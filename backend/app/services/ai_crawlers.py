"""Which AI crawlers your robots.txt actually lets in.

The question this answers is the first one to ask about AI visibility, and the cheapest: an assistant can only
cite a page it was allowed to fetch. A site that blocks `OAI-SearchBot` cannot appear in ChatGPT's citations no
matter how good its content is, and nothing in the product would otherwise explain why — the prompt runs, the
brand is absent, and the cause is one line in a text file.

Two things are deliberately kept apart, because conflating them turns a real finding into nagging:

* **Answer crawlers** fetch pages so an assistant can retrieve, quote and cite them. Blocking one costs
  visibility, and almost nobody does it on purpose — it is usually a copy-pasted "block the AI bots" snippet.
* **Training crawlers** collect corpora to train models. Blocking those is a legitimate, deliberate policy
  choice that costs no visibility, so we report it as a fact and never as a problem.

Everything here is observed evidence: a verdict is only reported when robots.txt was actually fetched, and each
one carries the exact rule line it came from so the user can check our reading against their file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.safe_http import UnsafeURLError, safe_get

# Purpose of a crawler, and the reason the distinction exists. "answers" is the only one whose absence costs
# visibility; "training" is a policy choice; "search" crawlers feed a classic index that in turn feeds an
# assistant (Googlebot → AI Overviews, Bingbot → Copilot), so blocking one costs both kinds of traffic at once.
ANSWERS, TRAINING, SEARCH = "answers", "training", "search"


@dataclass(frozen=True)
class Crawler:
    token: str          # the product token as it must appear in a User-agent line
    operator: str
    purpose: str
    what: str           # what blocking it actually costs, in the user's terms


# A point-in-time snapshot (last reviewed 2026-11). Operators add and rename tokens, so an unknown bot is not an
# error here — the file is the source of truth and we only report on tokens we can name. `what` is written to be
# shown to a non-technical user verbatim.
AI_CRAWLERS: tuple[Crawler, ...] = (
    Crawler("OAI-SearchBot", "OpenAI", ANSWERS, "Indexes pages so ChatGPT search can cite them. Blocking it removes you from ChatGPT's sources."),
    Crawler("ChatGPT-User", "OpenAI", ANSWERS, "Fetches a page when a ChatGPT user's question needs it live. Blocking it stops ChatGPT opening your pages on request."),
    Crawler("GPTBot", "OpenAI", TRAINING, "Collects pages to train OpenAI models. Blocking it is a policy choice and does not affect ChatGPT citations."),
    Crawler("Claude-SearchBot", "Anthropic", ANSWERS, "Indexes pages so Claude can cite them in answers."),
    Crawler("Claude-User", "Anthropic", ANSWERS, "Fetches a page when a Claude user's question needs it live."),
    Crawler("ClaudeBot", "Anthropic", TRAINING, "Collects pages to train Anthropic models. Blocking it is a policy choice."),
    Crawler("anthropic-ai", "Anthropic", TRAINING, "Older Anthropic token, still seen in robots.txt files."),
    Crawler("PerplexityBot", "Perplexity", ANSWERS, "Indexes pages so Perplexity can cite them. Blocking it removes you from Perplexity's sources."),
    Crawler("Perplexity-User", "Perplexity", ANSWERS, "Fetches a page when a Perplexity user's question needs it live."),
    Crawler("Googlebot", "Google", SEARCH, "Google's main crawler. It feeds both normal search results and AI Overviews, so blocking it removes you from both."),
    Crawler("Google-Extended", "Google", TRAINING, "Controls use of your pages for Gemini training and grounding. It does not affect normal Google indexing."),
    Crawler("Bingbot", "Microsoft", SEARCH, "Bing's crawler. Bing's index is what Microsoft Copilot answers from."),
    Crawler("DuckAssistBot", "DuckDuckGo", ANSWERS, "Fetches pages for DuckDuckGo's assistant answers."),
    Crawler("MistralAI-User", "Mistral", ANSWERS, "Fetches a page when a Mistral assistant user's question needs it live."),
    Crawler("Applebot", "Apple", SEARCH, "Feeds Siri and Spotlight suggestions."),
    Crawler("Applebot-Extended", "Apple", TRAINING, "Controls use of your pages for Apple Intelligence training."),
    Crawler("Amazonbot", "Amazon", SEARCH, "Feeds Alexa answers."),
    Crawler("meta-externalagent", "Meta", TRAINING, "Collects pages for Meta AI."),
    Crawler("Bytespider", "ByteDance", TRAINING, "Collects pages for ByteDance models."),
    Crawler("CCBot", "Common Crawl", TRAINING, "Common Crawl's crawler. Its archive is a training corpus for many different models."),
    Crawler("cohere-ai", "Cohere", TRAINING, "Collects pages for Cohere models."),
    Crawler("YouBot", "You.com", ANSWERS, "Indexes pages so You.com can cite them."),
)

CRAWLERS_BY_TOKEN = {c.token.lower(): c for c in AI_CRAWLERS}

# Response headers and meta values some publishers use to opt out of AI use. They are not a standard and no
# assistant is known to honour them, so finding one is worth reporting as a fact and never as a fix.
AI_OPTOUT_DIRECTIVES = ("noai", "noimageai", "noml")


@dataclass
class Rule:
    """One Allow/Disallow line, kept with its source text so a verdict can show its evidence."""
    allow: bool
    path: str
    line: str

    @property
    def specificity(self) -> int:
        """Length of the path pattern, which is how competing rules are ranked (RFC 9309 §2.2.2)."""
        return len(self.path)


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


@dataclass
class Verdict:
    token: str
    operator: str
    purpose: str
    what: str
    allowed: bool
    matched_group: str           # the User-agent value whose group decided it ("*" when only the catch-all applies)
    matched_rule: str | None     # the exact line, or None when nothing matched and the default (allow) applied
    explicit: bool               # True when a group names this crawler, rather than it falling through to "*"

    def as_dict(self) -> dict[str, Any]:
        return {"token": self.token, "operator": self.operator, "purpose": self.purpose, "what": self.what,
                "allowed": self.allowed, "matched_group": self.matched_group,
                "matched_rule": self.matched_rule, "explicit": self.explicit}


class RobotsFile:
    """A parsed robots.txt, evaluated the way RFC 9309 says crawlers evaluate it."""

    def __init__(self, text: str):
        self.text = text
        self.groups: list[Group] = []
        self.sitemaps: list[str] = []
        self._parse(text)

    def _parse(self, text: str) -> None:
        current: Group | None = None
        expecting_agents = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field_name, _, value = line.partition(":")
            key = field_name.strip().lower()
            value = value.strip()
            if key == "user-agent":
                # Consecutive User-agent lines share one set of rules; a User-agent line after a rule line starts
                # a new group.
                if current is None or not expecting_agents:
                    current = Group()
                    self.groups.append(current)
                    expecting_agents = True
                current.agents.append(value)
            elif key in ("allow", "disallow"):
                if current is None:  # rules before any User-agent line belong to nobody; crawlers ignore them
                    continue
                expecting_agents = False
                current.rules.append(Rule(allow=(key == "allow"), path=value, line=raw.strip()))
            elif key == "crawl-delay" and current is not None:
                expecting_agents = False
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass
            elif key == "sitemap":
                self.sitemaps.append(value)

    def _group_for(self, token: str) -> tuple[Group | None, str]:
        """The one group that applies to this crawler, and the User-agent value it was named by.

        Crawlers obey exactly one group: the most specific one that names them, falling back to `*`. Specificity
        is decided the way RFC 9309 §2.2.1 decides it — the value in the file must be a case-insensitive *prefix*
        of the crawler's product token, and the longest such value wins. The direction matters: it is what makes
        `User-agent: Claude` govern every Anthropic bot while `User-agent: Googlebot-Image` correctly governs
        none of the crawlers listed here.
        """
        low = token.lower()
        candidates = [(g, a) for g in self.groups for a in g.agents
                      if a.strip() and a.strip() != "*" and low.startswith(a.strip().lower())]
        if candidates:
            return max(candidates, key=lambda ga: len(ga[1].strip()))
        star = [(g, a) for g in self.groups for a in g.agents if a.strip() == "*"]
        return star[0] if star else (None, "*")

    def verdict(self, token: str, path: str = "/") -> tuple[bool, str, str | None, bool]:
        """(allowed, matched group name, matched rule line, whether a group names this crawler)."""
        group, agent = self._group_for(token)
        if group is None:
            return True, "*", None, False
        explicit = agent.strip() != "*"
        best: Rule | None = None
        for rule in group.rules:
            if rule.path == "" and not rule.allow:
                continue  # "Disallow:" with an empty value means "nothing is disallowed"
            if not _path_matches(rule.path, path):
                continue
            # Longest pattern wins; Allow wins a tie, which is what makes the Allow/Disallow pair work.
            if best is None or (rule.specificity, rule.allow) > (best.specificity, best.allow):
                best = rule
        if best is None:
            return True, agent, None, explicit
        return best.allow, agent, best.line, explicit


def _path_matches(pattern: str, path: str) -> bool:
    """RFC 9309 path matching: prefix match, with `*` as any run of characters and `$` anchoring the end."""
    if pattern in ("", "/"):
        return pattern == "" or path.startswith("/")
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.match(f"^{regex}{'$' if anchored else ''}", path) is not None


def analyze(robots_text: str, paths: list[str] | None = None) -> dict[str, Any]:
    """Per-crawler verdicts for a robots.txt we were able to read."""
    robots = RobotsFile(robots_text)
    paths = [p for p in (paths or []) if p and p != "/"]
    verdicts: list[Verdict] = []
    blocked_paths: dict[str, list[str]] = {}
    for crawler in AI_CRAWLERS:
        allowed, agent, rule, explicit = robots.verdict(crawler.token, "/")
        verdicts.append(Verdict(crawler.token, crawler.operator, crawler.purpose, crawler.what,
                                allowed, agent, rule, explicit))
        if allowed and paths:
            denied = [p for p in paths if not robots.verdict(crawler.token, p)[0]]
            if denied:
                blocked_paths[crawler.token] = denied[:20]
    return _summarize(verdicts, blocked_paths, robots)


def _summarize(verdicts: list[Verdict], blocked_paths: dict[str, list[str]], robots: RobotsFile) -> dict[str, Any]:
    blocked = [v for v in verdicts if not v.allowed]
    return {
        "checked": True,
        "crawlers": [v.as_dict() for v in verdicts],
        # The headline numbers the plan and the UI care about, split by what blocking actually costs.
        "blocked_answers": [v.token for v in blocked if v.purpose == ANSWERS],
        "blocked_search": [v.token for v in blocked if v.purpose == SEARCH],
        "blocked_training": [v.token for v in blocked if v.purpose == TRAINING],
        "allowed_count": len(verdicts) - len(blocked),
        "partially_blocked": blocked_paths,
        "sitemaps": robots.sitemaps[:20],
        "crawl_delay": next((g.crawl_delay for g in robots.groups if g.crawl_delay), None),
        "group_count": len(robots.groups),
    }


def _unreadable(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    """A result for the cases where no per-crawler verdict can honestly be given."""
    return {"checked": False, "status": status, "detail": detail, "crawlers": [],
            "blocked_answers": [], "blocked_search": [], "blocked_training": [],
            "partially_blocked": {}, "sitemaps": [], **extra}


def fetch_and_analyze(base_url: str, paths: list[str] | None = None) -> dict[str, Any]:
    """Fetch /robots.txt for a site and report which AI crawlers it admits.

    The failure modes carry real meaning and are reported rather than swallowed:

    * **404 / no file** — everything is allowed. Normal, and worth saying out loud.
    * **5xx** — RFC 9309 tells crawlers to treat an unreachable robots.txt as *disallow everything*, so a broken
      robots.txt endpoint can take a whole site out of search and out of AI answers while every page still loads
      perfectly in a browser. This is the finding most worth having.
    * **HTML body** — a SPA catch-all route answering `/robots.txt` with the app shell. No directive in it is
      parsed by anyone, so the file is effectively absent and whatever it was meant to say is not in force.
    """
    parts = urlsplit(base_url)
    robots_url = urlunsplit((parts.scheme or "https", parts.netloc, "/robots.txt", "", ""))
    try:
        resp = safe_get(robots_url, max_bytes=512_000)
    except UnsafeURLError as exc:
        return _unreadable("unsafe_url", str(exc)[:300], url=robots_url)
    except Exception as exc:  # noqa: BLE001 — a site we cannot reach must not fail the crawl
        return _unreadable("fetch_failed", str(exc)[:300], url=robots_url)

    out: dict[str, Any] = {"url": robots_url, "status_code": resp.status_code}
    ctype = resp.headers.get("content-type", "").lower()
    if resp.status_code in (401, 403) or resp.status_code >= 500:
        return {**_unreadable("server_error" if resp.status_code >= 500 else "access_denied",
                              f"robots.txt returned HTTP {resp.status_code}. Crawlers treat an unreachable "
                              f"robots.txt as 'disallow everything', so this can remove the whole site from "
                              f"search results and AI answers."), **out}
    if resp.status_code == 404:
        return {**_unreadable("missing", "No robots.txt. Nothing is blocked, so every crawler may fetch the site."), **out,
                "crawlers": [Verdict(c.token, c.operator, c.purpose, c.what, True, "*", None, False).as_dict()
                             for c in AI_CRAWLERS],
                "allowed_count": len(AI_CRAWLERS), "checked": True}
    if resp.status_code != 200:
        return {**_unreadable("unexpected_status", f"robots.txt returned HTTP {resp.status_code}."), **out}

    text = resp.text
    if "html" in ctype or text.lstrip()[:200].lower().startswith(("<!doctype", "<html")):
        return {**_unreadable("not_plain_text",
                              "robots.txt returns an HTML page rather than a text file, so no crawler can read "
                              "its rules — whatever it is meant to say is not in force."), **out,
                "content_type": ctype}

    result = analyze(text, paths)
    result.update(out)
    result["optout_headers"] = _optout_from_header(resp.headers.get("x-robots-tag", ""))
    return result


def _optout_from_header(x_robots_tag: str) -> list[str]:
    low = (x_robots_tag or "").lower()
    return [d for d in AI_OPTOUT_DIRECTIVES if d in low]
