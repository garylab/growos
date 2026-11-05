import pytest

from app.intelligence.data import classify_ai_referral


@pytest.mark.parametrize("source,medium,expected", [
    ("chatgpt.com", "referral", "ChatGPT"),
    ("chatgpt.com", "ai-assistant", "ChatGPT"),
    ("chat.openai.com", "referral", "ChatGPT"),
    ("www.perplexity.ai", "referral", "Perplexity"),
    ("gemini.google.com", "referral", "Gemini"),
    ("copilot.microsoft.com", "referral", "Microsoft Copilot"),
    ("claude.ai", "referral", "Claude"),
    ("eu.perplexity.ai", "referral", "Perplexity"),
    ("google", "organic", None),
    ("bing", "organic", None),
    ("(direct)", "", None),
    ("accounts.google.com", "referral", None),
    ("someassistant.io", "ai-assistant", "someassistant.io"),
])
def test_classify_ai_referral(source, medium, expected):
    assert classify_ai_referral(source, medium) == expected


def test_search_engines_are_not_ai_referrals():
    # A search engine sending organic traffic must never be counted as an AI assistant.
    for s in ("google", "bing", "yahoo", "duckduckgo", "yandex"):
        assert classify_ai_referral(s, "organic") is None
