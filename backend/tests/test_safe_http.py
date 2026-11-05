import ipaddress

import pytest

from app.core.safe_http import UnsafeURLError, is_public_ip, validate_hostname, validate_url


@pytest.mark.parametrize("ip,expected", [
    ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.5.5", False), ("192.168.1.1", False),
    ("169.254.169.254", False), ("100.64.1.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("8.8.8.8", True), ("1.1.1.1", True), ("::1", False), ("::ffff:127.0.0.1", False), ("::ffff:8.8.8.8", True),
    ("fe80::1", False), ("fd00::1", False), ("2606:4700::1111", True), ("2002:7f00:1::", False),
])
def test_is_public_ip(ip, expected):
    assert is_public_ip(ipaddress.ip_address(ip)) is expected


@pytest.mark.parametrize("url", [
    "ftp://example.com/", "file:///etc/passwd", "http://localhost/", "http://127.0.0.1/", "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/", "http://metadata.google.internal/", "http://user:pass@example.com/",
    "http://example.com:6379/", "http://intranet/", "http://foo.internal/", "http://10.0.0.1:8080/",
])
def test_validate_url_rejects(url):
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_validate_url_accepts_public():
    assert validate_url("https://example.com/path?q=1") == "https://example.com/path?q=1"
    assert validate_hostname("Example.COM.") == "example.com"


def test_allowlist_entry_with_a_port_opens_only_that_port(monkeypatch):
    import pytest

    from app.core import safe_http

    monkeypatch.setattr(safe_http, "allowed_hosts", lambda: {"internal-feed:8931"})
    assert safe_http.validate_url("http://internal-feed:8931/feed") == "http://internal-feed:8931/feed"
    with pytest.raises(safe_http.UnsafeURLError, match="Port 9999"):
        safe_http.validate_url("http://internal-feed:9999/feed")


def test_bare_allowlist_entry_opens_any_port(monkeypatch):
    from app.core import safe_http

    monkeypatch.setattr(safe_http, "allowed_hosts", lambda: {"internal-feed"})
    assert safe_http.validate_url("http://internal-feed:9999/feed") == "http://internal-feed:9999/feed"


def test_unusual_port_still_blocked_for_everyone_else(monkeypatch):
    import pytest

    from app.core import safe_http

    monkeypatch.setattr(safe_http, "allowed_hosts", lambda: {"internal-feed"})
    with pytest.raises(safe_http.UnsafeURLError, match="Port 8931"):
        safe_http.validate_url("https://example.com:8931/feed")


def test_allowlist_permits_an_operator_named_private_host(monkeypatch):
    """OUTBOUND_ALLOW_HOSTS is deployment config, so it may name a service that resolves privately."""
    from app.core import safe_http

    monkeypatch.setattr(safe_http, "allowed_hosts", lambda: {"internal-feed"})
    assert safe_http.validate_hostname("internal-feed") == "internal-feed"
    assert safe_http.validate_hostname("Internal-Feed.") == "internal-feed"


def test_allowlist_does_not_leak_to_other_hosts(monkeypatch):
    import pytest

    from app.core import safe_http

    monkeypatch.setattr(safe_http, "allowed_hosts", lambda: {"internal-feed"})
    for bad in ("localhost", "127.0.0.1", "169.254.169.254", "other-internal"):
        with pytest.raises(safe_http.UnsafeURLError):
            safe_http.validate_hostname(bad)


def test_allowlist_is_empty_by_default():
    from app.core.safe_http import allowed_hosts

    assert allowed_hosts() == set()
