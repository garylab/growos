"""SSRF-safe outbound HTTP for user-supplied URLs (crawl targets, feeds, competitor pages).

Defences:
- Only http/https schemes.
- Hostname resolved up front; every resolved address must be public (no loopback, link-local, private,
  CGNAT, multicast, reserved, cloud metadata 169.254.169.254, IPv4-mapped IPv6, etc.).
- The connection is pinned to the validated IP (URL host replaced by the IP, Host header + SNI set to the
  original hostname) so a DNS answer cannot change between validation and connection (DNS rebinding).
- Redirects are never followed automatically; each hop is re-validated with the same rules.
- Response size and timeout are capped.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import get_settings

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata", "instance-data"}


class UnsafeURLError(ValueError):
    """Raised when a URL must not be fetched."""


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
        elif ip.teredo is not None:
            return False
        elif ip.is_site_local:
            return False
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
            or ip.is_unspecified):
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        for net in ("0.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16", "192.0.0.0/24", "198.18.0.0/15", "240.0.0.0/4"):
            if ip in ipaddress.ip_network(net):
                return False
    return ip.is_global


def allowed_hosts() -> set[str]:
    """Entries from OUTBOUND_ALLOW_HOSTS: either `host` (any port) or `host:port` (that port only)."""
    raw = get_settings().outbound_allow_hosts or ""
    return {h.strip().lower().rstrip(".") for h in raw.split(",") if h.strip()}


def is_allowlisted(hostname: str, port: int | None = None) -> bool:
    """True when the operator has explicitly permitted this host (and port) despite it resolving privately."""
    host = (hostname or "").strip().rstrip(".").lower()
    if not host:
        return False
    entries = allowed_hosts()
    if host in entries:
        return True
    return port is not None and f"{host}:{port}" in entries


def validate_hostname(hostname: str) -> str:
    host = hostname.strip().rstrip(".").lower()
    # The allowlist is deployment configuration, so it outranks every other rule including the blocked names.
    if is_allowlisted(host) or any(e.split(":")[0] == host for e in allowed_hosts()):
        return host
    if not host or host in BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".internal"):
        raise UnsafeURLError(f"Hostname not allowed: {hostname!r}")
    literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    try:  # literal IP in the URL
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_ip(literal):
            raise UnsafeURLError(f"IP address not allowed: {host}")
        return host
    if "." not in host:
        raise UnsafeURLError(f"Unqualified hostname not allowed: {host}")
    return host


def resolve_public_ip(hostname: str) -> str:
    """Resolve and return one validated public IP; every answer must be public."""
    host = validate_hostname(hostname)
    if any(e.split(":")[0] == host for e in allowed_hosts()):
        try:  # an allowlisted host may legitimately be a private service name
            return socket.getaddrinfo(host, None)[0][4][0]
        except OSError as exc:
            raise UnsafeURLError(f"Could not resolve {host}: {exc}") from exc
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host}: {exc}") from exc
    addresses = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not is_public_ip(ip):
            raise UnsafeURLError(f"{host} resolves to a non-public address ({ip}); refusing to connect")
        addresses.append(ip)
    if not addresses:
        raise UnsafeURLError(f"No addresses for {host}")
    # Prefer IPv4 for widest compatibility.
    for ip in addresses:
        if isinstance(ip, ipaddress.IPv4Address):
            return str(ip)
    return str(addresses[0])


def validate_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Only http/https URLs are allowed (got {parts.scheme!r})")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    if not parts.hostname:
        raise UnsafeURLError("URL has no hostname")
    validate_hostname(parts.hostname)
    # An allowlisted service may listen anywhere; everything else is limited to the usual web ports.
    if (parts.port and parts.port not in (80, 443, 8080, 8443)
            and not is_allowlisted(parts.hostname, parts.port)):
        raise UnsafeURLError(f"Port {parts.port} is not allowed for outbound fetches")
    return urlunsplit(parts)


@dataclass
class SafeResponse:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    redirects: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        enc = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            enc = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


def safe_get(url: str, *, max_redirects: int = 5, timeout: float | None = None, max_bytes: int | None = None,
             headers: dict[str, str] | None = None) -> SafeResponse:
    settings = get_settings()
    timeout = timeout or settings.outbound_timeout_seconds
    max_bytes = max_bytes or settings.outbound_max_bytes
    base_headers = {"User-Agent": settings.crawl_user_agent, "Accept": "*/*"}
    if headers:
        base_headers.update(headers)

    current = validate_url(url)
    redirects: list[str] = []
    with httpx.Client(follow_redirects=False, timeout=timeout) as client:
        for _ in range(max_redirects + 1):
            parts = urlsplit(current)
            host = parts.hostname or ""
            ip = resolve_public_ip(host)
            pinned_netloc = (f"[{ip}]" if ":" in ip else ip) + (f":{parts.port}" if parts.port else "")
            pinned_url = urlunsplit((parts.scheme, pinned_netloc, parts.path or "/", parts.query, ""))
            req_headers = dict(base_headers)
            req_headers["Host"] = host + (f":{parts.port}" if parts.port else "")
            extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
            with client.stream("GET", pinned_url, headers=req_headers, extensions=extensions) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    location = httpx.URL(current).join(resp.headers["location"])
                    redirects.append(str(location))
                    current = validate_url(str(location))
                    continue
                chunks = []
                size = 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise UnsafeURLError(f"Response exceeded {max_bytes} bytes")
                    chunks.append(chunk)
                return SafeResponse(url=url, final_url=current, status_code=resp.status_code,
                                    headers={k.lower(): v for k, v in resp.headers.items()},
                                    content=b"".join(chunks), redirects=redirects)
    raise UnsafeURLError("Too many redirects")
