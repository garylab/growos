from app.services.onboarding import DEFAULT_SCHEDULES


def test_default_schedules_cover_the_loop():
    tasks = {t for t, _, _ in DEFAULT_SCHEDULES}
    # The full Monitor -> Act -> Measure loop must run on its own.
    assert {"sync_search_console", "crawl_domain", "run_ai_visibility", "monitor_brand_mentions",
            "build_growth_plan"} <= tasks


def test_domain_scoped_tasks_are_marked():
    per_domain = {t for t, _, needs in DEFAULT_SCHEDULES if needs}
    assert "crawl_domain" in per_domain and "sync_search_console" in per_domain
    assert "monitor_brand_mentions" not in per_domain  # project-wide, not per domain
