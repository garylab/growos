"""Growth Plan playbook: turns collected data into a user-facing checklist.

Three sections:
- setup:   things to connect/define before the platform can help (Search Console, competitors, prompts …)
- fix:     one-time website/content fixes with the affected pages listed (verified as resolved by the next crawl)
- routine: recurring habits (weekly article, video, community, backlinks, monthly competitor review …) with concrete
           placeholders (topics, outlines, targets) derived from the project's own data.
Every item explains why it matters and what to do. Items are upserted by key so user status survives regeneration.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.intelligence import data as D
from app.intelligence.scoring import EFFORT_FACTOR, clamp, expected_ctr, priority_score
from app.models import (ActionRecord, AIAnswerObservation, BrandMention, CollectionJob, PageSnapshot, PlanItem, Project,
                        PromptDefinition, SearchObservation)
from app.services.providers import list_connections_for

CADENCE_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


@dataclass
class Draft:
    key: str
    section: str
    category: str
    title: str
    why: str
    steps: list[str]
    impact: float = 50
    effort: int = 2
    cadence: str = "once"
    suggestions: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    source: str = "playbook"
    confidence: float = 0.75          # how sure the evidence is: first-party data high, heuristics lower
    origin: str = "rule"              # rule | ai | user
    target_urls: list[str] = field(default_factory=list)
    target_keywords: list[str] = field(default_factory=list)


# =====================================================================================  helpers
def _pages_for(findings, limit: int = 60) -> list[dict[str, Any]]:
    seen, out = set(), []
    for f in findings:
        if f.url and f.url not in seen:
            seen.add(f.url)
            out.append({"url": f.url, "detail": f.message, **({k: v for k, v in (f.details or {}).items() if k in ("length", "source_page", "target_url", "count", "title", "response_time_ms")})})
        if len(out) >= limit:
            break
    return out


def _outline(topic: str, brand: str, competitors: list[str], kind: str = "article") -> list[str]:
    comp = f" vs {', '.join(competitors[:2])}" if competitors else ""
    if kind == "video":
        return [f"Hook (0-5s): the pain behind “{topic}”", "Show the problem with a real example", f"Demo how {brand} solves it (screen recording)",
                f"One concrete tip the viewer can apply today", f"CTA: try {brand} (link in description)"]
    return [f"Intro: who searches “{topic}” and what they need", "Short answer in 2-3 sentences (good for AI answers and featured snippets)",
            "Step-by-step / detailed section with examples", f"How {brand} helps{comp} (honest comparison)",
            "FAQ: 3-5 related questions", f"CTA: try {brand}, with an internal link to the relevant product page"]


def _seo_title_placeholder(query: str, brand: str) -> str:
    q = query.strip().capitalize()
    return f"{q}: [benefit / number / year] | {brand}"


# =====================================================================================  SETUP
def setup_items(db: Session, project: Project) -> list[Draft]:
    out = []
    domains = D.primary_domains(db, project.id)
    if not domains:
        out.append(Draft("setup:website", "setup", "setup", "Add your website", "Nothing can be measured without the site to track.",
                         ["Settings → Websites → add your main domain"], impact=100, effort=1))
        return out
    has_crawl = any(D.latest_crawl_run(db, d.id) for d in domains)
    if not has_crawl:
        out.append(Draft("setup:crawl", "setup", "setup", "Run the first website audit",
                         "The audit finds broken pages, missing titles and other issues that cost you rankings.",
                         ["SEO Performance → Run crawl & audit (takes a few minutes)"], impact=90, effort=1))
    if not any(D.gsc_available(db, d.id) for d in domains):
        out.append(Draft("setup:search_console", "setup", "setup", "Connect Google Search Console",
                         "It is the only first-party source of which searches bring people to your site; most content tasks are derived from it.",
                         ["Integrations → Google Search Console → Connect with Google", "SEO Performance → Search performance → confirm the property → Sync"],
                         impact=95, effort=1))
    if not any(D.analytics_landing_pages(db, d.id, 90) for d in domains):
        out.append(Draft("setup:analytics", "setup", "setup", "Connect Google Analytics 4",
                         "Knowing which pages bring sessions but no sign-ups shows where sales are lost.",
                         ["Integrations → Google Analytics 4 → Connect with Google", "Actions & Results → Website analytics → set the property → Sync GA4"],
                         impact=70, effort=1))
    if not D.competitors(db, project.id):
        out.append(Draft("setup:competitors", "setup", "setup", "Add 3-5 competitors",
                         "Competitor names are needed to see who AI assistants and communities recommend instead of you.",
                         ["Competitors → Add competitor (name, aliases, website, pricing page URL to watch)"], impact=80, effort=1))
    if len(D.target_keywords(db, project.id)) < 5:
        sugg = []
        for d in domains:
            sugg += [q["query"] for q in D.gsc_top_queries(db, d.id, 90, 15)]
        out.append(Draft("setup:keywords", "setup", "setup", "Define 10+ target keywords",
                         "Target keywords drive the content gap analysis and progress tracking.",
                         ["Settings → Target keywords → add the phrases customers use when they look for what you sell"],
                         impact=70, effort=1, suggestions={"keywords": list(dict.fromkeys(sugg))[:15]}))
    prompts = db.scalars(select(PromptDefinition).where(PromptDefinition.project_id == project.id, PromptDefinition.is_active.is_(True))).all()
    if len(prompts) < 5:
        base = [k.text for k in D.target_keywords(db, project.id)][:5] or [project.name]
        sugg = [f"What is the best tool for {k}?" for k in base[:3]] + [f"{project.brand_name} alternatives", f"Is {project.brand_name} worth it?",
                                                                       f"How do I {base[0]}?" if base else f"How do I get started with {project.brand_name}?"]
        out.append(Draft("setup:prompts", "setup", "ai_visibility", "Add 10+ prompts customers ask AI assistants",
                         "AI answers are a growing acquisition channel; prompts are how we measure whether you appear in them.",
                         ["GEO AI Visibility → Add prompts (intent: commercial/comparison), 3 samples per run"],
                         impact=75, effort=1, suggestions={"prompts": sugg}))
    if not list_connections_for(db, project.id, "ai"):
        out.append(Draft("setup:ai_provider", "setup", "ai_visibility", "Connect an AI provider (OpenAI or Gemini)",
                         "Needed to run AI visibility prompts and the AI analyst.", ["Integrations → OpenAI / Gemini → add API key"], impact=75, effort=1))
    return out


# =====================================================================================  FIX (website)
FIX_RULES: dict[str, dict[str, Any]] = {
    "missing_title":            {"title": "Add page titles to {n} page(s)", "why": "The title is the headline in Google results and the first thing AI assistants read about a page.", "impact": 85, "effort": 2, "category": "website",
                                 "steps": ["Write a unique 50-60 character title per page: primary phrase + benefit + brand", "Deploy and re-run the audit to verify"]},
    "missing_meta_description": {"title": "Write meta descriptions for {n} page(s)", "why": "Descriptions do not affect ranking but strongly affect whether people click.", "impact": 55, "effort": 2, "category": "website",
                                 "steps": ["120-155 characters, include the search phrase and a reason to click", "Prioritise pages with impressions in Search Console"]},
    "title_too_long":           {"title": "Shorten {n} page title(s) over 60 characters", "why": "Long titles get cut off in results, losing the message.", "impact": 35, "effort": 1, "category": "website", "steps": ["Keep the keyword at the start, move the brand to the end or drop it"]},
    "meta_description_too_long":{"title": "Shorten {n} meta description(s)", "why": "Truncated descriptions look unfinished in results.", "impact": 20, "effort": 1, "category": "website", "steps": ["Cut to ≤155 characters; end with a call to action"]},
    "missing_h1":               {"title": "Add an H1 heading to {n} page(s)", "why": "The H1 tells search engines and AI what the page is about.", "impact": 45, "effort": 1, "category": "website", "steps": ["One H1 per page matching the page's main phrase"]},
    "heading_structure":        {"title": "Fix heading order on {n} page(s)", "why": "Skipped heading levels confuse crawlers and screen readers.", "impact": 15, "effort": 2, "category": "website", "steps": ["Use H2 for sections, H3 for sub-sections; do not skip levels"]},
    "duplicate_title":          {"title": "Make {n} duplicated title group(s) unique", "why": "Pages with the same title compete with each other and look like duplicates.", "impact": 50, "effort": 2, "category": "website", "steps": ["Give each page a title describing its specific content"]},
    "duplicate_description":    {"title": "Make {n} duplicated meta description group(s) unique", "why": "Duplicated descriptions lower click-through.", "impact": 25, "effort": 2, "category": "website", "steps": ["Write page-specific descriptions"]},
    "broken_link":              {"title": "Fix {n} broken link(s)", "why": "Broken links waste crawl budget and lose visitors.", "impact": 60, "effort": 1, "category": "website", "steps": ["Fix the destination or redirect it (301)", "Update the linking page"]},
    "internal_redirect":        {"title": "Point {n} internal link(s) directly to the final URL", "why": "Redirect chains slow pages and leak link value.", "impact": 20, "effort": 1, "category": "website", "steps": ["Replace the link with the redirect target"]},
    "slow_response":            {"title": "Speed up {n} slow page(s) (server response > 1.5 s)", "why": "Slow pages rank lower and convert worse.", "impact": 55, "effort": 3, "category": "website", "steps": ["Cache the page or its data", "Check hosting/database queries", "Measure again with Lighthouse"]},
    "security_header":          {"title": "Add missing security headers", "why": "HSTS, CSP and X-Frame-Options protect users against XSS, clickjacking and MITM, and are a trust signal browsers and scanners check.", "impact": 30, "effort": 2, "category": "website",
                                 "steps": ["Check what is actually missing first — many sites already send most of these: `curl -sI https://your-domain.com | grep -iE 'content-security|strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy'`. Only add the ones that are absent.",
                                           "Content-Security-Policy is the important and hardest one, and usually the only one missing. Start in report-only so nothing breaks: `Content-Security-Policy-Report-Only: default-src 'self'; img-src 'self' data: https:; script-src 'self'; style-src 'self' 'unsafe-inline'`. Watch for violations, loosen as needed, then switch the header name to `Content-Security-Policy` to enforce.",
                                           "Add any of the rest that are missing: `Strict-Transport-Security: max-age=31536000; includeSubDomains`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: geolocation=(), camera=(), microphone=()`.",
                                           "Set them where your responses are built — Cloudflare: Rules → Transform Rules → Modify Response Header. Nginx: `add_header` in the server block. Apache: `Header set`. Next.js: the `headers()` function in next.config.js.",
                                           "Verify with the curl above or securityheaders.com, then re-run the audit."]},
}
SITE_RULES = {
    "site_brotli_support": {"title": "Enable Brotli compression", "why": "Brotli shrinks HTML, CSS and JavaScript 15-25% more than gzip, so pages download and render faster — a ranking and conversion signal.", "impact": 25, "effort": 1,
                            "steps": ["On Cloudflare: Brotli is already on by default — the manual toggle was removed in 2024, so there is nothing to switch on. It auto-selects Brotli/gzip per visitor; tune it only if needed under Rules → Compression Rules. On Fastly/CloudFront: enable Brotli in the compression/behaviour settings.",
                                      "On Nginx: add the ngx_brotli module, then `brotli on; brotli_comp_level 5; brotli_types text/html text/css application/javascript application/json image/svg+xml;` and reload.",
                                      "On Apache: enable mod_brotli, then `AddOutputFilterByType BROTLI_COMPRESS text/html text/css application/javascript application/json image/svg+xml` and restart.",
                                      "Verify: `curl -s -H 'Accept-Encoding: br' -I https://your-domain.com` should return `content-encoding: br`. Then re-run the audit."]},
    "site_webp_support": {"title": "Serve images as WebP/AVIF", "why": "Modern formats cut image weight 30-50%, so pages load faster.", "impact": 30, "effort": 2,
                          "steps": ["Easiest is automatic format negotiation: Next.js → `images: { formats: ['image/avif','image/webp'] }` in next.config.js; Cloudflare → Polish (Pro+); Cloudinary → `f_auto`; imgix → `auto=format`.",
                                    "No image CDN? Convert at build time (sharp, `cwebp`, Squoosh) and serve `<picture>` with WebP/AVIF sources plus a PNG/JPEG fallback.",
                                    "Verify: `curl -H 'Accept: image/webp' -I <image-url>` should return `content-type: image/webp`, then re-run the audit."]},
    "site_avif_support": {"title": "Serve images as AVIF where supported", "why": "AVIF is ~20% smaller than WebP for the same quality.", "impact": 15, "effort": 2,
                          "steps": ["Next.js: put `image/avif` first in `images.formats`. Cloudflare Polish, Cloudinary (`f_auto`) and imgix (`auto=format`) negotiate AVIF automatically once enabled.",
                                    "For static assets, generate `.avif` alongside `.webp` (sharp or `avifenc`) and list it first in `<picture>`.",
                                    "Verify: `curl -H 'Accept: image/avif' -I <image-url>` should return `content-type: image/avif`, then re-run the audit."]},
    "site_ssl_protocol_unsafe": {"title": "Disable TLS 1.0/1.1", "why": "Old TLS versions are insecure and flagged by security scanners.", "impact": 25, "effort": 1, "steps": ["Allow TLS 1.2+ only on the load balancer/CDN"]},
}


def fix_items(db: Session, project: Project) -> list[Draft]:
    out = []
    comps = [c.name for c in D.competitors(db, project.id)]
    for domain in D.primary_domains(db, project.id):
        run = D.latest_crawl_run(db, domain.id)
        if not run:
            continue
        home = db.scalar(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run.id, PageSnapshot.path == "/"))
        sig = (home.signals or {}) if home else {}
        findings = D.crawl_findings(db, run.id, ("critical", "warning", "info"))
        by_code: dict[str, list] = defaultdict(list)
        for f in findings:
            by_code[f.code].append(f)
        for code, fs in by_code.items():
            # SiteOne's probes do not advertise Accept-Encoding: br, nor negotiate image/webp / image/avif, so it
            # flags these as missing even on sites that serve them. When our own home-page check confirmed support,
            # drop the false finding so it does not become a task.
            if code == "site_brotli_support" and sig.get("serves_brotli"):
                continue
            if code == "site_webp_support" and sig.get("serves_webp"):
                continue
            if code == "site_avif_support" and sig.get("serves_avif"):
                continue
            rule = FIX_RULES.get(code) or SITE_RULES.get(code)
            if not rule:
                continue
            n = len({f.url for f in fs if f.url}) or len(fs)
            out.append(Draft(f"fix:{domain.id}:{code}", "fix", rule.get("category", "website"), rule["title"].format(n=n), rule["why"], rule["steps"],
                             impact=min(100, rule["impact"] + min(15, n // 5)), effort=rule["effort"],
                             suggestions={"pages": _pages_for(fs), "count": n},
                             evidence=[{"table": "audit_findings", "record_ids": [str(f.id) for f in fs[:50]], "summary": f"{len(fs)} finding(s) in crawl {str(run.id)[:8]}"}],
                             source=f"crawl:{code}"))
        # Conversion & brand signals on the home page
        if home and sig.get("checked"):
            if not (sig.get("chat_link") or sig.get("tel") or sig.get("mailto")):
                out.append(Draft(f"fix:{domain.id}:contact_channel", "fix", "conversion", "Add a direct contact channel (WhatsApp click-to-chat, phone or email)",
                                 "Visitors with a question buy when they can ask it in one tap; the home page has no contact link.",
                                 ["Add a floating WhatsApp button linking to https://wa.me/<number>?text=<prefilled question>", "Show phone/email in the footer",
                                  "Re-run the audit to verify"], impact=70, effort=1, suggestions={"page": home.url}, source="signal:contact"))
            elif not sig.get("chat_link"):
                out.append(Draft(f"fix:{domain.id}:whatsapp", "fix", "conversion", "Add WhatsApp click-to-chat",
                                 "Chat converts better than forms for many markets; the page shows phone/email but no chat link.",
                                 ["Add a wa.me link/button on the home page and pricing page with a prefilled message"], impact=45, effort=1,
                                 suggestions={"page": home.url}, source="signal:whatsapp"))
            if not sig.get("has_organization_schema"):
                out.append(Draft(f"fix:{domain.id}:structured_data", "fix", "website", "Add Organization / Product structured data (JSON-LD)",
                                 "Structured data helps Google and AI assistants understand what the brand is, which improves rich results and AI mentions.",
                                 ["Add Organization (name, logo, sameAs social profiles) JSON-LD on the home page", "Add Product/SoftwareApplication or FAQ schema on key pages",
                                  "Validate with Google's Rich Results Test"], impact=55, effort=2,
                                 suggestions={"page": home.url, "found_schema_types": sig.get("jsonld_types")}, source="signal:jsonld"))
            if not sig.get("og_title") or not sig.get("og_image"):
                missing = [k for k in ("og:title", "og:image") if not sig.get(k.replace(":", "_"))]
                out.append(Draft(f"fix:{domain.id}:open_graph", "fix", "website", f"Add link-preview tags ({', '.join(missing)})",
                                 "Links shared on LinkedIn, X, WhatsApp or Slack without a preview image get far fewer clicks.",
                                 ["Add og:title, og:description and og:image (1200×630 PNG/JPG) to every page template",
                                  "Keep twitter:card = summary_large_image", "Test with LinkedIn Post Inspector or opengraph.xyz"],
                                 impact=40, effort=1, suggestions={"page": home.url, "missing": missing}, source="signal:og"))
            if not sig.get("social_links"):
                out.append(Draft(f"fix:{domain.id}:social_links", "fix", "brand", "Link your social profiles from the website",
                                 "Profile links connect the brand entity across the web (used by Google's knowledge graph and AI assistants).",
                                 ["Add LinkedIn, X, YouTube (and others you use) to the footer and to Organization sameAs"], impact=30, effort=1,
                                 suggestions={"page": home.url}, source="signal:social"))
        # Lighthouse
        slow = [o for o in D.latest_performance(db, domain.id) if o.measurement_type == "lab" and (o.scores.get("performance") or 100) < 50]
        if slow:
            out.append(Draft(f"fix:{domain.id}:lighthouse", "fix", "website", f"Improve Lighthouse performance on {len(slow)} key page(s)",
                             "Core Web Vitals are a ranking factor and slow pages lose visitors before they see the offer.",
                             ["Start with the top failing audits per page (images, render-blocking JS, server time)", "Re-run Lighthouse to confirm"],
                             impact=60, effort=3, suggestions={"pages": [{"url": o.url, "score": o.scores.get("performance"), "audits": [a.get("title") for a in (o.audits or [])[:4]]} for o in slow]},
                             source="lighthouse"))
        # Search Console: low CTR + striking distance
        if D.gsc_available(db, domain.id):
            rows = D.gsc_query_page_rows(db, domain.id, 28, 50, 400)
            low = []
            for r in rows:
                if 0 < r["position"] <= 10 and r["ctr"] < expected_ctr(r["position"]) * 0.5:
                    low.append({"query": r["query"], "page": r["page"], "impressions": r["impressions"], "clicks": r["clicks"], "ctr": round(r["ctr"], 4), "position": round(r["position"], 1),
                                "title_placeholder": _seo_title_placeholder(r["query"], project.brand_name)})
            if low:
                out.append(Draft(f"fix:{domain.id}:low_ctr", "fix", "content", f"Rewrite titles & descriptions for {len(low)} search(es) with low click-through",
                                 "These pages already rank on page 1 but people choose other results; a better snippet is the cheapest traffic gain.",
                                 ["For each query, rewrite the title to match the intent and add a benefit", "Mention the query in the first sentence of the page", "Check CTR again after 4 weeks"],
                                 impact=70, effort=2, suggestions={"queries": low[:25]}, source="gsc:low_ctr"))
            striking = [{"query": r["query"], "page": r["page"], "impressions": r["impressions"], "position": round(r["position"], 1)} for r in rows if 8 <= r["position"] <= 20]
            if striking:
                out.append(Draft(f"fix:{domain.id}:striking", "fix", "content", f"Push {len(striking)} search(es) from page 2 to page 1",
                                 "Rankings at positions 8-20 are the easiest to improve: Google already considers the page relevant.",
                                 ["Add the query to the title/H1 and expand the section answering it", "Add 2-3 internal links from related pages", "Refresh the publish date"],
                                 impact=65, effort=3, suggestions={"queries": sorted(striking, key=lambda r: -r["impressions"])[:25]}, source="gsc:striking"))
        out += _coverage_rules(db, project, domain)
        out += _opportunity_rules(db, project, domain)

    # AI visibility: prompts where the brand is absent
    runs = D.latest_runs(db, project.id, 1)
    if runs:
        absent = [r for r in D.visibility_by_prompt(db, project.id, runs[0]) if r["brand_mention_rate"] == 0]
        if absent:
            seen = {}
            for r in absent:
                seen.setdefault(r["prompt_id"], {"prompt": r["prompt"], "intent": r["intent"], "providers": [], "competitors": {}})
                seen[r["prompt_id"]]["providers"].append(r["provider"])
                for n, v in r["competitors"].items():
                    seen[r["prompt_id"]]["competitors"][n] = max(seen[r["prompt_id"]]["competitors"].get(n, 0), v["rate"])
            out.append(Draft("fix:ai_absent", "fix", "ai_visibility", f"Create content for {len(seen)} prompt(s) where AI assistants never mention you",
                             "When someone asks ChatGPT/Gemini these questions, competitors get recommended and you do not.",
                             ["Publish a page that answers each prompt directly (clear facts, comparison table, FAQ)", "Get the page cited on sites AI already trusts (see Backlinks routine)",
                              "Re-run AI visibility in 4-6 weeks"], impact=75, effort=4,
                             suggestions={"prompts": [{**v, "outline": _outline(v["prompt"], project.brand_name, list(v["competitors"]))} for v in list(seen.values())[:15]]},
                             source="geo:absent"))
    return out


# =====================================================================================  ROUTINE
def _topic_pool(db: Session, project: Project) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    comps = [c.name for c in D.competitors(db, project.id)]
    for d in D.primary_domains(db, project.id):
        if D.gsc_available(db, d.id):
            for r in D.gsc_query_page_rows(db, d.id, 90, 20, 300):
                if 8 <= r["position"] <= 30:
                    pool.append({"topic": r["query"], "source": "Search Console", "reason": f"ranks #{r['position']:.0f} with {r['impressions']} impressions in 90 days — a better page can reach page 1",
                                 "score": r["impressions"] / max(1, r["position"]), "page": r["page"]})
    runs = D.latest_runs(db, project.id, 1)
    if runs:
        for r in D.visibility_by_prompt(db, project.id, runs[0]):
            if r["brand_mention_rate"] < 0.5:
                pool.append({"topic": r["prompt"], "source": "AI visibility", "reason": f"{r['provider']} mentions you in only {r['brand_mention_rate']:.0%} of answers", "score": 50 * (1 - r["brand_mention_rate"])})
    for kw in D.target_keywords(db, project.id):
        pool.append({"topic": kw.text, "source": "Target keyword", "reason": f"importance {kw.importance}/5", "score": 8 * kw.importance})
    # de-duplicate by topic text
    seen, out = set(), []
    for t in sorted(pool, key=lambda t: -t["score"]):
        k = t["topic"].lower().strip()
        if k not in seen:
            seen.add(k)
            out.append(t)
    for t in out:
        t["outline"] = _outline(t["topic"], project.brand_name, comps)
        t["video_script"] = _outline(t["topic"], project.brand_name, comps, "video")
    return out



STAGING_PATTERNS = ("dev", "staging", "stage", "test", "preview", "uat", "demo", "beta", "tmp", "old", "www2")


def _coverage_rules(db: Session, project: Project, domain) -> list[Draft]:
    """Indexing, subdomain leaks, crawl coverage, hreflang, cannibalization, comparison pages and tracking."""
    out: list[Draft] = []
    run = D.latest_crawl_run(db, domain.id)
    if run is None:
        return out
    pages = D.html_pages(db, run.id)
    crawled = {p.url.rstrip("/") for p in pages}
    host = domain.hostname.lower().removeprefix("www.")
    # If the crawl stopped at its URL limit we only saw part of the site; claims about "missing" pages must say so.
    crawl_limit = int((run.config or {}).get("max_urls") or 0)
    crawl_capped = bool(crawl_limit and run.total_urls >= crawl_limit)
    checked = [p for p in pages if (p.signals or {}).get("checked")]
    sig = (checked[0].signals if checked else {})

    # --- conversion tracking installed?
    if checked and not sig.get("analytics"):
        out.append(Draft(f"fix:{domain.id}:tracking", "fix", "conversion", "Install website analytics / conversion tracking",
                         "Without tracking you cannot tell which pages, searches or campaigns actually produce customers — "
                         "every other decision in this plan becomes guesswork.",
                         ["Add Google Analytics 4 (or Umami/Plausible if you prefer self-hosted) to every page",
                          "Define a key event for the action that matters: signup, purchase, booking",
                          "Connect it under Integrations so the plan can see conversions per page",
                          "If you already have tracking that loads only after the page becomes interactive, confirm it fires and tick this off"],
                         impact=80, effort=2, suggestions={"page": (checked[0].url if checked else domain.base_url),
                                                            "detected": {"analytics_tags_found": sig.get("analytics") or []},
                                                            "note": "We look for known analytics tags in the HTML your server returns. "
                                                                    "Tags injected only by client-side JavaScript may not be visible to us — verify before acting."},
                         source="signal:analytics"))

    out.extend(_ai_crawler_rules(domain, run))

    if not D.gsc_available(db, domain.id):
        return out
    gsc_pages = D.gsc_pages(db, domain.id, 90)
    earning = {r["page"].rstrip("/") for r in gsc_pages}

    # --- 1. pages that exist but earn nothing
    silent = sorted(crawled - earning)
    if pages and len(silent) >= max(10, len(crawled) * 0.3):
        out.append(Draft(f"fix:{domain.id}:indexing_gap", "fix", "content",
                         f"{len(silent)} of {len(crawled)} pages get no search traffic at all",
                         "Pages that earn nothing in 90 days are usually thin, duplicated, not linked from anywhere, or not indexed. "
                         "They dilute the site and waste the crawl budget that should go to your money pages.",
                         ["Check a sample in Google Search Console → URL Inspection: indexed, or excluded?",
                          "Decide per group: improve it, merge it into a stronger page, or noindex it",
                          "Make sure every page you keep is linked from a page that already gets traffic",
                          "Submit an up-to-date sitemap"],
                         impact=85, effort=4,
                         suggestions={"count": len(silent), "pages": [{"url": u} for u in silent[:40]],
                                      "note": f"{len(earning)} page(s) earn impressions today, compared against the {len(crawled)} HTML pages in the last crawl."
                                              + (f" That crawl stopped at its limit of {crawl_limit} URLs, so this is a partial view — raise Max URLs on the SiteOne provider for the full picture." if crawl_capped else "")},
                         source="gsc:indexing_gap"))

    # --- 2. staging / other hosts showing up in search
    leaks = [h for h in D.gsc_hosts(db, domain.id, 90)
             if h["host"].removeprefix("www.") != host and (h["host"].endswith("." + host) or host in h["host"])
             and any(h["host"].split(".")[0].startswith(p) for p in STAGING_PATTERNS)]
    if leaks:
        out.append(Draft(f"fix:{domain.id}:staging_leak", "fix", "website",
                         f"Remove {len(leaks)} non-production site(s) from Google: {', '.join(h['host'] for h in leaks[:3])}",
                         "Staging or preview copies of your site compete with the real one, split your authority and can show "
                         "unfinished content to customers.",
                         ["Block them: HTTP auth, or robots.txt Disallow plus an X-Robots-Tag: noindex header",
                          "Remove the indexed URLs in Search Console → Removals",
                          "If a subdomain is a real product (app, help), keep it but give it its own canonical strategy"],
                         impact=75, effort=2, suggestions={"hosts": leaks}, source="gsc:staging"))

    # --- 3. pages Google knows that your own site never links to
    unseen = [] if crawl_capped else [r for r in gsc_pages if r["page"].rstrip("/") not in crawled
              and (r["page"].split("/")[2].lower().removeprefix("www.") == host) and r["impressions"] >= 5]
    if crawl_capped and len(crawled) >= 20:
        out.append(Draft(f"fix:{domain.id}:crawl_limit", "fix", "website",
                         f"Raise the crawl limit — the audit stopped after {crawl_limit} URLs",
                         "The site is bigger than the current crawl limit, so parts of it are never audited and the plan can only "
                         "judge what it has seen.",
                         [f"Integrations → SiteOne Crawler → raise Max URLs above {crawl_limit}",
                          "Re-run the audit from SEO Performance",
                          "If the extra URLs are low-value (filters, parameters, duplicates), exclude them instead"],
                         impact=45, effort=1,
                         suggestions={"crawled": run.total_urls, "limit": crawl_limit,
                                      "pages_google_knows": len({r["page"] for r in gsc_pages})},
                         source="crawl:limit"))
    if len(unseen) >= 5:
        out.append(Draft(f"fix:{domain.id}:crawl_gap", "fix", "website",
                         f"{len(unseen)} page(s) rank in Google but our crawler could not reach them from your site",
                         "If a crawler cannot walk to a page from your home page, neither can most visitors — and search engines "
                         "give those pages less weight. It usually means missing internal links or a stale sitemap.",
                         ["Link these pages from relevant navigation, footer or related content",
                          "Make sure they are in the sitemap referenced by robots.txt",
                          "If they are language versions, add a visible language switcher"],
                         impact=70, effort=3,
                         suggestions={"pages": sorted(unseen, key=lambda r: -r["impressions"])[:30]}, source="gsc:crawl_gap"))

    # --- 4. hreflang when several language versions earn traffic
    langs: dict[str, int] = defaultdict(int)
    for r in gsc_pages:
        parts = [p for p in r["page"].split("/") if p]
        if len(parts) >= 3 and len(parts[2]) == 2 and parts[2].isalpha():
            langs[parts[2].lower()] += r["impressions"]
    if len(langs) >= 2 and checked and not sig.get("hreflang"):
        out.append(Draft(f"fix:{domain.id}:hreflang", "fix", "website",
                         f"Add hreflang tags — you have {len(langs)} language versions and none declare each other",
                         "Without hreflang, Google treats your translations as duplicates and often shows the wrong language to the wrong "
                         "country, which quietly loses international sales.",
                         ["Add <link rel=\"alternate\" hreflang=\"xx\" href=\"…\"> for every language on every page, including x-default",
                          "Each language version must link to all the others, including itself",
                          "Validate in Search Console → International Targeting"],
                         impact=65, effort=3,
                         suggestions={"languages": sorted(({"language": k, "impressions": v} for k, v in langs.items()), key=lambda r: -r["impressions"]),
                                      "detected": {"hreflang_tags_found": sig.get("hreflang") or []}},
                         source="gsc:hreflang"))

    # --- 5. cannibalization
    pairs: dict[str, set[str]] = defaultdict(set)
    for r in D.gsc_query_page_rows(db, domain.id, 90, 20, 1000):
        pairs[r["query"]].add(r["page"])
    cannibal = [{"query": q, "pages": sorted(ps)} for q, ps in pairs.items() if len(ps) > 1 and not _is_brand_query(q, project)]
    if len(cannibal) >= 3:
        out.append(Draft(f"fix:{domain.id}:cannibalization", "fix", "content",
                         f"{len(cannibal)} search(es) where several of your pages compete with each other",
                         "When two pages target the same search, Google splits signals between them and usually ranks both lower "
                         "than one strong page would rank.",
                         ["For each search, pick the page that should win",
                          "Merge or differentiate the others, and link them to the winner",
                          "Redirect any page you retire (301)"],
                         impact=55, effort=3, suggestions={"queries": cannibal[:20]}, source="gsc:cannibalization"))

    # --- 6. branded search defense
    brand_rows = [r for r in D.gsc_top_queries(db, domain.id, 28, 100) if _is_brand_query(r["query"], project)]
    if brand_rows:
        worst = max(brand_rows, key=lambda r: r["position"])
        if worst["position"] > 3 or worst["ctr"] < 0.25:
            out.append(Draft(f"fix:{domain.id}:branded_search", "fix", "brand",
                             f"Win back your own name: “{worst['query']}” ranks #{worst['position']:.1f} with {worst['ctr']:.0%} click-through",
                             "People searching your brand name are your warmest buyers. If you are not the obvious first result, "
                             "someone else is intercepting them.",
                             ["Make sure your home page title starts with the brand name",
                              "Add Organization structured data with sameAs links to your social profiles",
                              "Claim directory and marketplace listings so they reinforce rather than outrank you",
                              "Consider a branded ad if a competitor bids on your name"],
                             impact=80, effort=2, suggestions={"queries": brand_rows[:5]}, source="gsc:branded"))

    # --- 7. comparison pages per competitor
    comps = D.competitors(db, project.id)
    if comps:
        blobs = [((p.title or "") + " " + p.path).lower() for p in pages]
        missing = [c.name for c in comps if not any(c.name.lower() in b for b in blobs)]
        has_alt_page = any("alternativ" in b for b in blobs)
        if missing or not has_alt_page:
            targets = missing or [c.name for c in comps]
            out.append(Draft(f"fix:{domain.id}:comparison_pages", "fix", "content",
                             f"Write comparison pages for {len(targets)} competitor(s)",
                             "“X vs Y” and “alternatives to X” searches are made by people about to choose — and these are the pages "
                             "AI assistants quote most when someone asks which tool to pick.",
                             ["One page per competitor: honest table of differences, who each tool suits best, pricing",
                              "Also write a single “alternatives to <your biggest competitor>” page",
                              "Link them from your pricing page and mention them where you answer the AI prompts"],
                             impact=75, effort=4,
                             suggestions={"pages_to_write": [{"title": f"{project.brand_name} vs {n}", "url_suggestion": f"/compare/{_slugify(project.brand_name)}-vs-{_slugify(n)}",
                                                              "outline": [f"Who {n} is for and who {project.brand_name} is for",
                                                                          "Feature-by-feature table", "Pricing side by side",
                                                                          "When to choose each (be honest — it builds trust and gets quoted)",
                                                                          "FAQ and migration notes"]} for n in targets[:8]]
                                           + ([] if has_alt_page else [{"title": f"Alternatives to {targets[0]}", "url_suggestion": f"/alternatives-to-{_slugify(targets[0])}",
                                                                        "outline": ["Shortlist of 5-7 options including yours", "What each is best at", "Pricing comparison", "How to switch"]}])},
                             source="content:comparison"))
    return out


# =====================================================================================  AI CRAWLER ACCESS
def _ai_crawler_rules(domain, run) -> list[Draft]:
    """robots.txt verdicts from the last crawl, turned into at most one item.

    Only blocks that cost visibility become a fix. A site that blocks GPTBot, CCBot or Google-Extended has opted
    out of model *training*, which is a deliberate policy decision with no effect on whether assistants can cite
    it — telling that user to "unblock the AI bots" would be wrong, so those tokens are reported as context
    inside the item and never raise one on their own.
    """
    ai = (run.stats or {}).get("ai_crawlers") or {}
    if not ai:
        return []

    # An unreadable robots.txt is the most severe case and the least visible: every page still loads in a
    # browser, so nothing looks wrong, while crawlers that cannot read the file back off the whole site.
    if ai.get("status") in ("server_error", "access_denied", "not_plain_text"):
        return [Draft(f"fix:{domain.id}:robots_unreadable", "fix", "website",
                      "Fix robots.txt — crawlers cannot read it",
                      str(ai.get("detail") or "robots.txt could not be read.") + " Until it is fixed, search "
                      "engines and AI assistants may stop fetching the site entirely, even though every page "
                      "still works for visitors.",
                      ["Open the robots.txt URL below and confirm it returns HTTP 200 with content-type text/plain",
                       "If a single-page-app catch-all route is answering it, serve robots.txt as a real static file",
                       "If it returns a 5xx, fix the error — crawlers read an unreachable robots.txt as 'disallow everything'",
                       "Re-check in Search Console → Settings → robots.txt"],
                      impact=95, effort=1, confidence=0.9,
                      suggestions={"robots_url": ai.get("url"), "status_code": ai.get("status_code"),
                                   "content_type": ai.get("content_type")},
                      source="robots:unreadable")]

    if not ai.get("checked"):
        return []

    answers = list(ai.get("blocked_answers") or [])
    search = list(ai.get("blocked_search") or [])
    training = list(ai.get("blocked_training") or [])
    partial = ai.get("partially_blocked") or {}
    by_token = {c["token"]: c for c in (ai.get("crawlers") or [])}

    # Partial blocks matter only for crawlers that are otherwise allowed in; a crawler already counted as blocked
    # site-wide must not be reported twice.
    visibility_partial = {t: paths for t, paths in partial.items()
                          if t not in answers and t not in search
                          and (by_token.get(t, {}).get("purpose") in ("answers", "search"))}

    if not answers and not search and not visibility_partial:
        return []

    blocked = answers + search
    if blocked:
        names = ", ".join(blocked[:4]) + (f" and {len(blocked) - 4} more" if len(blocked) > 4 else "")
        title = f"robots.txt blocks {len(blocked)} crawler(s) that AI assistants answer from: {names}"
        why = ("An assistant can only quote a page it was allowed to fetch. These crawlers are what ChatGPT, "
               "Perplexity, Copilot and AI Overviews read the web with, so while they are blocked the site "
               "cannot appear in those answers however good its content is. This is usually an accident — a "
               "copy-pasted 'block the AI bots' snippet that caught the retrieval crawlers along with the "
               "training ones.")
    else:
        names = ", ".join(sorted(visibility_partial)[:4])
        title = f"robots.txt hides some pages from AI assistants ({names})"
        why = ("The home page is reachable but some of the pages an assistant would actually cite sit under a "
               "disallowed path, so they can never be quoted or linked.")

    steps = ["Open the robots.txt URL below and find the rule lines listed in the evidence",
             "Remove the Disallow for the retrieval crawlers you want to be cited by (listed as 'answers' below)",
             "Keep any blocks you added on purpose — opting out of model training costs no visibility",
             "Re-run the site audit to confirm the change took effect"]

    return [Draft(f"fix:{domain.id}:ai_crawlers_blocked", "fix", "website", title, why, steps,
                  impact=90 if search else 80, effort=1, confidence=0.9,
                  suggestions={
                      "robots_url": ai.get("url"),
                      "blocked": [{"token": t, "operator": by_token.get(t, {}).get("operator"),
                                   "purpose": by_token.get(t, {}).get("purpose"),
                                   "cost": by_token.get(t, {}).get("what"),
                                   "rule": by_token.get(t, {}).get("matched_rule"),
                                   "named_by": by_token.get(t, {}).get("matched_group")} for t in blocked],
                      "blocked_paths": visibility_partial,
                      "blocked_for_training_only": training,
                      "note": ("Training crawlers (" + ", ".join(training) + ") are blocked too. That is a valid "
                               "choice and does not affect whether assistants can cite you, so it is listed here "
                               "as context rather than something to change.") if training else
                              "Read from your live robots.txt during the last site audit.",
                  },
                  evidence=[{"token": t, "rule": by_token.get(t, {}).get("matched_rule") or "(no explicit rule)",
                             "named_by": by_token.get(t, {}).get("matched_group")} for t in blocked],
                  source="robots:ai_crawlers")]


def _is_brand_query(query: str, project: Project) -> bool:
    terms = [project.brand_name, *(project.brand_aliases or [])]
    q = query.lower()
    return any(t and t.lower() in q for t in terms)


def _slugify(v: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "-", v.lower()).strip("-")



def _opportunity_rules(db: Session, project: Project, domain) -> list[Draft]:
    """Detections that previously lived in the separate opportunity engine."""
    out: list[Draft] = []
    run = D.latest_crawl_run(db, domain.id)

    # --- target keywords with no page and no impressions
    keywords = D.target_keywords(db, project.id)
    if keywords:
        has_gsc = D.gsc_available(db, domain.id)
        seen = {r["query"].lower() for r in D.gsc_query_page_rows(db, domain.id, 90, 1, 5000)} if has_gsc else set()
        pages = D.html_pages(db, run.id) if run else []
        gaps = []
        for kw in keywords:
            k = kw.text.lower().strip()
            if not k or any(k in q for q in seen):
                continue
            if any(k in ((p.title or "") + " " + (p.h1 or "")).lower() for p in pages):
                continue
            gaps.append({"keyword": kw.text, "importance": kw.importance})
        if gaps and (has_gsc or run):
            out.append(Draft(f"fix:{domain.id}:keyword_gap", "fix", "content",
                             f"No page targets {len(gaps)} of your keywords",
                             "Without a dedicated page you cannot rank or be cited for these topics at all.",
                             ["Create one in-depth page per keyword, or expand the closest existing page",
                              "Put the phrase in the title, H1 and first paragraph",
                              "Link it from the navigation or a page that already gets traffic"],
                             impact=clamp(20 + 12 * len(gaps), 20, 85), effort=4, confidence=0.6 if has_gsc else 0.45,
                             suggestions={"keywords": sorted(gaps, key=lambda g: -g["importance"])[:20]},
                             evidence=[{"table": "keywords", "record_ids": [], "summary":
                                        f"{len(gaps)} target keyword(s) with no page and no impressions in 90 days"}],
                             target_keywords=[g["keyword"] for g in gaps[:20]], source="content:keyword_gap"))

    # --- AI cites other sites instead of yours
    runs = D.latest_runs(db, project.id, 1)
    if runs:
        rows = D.visibility_by_prompt(db, project.id, runs[0])
        weak = [r for r in rows if r["grounded_samples"] and r["brand_mention_rate"] > 0
                and r["own_domain_cited_rate"] < 0.3 and r["top_cited_domains"]]
        if weak:
            domains_cited: dict[str, int] = {}
            for r in weak:
                for d_, n in r["top_cited_domains"]:
                    domains_cited[d_] = domains_cited.get(d_, 0) + n
            out.append(Draft("fix:ai_third_party_citations", "fix", "ai_visibility",
                             f"AI talks about you but cites other sites for {len(weak)} prompt(s)",
                             "Third-party pages are shaping how assistants describe you, because your own pages are not "
                             "the source they trust for these questions.",
                             ["Publish a citable page per prompt: clear facts, a comparison table, an FAQ",
                              "Get accurate listings on the sites already being cited",
                              "Re-run AI visibility in four to six weeks"],
                             impact=clamp(40 + 8 * len(weak), 30, 80), effort=3, confidence=0.6,
                             suggestions={"prompts": [{"prompt": r["prompt"], "provider": r["provider"],
                                                        "own_cited": r["own_domain_cited_rate"],
                                                        "cited_instead": r["top_cited_domains"][:5]} for r in weak[:10]],
                                          "most_cited_domains": sorted(domains_cited.items(), key=lambda kv: -kv[1])[:10]},
                             evidence=[{"table": "ai_answer_observations",
                                        "record_ids": [i for r in weak for i in r["observation_ids"][:5]][:50],
                                        "summary": f"{len(weak)} prompt(s) where your domain is cited in under 30% of grounded answers"}],
                             source="geo:third_party_citations"))

        # --- a competitor gaining share of voice between runs
        two = D.latest_runs(db, project.id, 2)
        if len(two) == 2:
            now, before = D.visibility_summary(db, project.id, two[0]), D.visibility_summary(db, project.id, two[1])
            gaining = [{"competitor": n, "now": rate, "before": before["competitors"].get(n, 0.0),
                        "gain": round(rate - before["competitors"].get(n, 0.0), 3)}
                       for n, rate in now["competitors"].items() if rate - before["competitors"].get(n, 0.0) >= 0.15]
            if gaining:
                top = max(gaining, key=lambda g: g["gain"])
                out.append(Draft("fix:competitor_ai_gain", "fix", "competitors",
                                 f"{top['competitor']} is gaining ground in AI answers",
                                 f"Their mention rate rose from {top['before']:.0%} to {top['now']:.0%} between the last two runs. "
                                 "Share of AI recommendations is being taken while you watch.",
                                 ["Open the prompts where they now appear and read which sources are cited",
                                  "Match or beat that content on your own site",
                                  "Pursue a mention on the sources driving their rise"],
                                 impact=clamp(100 * top["gain"] + 20, 25, 80), effort=3, confidence=0.55,
                                 suggestions={"competitors": sorted(gaining, key=lambda g: -g["gain"]),
                                              "samples": {"now": now["samples"], "previous": before["samples"]}},
                                 evidence=[{"table": "ai_answer_observations", "record_ids": [str(two[0]), str(two[1])],
                                            "summary": "Comparison of the last two AI visibility runs"}],
                                 source="geo:competitor_gain"))

    # --- pages with traffic but almost no conversions
    rows = [r for r in D.analytics_landing_pages(db, domain.id, 28) if r["sessions"] >= 100]
    if len(rows) >= 3:
        rates = sorted(r["conversion_rate"] for r in rows)
        median = rates[len(rates) // 2]
        if median > 0:
            weak = [r for r in rows if r["conversion_rate"] < median * 0.3]
            if weak:
                lost = sum(r["sessions"] * (median - r["conversion_rate"]) for r in weak)
                out.append(Draft(f"fix:{domain.id}:low_conversion", "fix", "conversion",
                                 f"{len(weak)} page(s) get traffic but barely convert",
                                 f"Bringing them to your own median of {median:.1%} would add roughly {lost:.0f} conversions "
                                 "per 28 days from traffic you already pay for.",
                                 ["Check the offer and the call to action above the fold",
                                  "Make sure the page matches what the visitor searched for",
                                  "Remove friction: long forms, slow loading, unclear pricing"],
                                 impact=clamp(20 + lost * 2, 25, 90), effort=3, confidence=0.7,
                                 suggestions={"pages": [{k: v for k, v in r.items() if k != "ids"} for r in
                                                        sorted(weak, key=lambda r: -r["sessions"])[:15]],
                                              "site_median_conversion_rate": round(median, 4)},
                                 evidence=[{"table": "analytics_events",
                                            "record_ids": [i for r in weak for i in r["ids"][:5]][:50],
                                            "summary": f"{len(weak)} landing pages below 30% of the site median conversion rate"}],
                                 target_urls=[r["landing_page"] for r in weak[:20]], source="analytics:low_conversion"))

    # Analytics is connected and has traffic, but records zero conversions -> no key event / goal is set. This blocks
    # the whole Monetization index and any revenue measurement. Provider-agnostic on purpose.
    rows28 = D.analytics_landing_pages(db, domain.id, 28)
    sessions28 = sum(r["sessions"] for r in rows28)
    conv28 = sum(r["conversions"] for r in rows28)
    if sessions28 >= 50 and conv28 == 0:
        out.append(Draft(f"fix:{domain.id}:no_conversion_event", "fix", "conversion",
                         "Define a conversion event so results can be measured in money",
                         "Your analytics has traffic but records zero conversions, so nothing downstream can tell what "
                         "actually produces customers — revenue and the Monetization score run on an assumption until a "
                         "conversion is defined.",
                         ["Decide the one action that means 'a customer': sign-up, purchase, booking, lead form, call",
                          "Mark it as a conversion in your analytics: GA4 -> mark a key event; Umami/Plausible/Matomo -> "
                          "define a goal or custom event; or fire a server-side event on success",
                          "Connect that analytics source under Integrations so GrowOS can read conversions",
                          "Re-check after a few days of data"],
                         impact=85, effort=2, confidence=0.8,
                         suggestions={"sessions_28d": sessions28, "conversions_28d": conv28},
                         evidence=[{"table": "analytics_events", "record_ids": [],
                                    "summary": f"{sessions28} sessions and 0 conversions in 28 days — no conversion event is set"}],
                         source="analytics:no_conversion_event"))
    return out


# =====================================================================================  BUSINESS BASICS
# Page types we look for across the crawled site to judge whether the customer journey is covered end to end.
JOURNEY_PAGES: dict[str, dict[str, Any]] = {
    "offer":    {"label": "What you sell / pricing", "patterns": ("pricing", "plans", "price", "buy", "order", "shop", "product"),
                 "stage": "Attract → decide", "why": "Buyers abandon when they cannot see what it costs or how to start."},
    "contact":  {"label": "Contact / talk to a human", "patterns": ("contact", "demo", "book", "call", "sales", "support"),
                 "stage": "Decide → buy", "why": "A visible way to ask a question converts hesitant buyers."},
    "about":    {"label": "About / who you are", "patterns": ("about", "team", "company", "story", "impressum"),
                 "stage": "Trust", "why": "Google and AI assistants use this to understand the brand entity."},
    "help":     {"label": "Help / docs / FAQ", "patterns": ("help", "faq", "docs", "documentation", "guide", "support", "knowledge"),
                 "stage": "Deliver → support", "why": "Self-serve answers reduce churn and feed AI answers about your product."},
    "terms":    {"label": "Terms of service", "patterns": ("terms", "tos", "conditions", "legal"),
                 "stage": "Trust", "why": "Required for payments, app stores and ad platforms; a trust signal for buyers."},
    "privacy":  {"label": "Privacy policy", "patterns": ("privacy", "gdpr", "data-protection", "cookie"),
                 "stage": "Trust", "why": "Legally required in most markets and checked by security-minded buyers."},
    "refund":   {"label": "Refund / cancellation policy", "patterns": ("refund", "returns", "cancellation", "money-back", "guarantee"),
                 "stage": "After-sales", "why": "A clear policy removes the biggest objection to a first purchase."},
    "proof":    {"label": "Customer proof (testimonials / cases)", "patterns": ("testimonial", "case-stud", "customers", "reviews", "success", "stories"),
                 "stage": "Decide", "why": "Proof from other customers is the strongest conversion lever and gets quoted by AI assistants."},
}

CLOSED_LOOP_CHECKS = [
    {"stage": "1. Attract", "question": "Can a stranger understand what you sell and for whom within 10 seconds of landing?"},
    {"stage": "2. Decide", "question": "Is pricing (or a clear 'how to get a quote') visible without talking to anyone?"},
    {"stage": "3. Buy", "question": "Can someone actually buy or book right now — and does that path work end to end today?"},
    {"stage": "4. Deliver", "question": "After paying, does the customer get what they bought without you doing manual work each time?"},
    {"stage": "5. Onboard", "question": "Is there a first-run guide, welcome email or walkthrough so they reach value quickly?"},
    {"stage": "6. Support", "question": "Is there one place to ask for help, and do you answer within a stated time?"},
    {"stage": "7. After-sales", "question": "Do you follow up, ask for a review, and have a clear refund/renewal policy?"},
    {"stage": "8. Feedback", "question": "Do support questions and lost deals get fed back into the product and the website copy?"},
]



# Places where buyers compare options and where AI assistants look for evidence about a brand.
LISTING_TARGETS = [
    {"domain": "g2.com", "name": "G2", "for": "B2B software", "why": "the most quoted review site for business tools"},
    {"domain": "capterra.com", "name": "Capterra", "for": "B2B software", "why": "feeds Software Advice and GetApp too"},
    {"domain": "producthunt.com", "name": "Product Hunt", "for": "new products", "why": "a launch earns links, reviews and first users"},
    {"domain": "alternativeto.net", "name": "AlternativeTo", "for": "any product", "why": "ranks for “alternatives to …” searches AI reads"},
    {"domain": "crunchbase.com", "name": "Crunchbase", "for": "any company", "why": "the company record AI assistants cite for facts"},
    {"domain": "linkedin.com", "name": "LinkedIn company page", "for": "any company", "why": "confirms the business is real and active"},
    {"domain": "trustpilot.com", "name": "Trustpilot", "for": "consumer-facing", "why": "public reviews visible in Google and AI answers"},
    {"domain": "theresanaiforthat.com", "name": "There's An AI For That", "for": "AI products", "why": "the main directory for AI tools"},
    {"domain": "getapp.com", "name": "GetApp", "for": "B2B software", "why": "another Gartner-owned comparison site"},
    {"domain": "saashub.com", "name": "SaaSHub", "for": "SaaS", "why": "cheap listing that ranks for comparison searches"},
]


def _known_listings(db: Session, project: Project, sig: dict[str, Any]) -> set[str]:
    """Directory domains we can already see the brand on: linked from the site, cited by AI, or seen in mentions."""
    found: set[str] = set()
    for link in sig.get("social_links") or []:
        host = (urlsplit(link).hostname or "").lower().removeprefix("www.")
        found.add(host)
    runs = D.latest_runs(db, project.id, 1)
    if runs:
        for o in db.scalars(select(AIAnswerObservation).where(AIAnswerObservation.run_id == runs[0], AIAnswerObservation.error.is_(None))).all():
            for c in o.citations or []:
                if c.get("domain"):
                    found.add(c["domain"].lower().removeprefix("www."))
    for m in D.recent_mentions(db, project.id, 180, 500):
        if m.source_url:
            found.add((urlsplit(m.source_url).hostname or "").lower().removeprefix("www."))
    return {f for f in found if f}

def business_items(db: Session, project: Project) -> list[Draft]:
    """Trust and customer-journey basics. Detected where possible; a guided self-check where judgement is needed."""
    out: list[Draft] = []
    domains = D.primary_domains(db, project.id)
    if not domains:
        return out
    domain = domains[0]
    run = D.latest_crawl_run(db, domain.id)
    if not run:
        return out
    pages = D.html_pages(db, run.id)
    paths = [(p.path or "/").lower() + " " + (p.title or "").lower() for p in pages]
    coverage = []
    missing = []
    for key, cfg in JOURNEY_PAGES.items():
        hits = [p.url for p, blob in zip(pages, paths, strict=False) if any(pat in blob for pat in cfg["patterns"])]
        entry = {"area": cfg["label"], "stage": cfg["stage"], "found": bool(hits), "examples": hits[:3], "why": cfg["why"]}
        coverage.append(entry)
        if not hits:
            missing.append(entry)

    out.append(Draft("business:closed_loop", "business", "business", "Check your business runs as a closed loop, end to end",
                     "Traffic only turns into revenue if every stage works: attract → decide → buy → deliver → support → after-sales → feedback. "
                     "Gaps here waste every visit the rest of this plan earns you.",
                     ["Walk through the 8 questions below as if you were a new customer — ideally buy from yourself once",
                      "Write down where the loop breaks (no pricing, manual delivery, no follow-up …)",
                      "Fix the weakest stage first; it caps everything upstream of it",
                      "Tick this off once you have been through the full loop yourself"],
                     impact=95, effort=3,
                     suggestions={"checks": CLOSED_LOOP_CHECKS, "coverage": coverage,
                                  "note": f"Detected from {len(pages)} crawled pages — a missing page is a hint, not proof; you may cover the stage elsewhere."},
                     source="business:loop"))

    if missing:
        out.append(Draft("business:journey_gaps", "business", "business", f"Add {len(missing)} missing page(s) buyers look for",
                         "These pages are what hesitant buyers (and AI assistants describing you) look for before trusting a brand.",
                         ["Create the missing pages below — short and honest beats long and vague",
                          "Link them from the footer so they are easy to find and easy to crawl"],
                         impact=min(90, 30 + 12 * len(missing)), effort=3,
                         suggestions={"missing": missing, "present": [c for c in coverage if c["found"]]},
                         source="business:gaps"))

    # Signals from the fetched key pages (home first)
    home = db.scalar(select(PageSnapshot).where(PageSnapshot.crawl_run_id == run.id, PageSnapshot.path == "/"))
    checked = [p for p in pages if (p.signals or {}).get("checked")]
    sig = (home.signals or {}) if home and (home.signals or {}).get("checked") else ({} if not checked else checked[0].signals)
    if sig:
        own = {e for p in checked for e in (p.signals or {}).get("own_domain_emails", [])}
        free = {e for p in checked for e in (p.signals or {}).get("free_emails", [])}
        any_email = {e for p in checked for e in (p.signals or {}).get("emails", [])}
        if free and not own:
            out.append(Draft("business:email_domain", "business", "business", f"Use an email on your own domain, not {sorted(free)[0].split('@')[-1]}",
                             "A free-provider address signals 'side project' to buyers, hurts email deliverability, and blocks verification on "
                             "directories, ad platforms and marketplaces that AI assistants read.",
                             [f"Set up e.g. hello@{domain.hostname.removeprefix('www.')} (Google Workspace, Zoho or your host's mail)",
                              "Publish it on the contact page and in the footer",
                              "Add SPF, DKIM and DMARC DNS records so your email is not marked as spam"],
                             impact=65, effort=2,
                             suggestions={"found": sorted(free), "suggested": [f"{n}@{domain.hostname.removeprefix('www.')}" for n in ("hello", "support", "sales")]},
                             source="business:email"))
        elif not any_email:
            out.append(Draft("business:email_missing", "business", "business", "Publish a contact email address",
                             "People who will not fill in a form still send an email — and reviewers, journalists and partners need a way to reach you.",
                             [f"Create hello@{domain.hostname.removeprefix('www.')} and show it on the contact page and footer",
                              "Add it to your Organization structured data so AI assistants can surface it"],
                             impact=50, effort=1, suggestions={"suggested": f"hello@{domain.hostname.removeprefix('www.')}"}, source="business:email"))
        if not sig.get("has_logo"):
            out.append(Draft("business:logo", "business", "business", "Add a recognisable logo to the site",
                             "The logo is what people remember and what Google, app stores and AI assistants show next to your name. "
                             "No logo in the header reads as unfinished.",
                             ["Put the logo in the header, linked to the home page, with alt text = your brand name",
                              "Add logo to your Organization JSON-LD (square PNG/SVG, transparent background)",
                              "Reuse it as the favicon, the apple-touch-icon and the og:image fallback"],
                             impact=55, effort=2, suggestions={"page": (home.url if home else domain.base_url),
                                                               "detected": {"header_image": sig.get("logo_img"), "schema_logo": sig.get("logo_in_schema"),
                                                                            "header_svg": sig.get("header_svg_logo"), "favicon": sig.get("favicon")}},
                             source="business:logo"))
        elif not sig.get("logo_in_schema"):
            out.append(Draft("business:logo_schema", "business", "business", "Declare your logo in structured data",
                             "Google and AI assistants use Organization.logo to show your brand mark next to your name.",
                             ["Add \"logo\": \"https://…/logo.png\" to the Organization JSON-LD on your home page",
                              "Use a square image of at least 112×112 px"],
                             impact=30, effort=1, suggestions={"page": (home.url if home else domain.base_url), "current_logo": sig.get("logo_img")},
                             source="business:logo"))
        if not sig.get("favicon"):
            out.append(Draft("business:favicon", "business", "business", "Add a favicon",
                             "The small icon in browser tabs and bookmarks; without it your site looks generic next to competitors.",
                             ["Add /favicon.ico plus <link rel=\"icon\"> and <link rel=\"apple-touch-icon\"> in the page head"],
                             impact=20, effort=1, suggestions={"page": (home.url if home else domain.base_url)}, source="business:favicon"))

        # --- Tier 2: be present where buyers compare and where AI looks for evidence
        known = _known_listings(db, project, sig)
        todo = [t for t in LISTING_TARGETS if t["domain"] not in known]
        if todo:
            out.append(Draft("business:listings", "business", "business", f"Claim your profile on {len(todo)} site(s) where buyers compare options",
                             "Directories and review sites are what AI assistants read when someone asks “what are the best tools for …”. "
                             "A missing or unclaimed listing means the answer is written by someone else, or not at all.",
                             ["Create or claim each profile below with the same name, logo, description and website",
                              "Use the exact brand name everywhere so the profiles reinforce each other",
                              "Add the profile URLs to your Organization structured data (sameAs)",
                              "Tick this off when the main ones for your category are live"],
                             impact=75, effort=3,
                             suggestions={"listings": todo, "already_present": sorted(d for d in known if any(d == t["domain"] for t in LISTING_TARGETS)),
                                          "note": "Pick the ones that fit your category — not every directory is relevant."},
                             source="business:listings"))

        if not sig.get("email_capture"):
            out.append(Draft("business:email_capture", "business", "conversion", "Add a way to capture emails from visitors who are not ready to buy",
                             "Most first-time visitors will not buy today. Without an email list you pay to attract them again later; "
                             "with one you can follow up for free.",
                             ["Add a single-field signup (newsletter, free guide, waitlist or trial) on the home page and blog",
                              "Offer something concrete in return — a template, checklist or sample report",
                              "Send a short welcome email immediately, then something useful monthly"],
                             impact=60, effort=2, suggestions={"page": (home.url if home else domain.base_url)}, source="business:capture"))

        if not sig.get("has_local_schema") and not sig.get("address"):
            out.append(Draft("business:google_business_profile", "business", "business", "Create or claim your Google Business Profile",
                             "A Business Profile puts you on Google Maps and in the knowledge panel next to search results. It is free, "
                             "it is a strong trust signal, and the reviews it collects are read by AI assistants.",
                             ["Create the profile at business.google.com and verify it",
                              "Use the same name, website and phone as on your site",
                              "Add your address (or service area if you have no public office) and your logo",
                              "Publish the address or service area on your site and in LocalBusiness structured data",
                              "Skip and mark 'Not relevant' if you are purely online with no service area"],
                             impact=55, effort=2, suggestions={"page": (home.url if home else domain.base_url),
                                                                "detected": {"address_in_schema": sig.get("address"), "local_business_schema": sig.get("has_local_schema")}},
                             source="business:gbp"))
    return out


def routine_items(db: Session, project: Project) -> list[Draft]:
    out = []
    pool = _topic_pool(db, project)
    comps = D.competitors(db, project.id)
    comp_names = [c.name for c in comps]
    # Weekly article
    out.append(Draft("routine:article", "routine", "content", "Publish one article that answers a real customer question",
                     "Consistent, specific content is how a site earns rankings and gets cited by AI assistants. One good article per week compounds.",
                     ["Pick a topic below (highest first)", "Write 800-1500 words following the outline; answer the question in the first paragraph",
                      "Add an internal link from an existing page and a CTA", "Share it on your social profiles and in one community"],
                     impact=80, effort=3, cadence="weekly",
                     suggestions={"topics": [{k: v for k, v in t.items() if k != "video_script"} for t in pool[:10]],
                                  "note": "Topics come from your Search Console queries ranking on page 2-3, AI prompts where you are absent, and target keywords." if pool else
                                          "Connect Search Console and add target keywords/prompts to get data-driven topics."}, source="routine"))
    # Weekly video
    out.append(Draft("routine:video", "routine", "video", "Record one short video (60-90 s)",
                     "Video reaches people who never search, and YouTube is itself the second largest search engine. Reuse the article topic.",
                     ["Pick a topic below", "Follow the 5-beat script", "Post on YouTube Shorts / TikTok / LinkedIn with the article link", "Embed the video in the article"],
                     impact=60, effort=3, cadence="weekly",
                     suggestions={"topics": [{"topic": t["topic"], "source": t["source"], "reason": t["reason"], "script": t["video_script"]} for t in pool[:6]]}, source="routine"))
    # Weekly community
    since = datetime.now(UTC) - timedelta(days=14)
    mentions = db.scalars(select(BrandMention).where(BrandMention.project_id == project.id, BrandMention.collected_at >= since,
                                                     BrandMention.intent != "none").order_by(desc(BrandMention.published_at)).limit(15)).all()
    queries = [project.brand_name, *comp_names[:3]] + [t["topic"] for t in pool[:3]]
    out.append(Draft("routine:community", "routine", "community", "Join 3 conversations where people ask for what you offer",
                     "Helpful answers in communities bring buyers directly and create the mentions AI assistants learn from.",
                     ["Open the threads below (or search the suggested phrases on Reddit, Hacker News, Quora, LinkedIn)", "Answer the question genuinely first; mention your product only where it fits",
                      "Log the thread link here when done"], impact=55, effort=2, cadence="weekly",
                     suggestions={"threads": [{"title": m.title or (m.content_excerpt or "")[:80], "url": m.source_url, "source": m.source_name, "intent": m.intent, "entity": m.entity_name} for m in mentions],
                                  "search_phrases": [f"{q} recommendations" for q in queries[:4]] + [f"alternatives to {c}" for c in comp_names[:3]]}, source="routine"))
    # Weekly backlinks / mentions
    targets: dict[str, dict[str, Any]] = {}
    own = {d.hostname.removeprefix("www.") for d in D.primary_domains(db, project.id)}
    runs = D.latest_runs(db, project.id, 1)
    if runs:
        obs = db.scalars(select(AIAnswerObservation).where(AIAnswerObservation.run_id == runs[0], AIAnswerObservation.error.is_(None))).all()
        for o in obs:
            for c in o.citations or []:
                dom = c.get("domain")
                if dom and dom not in own:
                    t = targets.setdefault(dom, {"domain": dom, "cited": 0, "example": c.get("url"), "why": "cited by AI assistants for your prompts"})
                    t["cited"] += 1
    generic = [{"domain": "Product Hunt / G2 / Capterra / AlternativeTo (or the directories of your industry)", "why": "listings are read by AI assistants and buyers comparing options"},
               {"domain": "Partners, customers, integrations", "why": "ask for a logo/link on their site; case studies earn natural links"},
               {"domain": "Industry newsletters & podcasts", "why": "a guest appearance yields a link and a mention"}]
    out.append(Draft("routine:backlinks", "routine", "backlinks", "Earn 2 new mentions or backlinks on sites that matter",
                     "The sites AI assistants cite for your topics decide whether you get recommended; links from them also lift rankings.",
                     ["Pick a target below", "Offer something useful: data, a guest article, a listing, a quote", "Use the outreach template; log the result here"],
                     impact=70, effort=3, cadence="weekly",
                     suggestions={"ai_cited_domains": sorted(targets.values(), key=lambda t: -t["cited"])[:15], "generic_targets": generic,
                                  "outreach_template": f"Hi <name>, I read your <article> on <topic>. We built {project.brand_name} for <audience>; here is <data/insight> your readers may find useful: <link>. Happy to contribute a short section or an example if helpful."},
                     source="routine"))
    # Monthly competitor review
    changes = D.recent_competitor_changes(db, project.id, 30)
    comp_lookup = {c.id: c.name for c in comps}
    vis = D.visibility_summary(db, project.id, runs[0]) if runs else None
    out.append(Draft("routine:competitors", "routine", "competitors", "Review competitor moves and your share of voice",
                     "Pricing/feature changes and AI share-of-voice shifts tell you where to sharpen your positioning.",
                     ["Read the detected page changes below", "Compare AI mention rates (yours vs theirs) and note who is gaining", "Decide one positioning or pricing response"],
                     impact=45, effort=2, cadence="monthly",
                     suggestions={"changes": [{"competitor": comp_lookup.get(c.competitor_id), "url": c.url, "when": c.observed_at.isoformat(), "prices_added": c.diff_summary.get("prices_added")} for c in changes[:15]],
                                  "share_of_voice": ({"you": vis["brand_mention_rate"], **vis["competitors"]} if vis else None),
                                  "watched_pages_hint": "Add competitor pricing/feature URLs under Competitors to detect changes." if not changes else None}, source="routine"))
    # Monthly refresh declining pages
    declining = []
    for d in D.primary_domains(db, project.id):
        if not D.gsc_available(db, d.id):
            continue
        s, e = D.gsc_window(28)
        ps = D.gsc_window(56)[0]
        cur = {r["page"]: r for r in D.gsc_top_pages(db, d.id, 28, 100)}
        prev_rows = db.execute(select(SearchObservation.page, func.sum(SearchObservation.clicks)).where(SearchObservation.domain_id == d.id, SearchObservation.date >= ps, SearchObservation.date < s,
                                                                                                        SearchObservation.query == "", SearchObservation.page != "", SearchObservation.country == "", SearchObservation.device == "").group_by(SearchObservation.page)).all()
        for page, prev_clicks in prev_rows:
            prev_clicks = int(prev_clicks or 0)
            now_clicks = cur.get(page, {}).get("clicks", 0)
            if prev_clicks >= 10 and now_clicks < prev_clicks * 0.7:
                declining.append({"page": page, "clicks_before": prev_clicks, "clicks_now": now_clicks, "drop_pct": round(100 * (1 - now_clicks / prev_clicks))})
    out.append(Draft("routine:refresh", "routine", "content", "Refresh pages that are losing search clicks",
                     "Content decays; updating a page that lost traffic usually recovers it faster than writing a new one.",
                     ["Update facts, dates and screenshots; expand thin sections", "Re-check the title against the queries it ranks for", "Republish with the current date"],
                     impact=50, effort=2, cadence="monthly", suggestions={"pages": sorted(declining, key=lambda r: -r["clicks_before"])[:15]}, source="routine"))
    # Weekly AI visibility check
    out.append(Draft("routine:ai_check", "routine", "ai_visibility", "Re-run AI visibility prompts and read the changes",
                     "AI answers change with every model update; weekly sampling shows whether your content and mentions are working.",
                     ["GEO AI Visibility → Run all active prompts (or add a weekly schedule under Settings)", "Note prompts where you gained/lost and which sources were cited"],
                     impact=40, effort=1, cadence="weekly", suggestions={"last_run": vis}, source="routine"))
    # Monthly: collect public reviews
    out.append(Draft("routine:reviews", "routine", "brand", "Ask 2 happy customers for a public review",
                     "Reviews on Google, G2 or Trustpilot are the single strongest input to how AI assistants and buyers judge you — "
                     "and they keep working for years.",
                     ["Pick 2 customers who recently got a good result",
                      "Send a short personal message with a direct link to the review page (one click, no login hunting)",
                      "Reply to every review you receive, positive or not",
                      "Log who you asked so you do not ask the same people twice"],
                     impact=70, effort=1, cadence="monthly",
                     suggestions={"where": [t for t in LISTING_TARGETS if t["domain"] in ("g2.com", "trustpilot.com", "capterra.com", "producthunt.com")]
                                            + [{"domain": "google.com/maps", "name": "Google Business Profile", "for": "any business", "why": "shows next to your name in Google"}],
                                  "template": f"Hi <name>, glad {project.brand_name} is working for you. Would you mind leaving a short review here: <link>? "
                                              "Two sentences about what changed for you is plenty — it genuinely helps other people decide."},
                     source="routine"))

    # Daily: respond to new mentions
    day_ago = datetime.now(UTC) - timedelta(days=1)
    new_mentions = db.scalar(select(func.count()).select_from(BrandMention).where(BrandMention.project_id == project.id, BrandMention.collected_at >= day_ago)) or 0
    out.append(Draft("routine:respond", "routine", "community", "Respond to new mentions of your brand",
                     "A fast, friendly reply turns a question into a customer and a complaint into a save.",
                     ["Brand Monitoring → filter brand mentions by newest", "Reply where a human answer adds value"],
                     impact=35, effort=1, cadence="daily", suggestions={"new_in_last_24h": new_mentions}, source="routine"))
    return out


# =====================================================================================  sync
def build_drafts(db: Session, project: Project) -> list[Draft]:
    return setup_items(db, project) + business_items(db, project) + fix_items(db, project) + routine_items(db, project)


def complete_actions_for_item(db: Session, item: PlanItem, now: datetime | None = None) -> int:
    """Close any open action tracking a plan item once that item is resolved/done.

    Actions are the user's work record for an item. When the item is verified fixed (or marked done) the action is
    done too, so without this it lingers as 'in progress' forever and its outcome never gets an anchor to measure
    against. Returns how many actions were completed.
    """
    now = now or datetime.now(UTC)
    acts = db.scalars(select(ActionRecord).where(ActionRecord.plan_item_id == item.id,
                                                 ActionRecord.status.in_(("planned", "in_progress")))).all()
    for a in acts:
        a.status = "done"
        a.completed_at = a.completed_at or now
    return len(acts)


def sync_plan(db: Session, project: Project) -> dict[str, Any]:
    drafts = build_drafts(db, project)
    now = datetime.now(UTC)
    existing = {p.key: p for p in db.scalars(select(PlanItem).where(PlanItem.project_id == project.id)).all()}
    created = updated = resolved = 0
    seen_keys = set()
    for d in drafts:
        seen_keys.add(d.key)
        prio, breakdown = priority_score(d.impact, d.confidence, d.effort)
        breakdown["source"] = d.source
        item = existing.get(d.key)
        if item is None:
            item = PlanItem(project_id=project.id, key=d.key, section=d.section, cadence=d.cadence, category=d.category,
                            title=d.title, why=d.why, steps=d.steps, suggestions=d.suggestions, evidence=d.evidence,
                            impact=d.impact, confidence=d.confidence, effort=d.effort, priority=prio,
                            score_breakdown=breakdown, origin=d.origin, target_urls=d.target_urls[:50],
                            target_keywords=d.target_keywords[:50], source=d.source,
                            next_due_at=now if d.cadence != "once" else None, last_seen_at=now,
                            history=[{"at": now.isoformat(), "event": "created", "actor": d.origin}])
            db.add(item)
            created += 1
        else:
            if abs((item.priority or 0) - prio) >= 0.05:
                item.history = [*(item.history or []), {"at": now.isoformat(), "event": "rescored",
                                                        "from": item.priority, "to": prio}][-50:]
            item.title, item.why, item.steps, item.suggestions, item.evidence = d.title, d.why, d.steps, d.suggestions, d.evidence
            item.impact, item.confidence, item.effort = d.impact, d.confidence, d.effort
            item.priority, item.score_breakdown, item.category, item.last_seen_at = prio, breakdown, d.category, now
            item.target_urls, item.target_keywords = d.target_urls[:50], d.target_keywords[:50]
            if item.section in ("fix", "setup", "business") and item.status == "done" and item.resolved_at is not None:
                item.status, item.resolved_at = "todo", None  # it came back
            updated += 1
    # fix/setup items no longer produced by the data → verified resolved
    for key, item in existing.items():
        if (key not in seen_keys and item.section in ("fix", "setup", "business") and item.origin != "ai"
                and item.status in ("todo", "in_progress", "done") and item.resolved_at is None):
            item.status, item.resolved_at = "done", now
            item.history = [*(item.history or []), {"at": now.isoformat(), "event": "auto_resolved"}][-50:]
            complete_actions_for_item(db, item, now)
            resolved += 1
    db.commit()
    return {"created": created, "updated": updated, "auto_resolved": resolved, "total": len(drafts)}


def sync_one(db: Session, project_id: uuid.UUID, draft: Draft) -> PlanItem:
    """Upsert a single draft — used by the AI analyst so its findings land in the same checklist."""
    now = datetime.now(UTC)
    prio, breakdown = priority_score(draft.impact, draft.confidence, draft.effort)
    breakdown["source"] = draft.source
    item = db.scalar(select(PlanItem).where(PlanItem.project_id == project_id, PlanItem.key == draft.key[:300]))
    if item is None:
        item = PlanItem(project_id=project_id, key=draft.key[:300], section=draft.section, cadence=draft.cadence,
                        category=draft.category, title=draft.title, why=draft.why, steps=draft.steps,
                        suggestions=draft.suggestions, evidence=draft.evidence, impact=draft.impact,
                        confidence=draft.confidence, effort=draft.effort, priority=prio, score_breakdown=breakdown,
                        origin=draft.origin, target_urls=draft.target_urls[:50],
                        target_keywords=draft.target_keywords[:50], source=draft.source, last_seen_at=now,
                        history=[{"at": now.isoformat(), "event": "created", "actor": draft.origin}])
        db.add(item)
    else:
        item.title, item.why, item.steps = draft.title, draft.why, draft.steps
        item.suggestions, item.evidence = draft.suggestions, draft.evidence
        item.impact, item.confidence, item.effort = draft.impact, draft.confidence, draft.effort
        item.priority, item.score_breakdown, item.last_seen_at = prio, breakdown, now
    db.commit()
    db.refresh(item)
    return item


def mark_complete(item: PlanItem, note: str | None = None) -> None:
    now = datetime.now(UTC)
    item.completions = [*(item.completions or []), {"at": now.isoformat(), "note": note}][-100:]
    item.last_done_at = now
    if item.cadence in CADENCE_DAYS:
        item.next_due_at = now + timedelta(days=CADENCE_DAYS[item.cadence])
        item.status = "todo"
    else:
        item.status = "done"


def undo_complete(item: PlanItem) -> bool:
    """Reverse the most recent completion, restoring the previous due date. False when there is nothing to undo."""
    completions = list(item.completions or [])
    if not completions:
        if item.status != "done":
            return False
        item.status = "todo"       # marked done directly, without a logged completion
        item.last_done_at = None
        return True
    completions.pop()
    item.completions = completions
    previous = completions[-1].get("at") if completions else None
    item.last_done_at = datetime.fromisoformat(previous) if previous else None
    if item.cadence in CADENCE_DAYS:
        # Due again as it would have been after the earlier completion; no completions left means due now.
        item.next_due_at = item.last_done_at + timedelta(days=CADENCE_DAYS[item.cadence]) if item.last_done_at else None
    item.status = "todo"
    return True


def plan_summary(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    items = db.scalars(select(PlanItem).where(PlanItem.project_id == project_id)).all()
    now = datetime.now(UTC)
    open_fix = [i for i in items if i.section in ("fix", "setup", "business") and i.status in ("todo", "in_progress")]
    due = [i for i in items if i.section == "routine" and i.status != "skipped" and (i.next_due_at is None or i.next_due_at <= now)]
    last_job = db.scalar(select(CollectionJob).where(CollectionJob.project_id == project_id, CollectionJob.task_type == "build_growth_plan",
                                                     CollectionJob.status == "succeeded").order_by(desc(CollectionJob.finished_at)).limit(1))
    return {"open_fixes": len(open_fix), "setup_open": sum(1 for i in open_fix if i.section == "setup"),
            "business_open": sum(1 for i in open_fix if i.section == "business"),
            "fix_open": sum(1 for i in open_fix if i.section == "fix"),
            "routines_total": sum(1 for i in items if i.section == "routine" and i.status != "skipped"), "routines_due": len(due),
            "done_total": sum(1 for i in items if i.status == "done") + sum(len(i.completions or []) for i in items),
            "last_generated_at": last_job.finished_at if last_job else None, "total": len(items)}
