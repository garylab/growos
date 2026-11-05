from app.services.ai_crawlers import RobotsFile, analyze

# A real-world shape: the catch-all is permissive, and a copy-pasted "block the AI bots" block catches the
# retrieval crawlers along with the training ones.
MIXED = """
User-agent: *
Disallow: /admin/
Allow: /admin/public
Sitemap: https://example.com/sitemap.xml

User-agent: GPTBot
User-agent: OAI-SearchBot
Disallow: /

User-agent: CCBot
Disallow: /

User-agent: PerplexityBot
Disallow: /docs/
"""


def test_group_selection_and_longest_match():
    r = RobotsFile(MIXED)
    # A named group wins over "*", and consecutive User-agent lines share one rule set.
    assert r.verdict("GPTBot")[0] is False
    assert r.verdict("OAI-SearchBot")[0] is False
    # Allow beats an equally-matching Disallow; the longer pattern beats the shorter one.
    assert r.verdict("Claude-User", "/admin/public")[0] is True
    assert r.verdict("Claude-User", "/admin/secret")[0] is False
    assert r.verdict("Claude-User", "/pricing")[0] is True
    assert r.sitemaps == ["https://example.com/sitemap.xml"]


def test_verdict_reports_the_rule_it_matched():
    allowed, group, rule, explicit = RobotsFile(MIXED).verdict("GPTBot")
    assert (allowed, group, explicit) == (False, "GPTBot", True)
    assert rule == "Disallow: /"
    # Falling through to the catch-all is reported as not explicit, so the UI can say "no rule names this bot".
    assert RobotsFile(MIXED).verdict("Claude-User")[3] is False


def test_training_blocks_are_separated_from_visibility_blocks():
    out = analyze(MIXED, ["/docs/start", "/pricing"])
    assert out["blocked_answers"] == ["OAI-SearchBot"]
    assert sorted(out["blocked_training"]) == ["CCBot", "GPTBot"]
    assert out["blocked_search"] == []
    # PerplexityBot may fetch "/" but not the docs, so it is a partial block rather than a blocked crawler.
    assert "PerplexityBot" not in out["blocked_answers"]
    assert out["partially_blocked"]["PerplexityBot"] == ["/docs/start"]


def test_prefix_matching_direction():
    """A robots.txt token governs every crawler it is a prefix of — and nothing it merely resembles."""
    r = RobotsFile("User-agent: Claude\nDisallow: /\n")
    assert r.verdict("ClaudeBot")[0] is False
    assert r.verdict("Claude-User")[0] is False
    assert r.verdict("GPTBot")[0] is True
    # The reverse direction must not apply: an image-bot group does not govern Googlebot itself.
    r2 = RobotsFile("User-agent: Googlebot-Image\nDisallow: /\n")
    assert r2.verdict("Googlebot")[0] is True


def test_wildcards_and_end_anchor():
    r = RobotsFile("User-agent: *\nDisallow: /*.pdf$\nDisallow: /p/*/draft\n")
    assert r.verdict("GPTBot", "/files/report.pdf")[0] is False
    assert r.verdict("GPTBot", "/files/report.pdf?v=2")[0] is True   # $ anchors the end
    assert r.verdict("GPTBot", "/p/123/draft")[0] is False
    assert r.verdict("GPTBot", "/p/123/live")[0] is True


def test_empty_disallow_allows_everything():
    r = RobotsFile("User-agent: *\nDisallow:\n")
    assert r.verdict("GPTBot", "/anything")[0] is True
    assert analyze("User-agent: *\nDisallow:\n")["blocked_answers"] == []


def test_rules_before_any_user_agent_line_are_ignored():
    # Nobody obeys orphan rules, so reading them would invent a block that no crawler applies.
    r = RobotsFile("Disallow: /\n\nUser-agent: *\nAllow: /\n")
    assert r.verdict("GPTBot", "/")[0] is True


def test_site_wide_block_counts_every_purpose():
    out = analyze("User-agent: *\nDisallow: /\n")
    assert "OAI-SearchBot" in out["blocked_answers"]
    assert "Googlebot" in out["blocked_search"]
    assert "GPTBot" in out["blocked_training"]
    assert out["allowed_count"] == 0
