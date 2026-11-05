from datetime import datetime

from app.adapters.base import CollectResult
from app.adapters.brand.apify_linkedin import ACTOR_ID, ApifyLinkedInPostsAdapter


def test_normalizes_posts_and_skips_paid_reaction_rows():
    raw = [{"type": "post", "id": "733", "linkedinUrl": "https://linkedin.com/posts/x", "content": "Acme news",
            "author": {"name": "Nick", "type": "profile", "linkedinUrl": "https://linkedin.com/in/nick"},
            "postedAt": {"date": "2025-05-21T16:12:05.614Z", "timestamp": 1747843925614},
            "engagement": {"likes": 13, "comments": 1, "shares": 9,
                           "reactions": [{"type": "LIKE", "count": 12}, {"type": "PRAISE", "count": 1}]}},
           {"type": "reaction", "id": "paid-extra"}]
    rows = ApifyLinkedInPostsAdapter(credentials={"apify_token": "x"}).normalize(CollectResult(raw=raw))
    assert len(rows) == 1
    assert rows[0]["source_id"] == "linkedin:733" and rows[0]["author"] == "Nick"
    assert rows[0]["published_at"] == datetime.fromisoformat("2025-05-21T16:12:05.614+00:00")
    assert rows[0]["engagement"] == {"likes": 13, "comments": 1, "shares": 9, "reactions": 13,
                                     "author_url": "https://linkedin.com/in/nick", "author_type": "profile"}


def test_collect_uses_one_bounded_run_with_expensive_extras_off(monkeypatch):
    calls = []
    class Response:
        status_code = 201
        text = "[]"
        def json(self):
            return []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr("app.adapters.brand.apify_linkedin.httpx.post", fake_post)
    adapter = ApifyLinkedInPostsAdapter(credentials={"apify_token": "secret"},
        config={"posted_limit": "week", "max_posts": 20, "max_charge_usd": 0.5})
    result = adapter.collect({"queries": ["Acme", "Acme", "Competitor"]})
    assert len(calls) == 1 and ACTOR_ID in calls[0][0]
    assert calls[0][1]["json"] == {"searchQueries": ["Acme", "Competitor"], "postedLimit": "week",
        "sortBy": "date", "maxPosts": 20, "scrapeComments": False, "maxComments": 10,
        "scrapeReactions": False, "maxReactions": 10}
    assert calls[0][1]["params"] == {"maxTotalChargeUsd": 0.5}
    assert result.meta["searches"] == 2 and "secret" not in str(result.meta)


def test_provider_catalog_exposes_linkedin_under_apify():
    from app.adapters.registry import ADAPTERS
    item = ADAPTERS["apify_linkedin_posts"].describe()
    assert item["vendor"] == "Apify" and item["category"] == "brand"
    assert {"mentions", "engagement", "linkedin"} <= set(item["features"])
