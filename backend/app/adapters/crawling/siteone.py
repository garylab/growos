"""SiteOne Crawler adapter (https://crawler.siteone.io, MIT). Runs the bundled binary and normalizes its JSON output
into PageSnapshot / AuditFinding records. We do not re-implement what SiteOne already audits."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import urlsplit

from app.adapters.base import Capabilities, CollectResult, ConfigField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate
from app.core.config import get_settings
from app.core.safe_http import resolve_public_ip, validate_url

# SiteOne's xpath only sees the document body and the option list is comma-separated, so only simple,
# comma-free, body-level extractions are safe here. Head-level signals (canonical, robots, JSON-LD, OG) and
# contact/social links are collected separately for key pages — see app/services/page_signals.py.
EXTRA_COLUMNS = "Title,Description,H1=xpath://h1(500>)"

CONTENT_TYPES = {1: "html", 2: "js", 3: "css", 4: "image", 5: "audio", 6: "video", 7: "document", 8: "json",
                 9: "xml", 10: "font", 11: "redirect", 12: "other"}


@dataclass
class NormalizedPage:
    url: str
    path: str
    status_code: int | None
    content_type: str
    response_time_ms: int | None
    size_bytes: int | None
    title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    indexing: str | None = None
    robots_index: bool | None = None
    denied_by_robots_txt: bool | None = None
    headings_count: int | None = None
    headings_errors: int | None = None
    headings_structure: str | None = None
    canonical: str | None = None
    cache_type_flags: int | None = None
    cache_lifetime: int | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    metadata_captured: bool = False  # True when title/description/H1 were extracted for this page
    og: dict[str, Any] = field(default_factory=dict)
    seo_score: int | None = None


@dataclass
class NormalizedFinding:
    code: str
    category: str
    severity: str
    message: str
    url: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedCrawl:
    pages: list[NormalizedPage]
    findings: list[NormalizedFinding]
    quality_scores: dict[str, Any]
    summary: list[dict[str, Any]]
    stats: dict[str, Any]
    crawler_version: str | None
    total_urls: int
    html_pages: int
    count_by_status: dict[str, int]


class SiteOneCrawlerAdapter(ProviderAdapter):
    key: ClassVar[str] = "siteone"
    category: ClassVar[str] = "crawling"
    vendor: ClassVar[str] = "SiteOne"
    vendor_url: ClassVar[str] = "https://crawler.siteone.io"
    display_name: ClassVar[str] = "SiteOne Crawler (bundled)"
    description: ClassVar[str] = "Website crawler and technical/SEO audit engine bundled in the worker image."
    docs_url: ClassVar[str] = "https://crawler.siteone.io/"
    requires_connection: ClassVar[bool] = False
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("max_urls", "Max URLs per crawl", "number", 500),
        ConfigField("max_depth", "Max depth (0 = unlimited)", "number", 0),
        ConfigField("max_reqs_per_sec", "Max requests/second", "number", 5),
        ConfigField("workers", "Concurrent workers", "number", 3),
        ConfigField("timeout", "Request timeout (s)", "number", 10),
        ConfigField("ignore_robots_txt", "Ignore robots.txt", "boolean", False),
    ]

    def _bin(self) -> str:
        return os.environ.get("SITEONE_BIN") or get_settings().siteone_bin

    def installed(self) -> bool:
        binary = self._bin()
        return bool((os.path.isfile(binary) and os.access(binary, os.X_OK)) or shutil.which(binary))

    def health_check(self) -> HealthResult:
        binary = self._bin()
        if not self.installed():
            # Expected in the API container: crawling runs in the crawl worker, which is the only image carrying
            # the binary. The caller substitutes evidence from the last crawl; this is the fallback wording.
            return HealthResult(False, f"SiteOne is not installed in this service (looked for {binary}). Crawling "
                                       "runs in the crawler container — run a crawl to verify it there.")
        try:
            out = subprocess.run([binary, "--version", "--no-color"], capture_output=True, text=True, timeout=20)
            text = re.sub(r"\x1b\[[0-9;]*m", "", (out.stdout or out.stderr or "")).strip()
            version = text.splitlines()[0].replace("Version:", "").strip() if text else "unknown"
            return HealthResult(True, f"SiteOne available: {version}", {"version": version})
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Cannot execute SiteOne: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="crawling", measurement_type="observed",
                            features=["crawl", "sitemap", "technical_audit", "broken_links", "redirects", "metadata",
                                      "headings", "duplicates", "security_headers", "performance_timings"])

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        return UsageEstimate(requests=int(request.get("max_urls") or self.config["max_urls"]), unit_type="urls",
                             note="Requests are made to the target website only.")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        url = validate_url(request["url"])
        host = urlsplit(url).hostname or ""
        resolve_public_ip(host)  # SSRF guard before handing the URL to the external process
        cfg = {**self.config, **{k: v for k, v in request.items() if k in self.config}}
        settings = get_settings()
        workdir = tempfile.mkdtemp(prefix="siteone-")
        json_path = os.path.join(workdir, "output.json")
        cmd = [self._bin(), f"--url={url}", "--output=json", f"--output-json-file={json_path}",
               "--output-html-report=", "--output-text-file=", "--hide-progress-bar",
               f"--max-visited-urls={int(cfg['max_urls'])}", f"--workers={int(cfg['workers'])}",
               f"--max-reqs-per-sec={int(cfg['max_reqs_per_sec'])}", f"--timeout={int(cfg['timeout'])}",
               f"--user-agent={settings.crawl_user_agent}", "--no-color",
               # Per-URL metadata for every page (the report's seo/seo-headings tables are capped at 200 rows).
               f"--extra-columns={EXTRA_COLUMNS}"]
        if int(cfg.get("max_depth") or 0) > 0:
            cmd.append(f"--max-depth={int(cfg['max_depth'])}")
        if cfg.get("ignore_robots_txt"):
            cmd.append("--ignore-robots-txt")
        on_output = request.get("on_output")
        try:
            proc = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            tail: list[str] = []
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                tail.append(line)
                tail = tail[-50:]
                if on_output:
                    on_output(line)
            rc = proc.wait(timeout=int(request.get("max_runtime_seconds") or 3600))
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise ProviderError("SiteOne crawl exceeded the maximum runtime") from exc
        if not os.path.exists(json_path):
            raise ProviderError(f"SiteOne exited with code {rc} and produced no JSON output. Last output: "
                                + " | ".join(tail[-5:]))
        with open(json_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        shutil.rmtree(workdir, ignore_errors=True)
        return CollectResult(raw=raw, meta={"url": url, "exit_code": rc, "command": " ".join(cmd)})

    # ---------------------------------------------------------------- normalization
    def normalize(self, result: CollectResult) -> NormalizedCrawl:
        raw = result.raw
        tables = raw.get("tables", {})
        results = raw.get("results", [])
        rows = lambda name: tables.get(name, {}).get("rows", [])  # noqa: E731

        seo_by_path = {r.get("urlPathAndQuery"): r for r in rows("seo")}
        headings_by_path = {r.get("urlPathAndQuery"): r for r in rows("seo-headings")}
        og_by_path = {r.get("urlPathAndQuery"): r for r in rows("open-graph")}

        pages: list[NormalizedPage] = []
        findings: list[NormalizedFinding] = []
        html_pages = 0
        for r in results:
            url = r.get("url", "")
            parts = urlsplit(url)
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            ctype = CONTENT_TYPES.get(int(r.get("type") or 12), "other")
            status = _to_int(r.get("status"))
            page = NormalizedPage(url=url, path=path, status_code=status, content_type=ctype,
                                  response_time_ms=int(float(r.get("elapsedTime") or 0) * 1000),
                                  size_bytes=_to_int(r.get("size")), cache_type_flags=_to_int(r.get("cacheTypeFlags")),
                                  cache_lifetime=_to_int(r.get("cacheLifetime")))
            if ctype == "html" and status == 200:
                html_pages += 1
                extras = r.get("extras") if isinstance(r.get("extras"), dict) else {}
                seo = seo_by_path.get(path, {})
                if extras and "Title" in extras:  # per-URL extraction, available for every page
                    page.title = _clean(extras.get("Title"))
                    page.meta_description = _clean(extras.get("Description"))
                    page.h1 = _clean(extras.get("H1"))
                    page.indexing = seo.get("indexing") or None
                    page.robots_index = _to_bool(seo.get("robotsIndex")) if seo else None
                    page.metadata_captured = True
                elif seo:  # older artifacts: capped seo table only
                    page.title = seo.get("title") or None
                    page.meta_description = seo.get("description") or None
                    page.h1 = seo.get("h1") or None
                    page.indexing = seo.get("indexing") or None
                    page.robots_index = _to_bool(seo.get("robotsIndex"))
                    page.metadata_captured = True
                page.denied_by_robots_txt = _to_bool(seo.get("deniedByRobotsTxt")) if seo else None
                h = headings_by_path.get(path)
                if h:
                    page.headings_count = _to_int(h.get("headingsCount"))
                    page.headings_errors = _to_int(h.get("headingsErrorsCount"))
                    page.headings_structure = h.get("headings") or None
                og = og_by_path.get(path, {})
                page.og = {k: v for k, v in og.items() if k != "urlPathAndQuery" and v}
                findings.extend(_page_findings(page))
            pages.append(page)

        # Broken links and redirects discovered by the crawler
        for r in rows("404"):
            findings.append(NormalizedFinding("broken_link", "links", "critical",
                                              f"Broken link ({r.get('statusCode')}) found on {r.get('sourceUqId') or '?'}",
                                              url=r.get("url"), details={"source_page": r.get("sourceUqId"),
                                                                           "status_code": r.get("statusCode")}))
        for r in rows("redirects"):
            findings.append(NormalizedFinding("internal_redirect", "links", "warning",
                                              f"Link to redirecting URL ({r.get('statusCode')}) on {r.get('sourceUqId') or '?'}",
                                              url=r.get("url"), details={"target_url": r.get("targetUrl"),
                                                                           "source_page": r.get("sourceUqId"),
                                                                           "status_code": r.get("statusCode")}))
        for r in rows("non-unique-titles"):
            findings.append(NormalizedFinding("duplicate_title", "content", "warning",
                                              f"{r.get('count')} pages share the title “{(r.get('title') or '')[:80]}”",
                                              details={"count": _to_int(r.get("count")), "title": r.get("title")}))
        for r in rows("non-unique-descriptions"):
            findings.append(NormalizedFinding("duplicate_description", "content", "warning",
                                              f"{r.get('count')} pages share the same meta description",
                                              details={"count": _to_int(r.get("count")), "description": r.get("description")}))
        for r in rows("slowest-urls")[:10]:
            t = float(r.get("requestTime") or 0)
            if t >= 1.5:
                findings.append(NormalizedFinding("slow_response", "performance", "warning" if t < 3 else "critical",
                                                  f"Slow server response: {t:.2f}s", url=r.get("url"),
                                                  details={"request_time_s": t}))
        for r in rows("security"):
            # Security table rows describe header checks; keep as info-level technical findings.
            analysis = r.get("analysisName") or r.get("header") or ""
            crit = _to_int(r.get("critical")) or 0
            warn = _to_int(r.get("warning")) or 0
            if crit or warn:
                findings.append(NormalizedFinding("security_header", "security", "critical" if crit else "warning",
                                                  f"{analysis}: {crit} critical / {warn} warning page(s)",
                                                  details={k: v for k, v in r.items()}))
        for item in raw.get("summary", {}).get("items", []):
            if item.get("status") in ("CRITICAL", "WARNING"):
                findings.append(NormalizedFinding(f"site_{_slug(item.get('aplCode') or 'finding')}", "technical",
                                                  "critical" if item["status"] == "CRITICAL" else "warning",
                                                  item.get("text") or "", details={"apl_code": item.get("aplCode")}))

        # Page scores (0..100) from the page-level findings
        page_findings: dict[str, list[NormalizedFinding]] = {}
        for f in findings:
            if f.url:
                page_findings.setdefault(f.url, []).append(f)
        for page in pages:
            if page.content_type == "html" and page.status_code == 200:
                page.seo_score = _score_page(page_findings.get(page.url, []))

        stats = raw.get("stats", {})
        return NormalizedCrawl(
            pages=pages, findings=findings, quality_scores=raw.get("qualityScores", {}),
            summary=raw.get("summary", {}).get("items", []), stats=stats,
            crawler_version=(raw.get("crawler") or {}).get("version"),
            total_urls=int(stats.get("totalUrls") or len(results)), html_pages=html_pages,
            count_by_status={str(k): int(v) for k, v in (stats.get("countByStatus") or {}).items()},
        )


def _page_findings(page: NormalizedPage) -> list[NormalizedFinding]:
    out: list[NormalizedFinding] = []
    url = page.url
    if not page.metadata_captured:
        # Metadata unknown for this page (not extracted) — never report "missing" without evidence.
        if page.response_time_ms and page.response_time_ms > 1500:
            out.append(NormalizedFinding("slow_response", "performance", "warning",
                                         f"Server response took {page.response_time_ms} ms", url,
                                         {"response_time_ms": page.response_time_ms}))
        return out
    if not page.title:
        out.append(NormalizedFinding("missing_title", "metadata", "critical", "Page has no <title>", url))
    elif len(page.title) > 65:
        out.append(NormalizedFinding("title_too_long", "metadata", "warning",
                                     f"Title is {len(page.title)} characters (recommended ≤ 60)", url,
                                     {"length": len(page.title)}))
    elif len(page.title) < 15:
        out.append(NormalizedFinding("title_too_short", "metadata", "info",
                                     f"Title is only {len(page.title)} characters", url, {"length": len(page.title)}))
    if not page.meta_description:
        out.append(NormalizedFinding("missing_meta_description", "metadata", "warning", "Page has no meta description", url))
    elif len(page.meta_description) > 165:
        out.append(NormalizedFinding("meta_description_too_long", "metadata", "info",
                                     f"Meta description is {len(page.meta_description)} characters (recommended ≤ 160)",
                                     url, {"length": len(page.meta_description)}))
    if not page.h1:
        out.append(NormalizedFinding("missing_h1", "content", "warning", "Page has no <h1>", url))
    if page.headings_errors:
        out.append(NormalizedFinding("heading_structure", "content", "info",
                                     f"Heading hierarchy has {page.headings_errors} structural error(s)", url,
                                     {"structure": page.headings_structure}))
    if page.robots_index is False:
        out.append(NormalizedFinding("noindex", "technical", "info", "Page is marked noindex", url,
                                     {"indexing": page.indexing}))
    if page.canonical:
        canon = page.canonical.rstrip("/").lower()
        if canon != page.url.rstrip("/").lower():
            out.append(NormalizedFinding("canonical_elsewhere", "technical", "info",
                                         f"Canonical points to a different URL: {page.canonical}", url,
                                         {"canonical": page.canonical}))
    if page.response_time_ms and page.response_time_ms > 1500:
        out.append(NormalizedFinding("slow_response", "performance", "warning",
                                     f"Server response took {page.response_time_ms} ms", url,
                                     {"response_time_ms": page.response_time_ms}))
    return out


SEVERITY_PENALTY = {"critical": 25, "warning": 10, "info": 3}


def _score_page(findings: list[NormalizedFinding]) -> int:
    score = 100
    for f in findings:
        score -= SEVERITY_PENALTY.get(f.severity, 0)
    return max(0, score)


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    import html
    s = html.unescape(str(v)).strip()
    return s or None


def _to_int(v: Any) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_bool(v: Any) -> bool | None:
    if v in (None, ""):
        return None
    return str(v).lower() in ("1", "true", "yes")


def _slug(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")
