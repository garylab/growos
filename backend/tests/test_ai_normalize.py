from app.adapters.ai.gemini import GeminiAdapter
from app.adapters.ai.openai import OpenAIAdapter
from app.adapters.ai.openai_compat import PerplexityAdapter
from app.adapters.base import CollectResult


def test_openai_responses_normalize_with_citations():
    raw = {"model": "gpt-4.1-mini-2025-04-14", "usage": {"input_tokens": 10, "output_tokens": 20},
           "output": [{"type": "web_search_call"}, {"type": "message", "content": [{"type": "output_text", "text": "Try Hirelala.",
                      "annotations": [{"type": "url_citation", "url": "https://www.hirelala.com/x", "title": "Hirelala"}]}]}]}
    a = OpenAIAdapter(credentials={"api_key": "k"}).normalize(CollectResult(raw=raw, meta={"latency_ms": 5, "request": {"model": "gpt-4.1-mini", "input": "q"}, "grounded": True}))
    assert a.grounded and a.grounding_type == "web_search" and a.model_version == "gpt-4.1-mini-2025-04-14"
    assert a.citations[0].domain == "hirelala.com" and "input" not in a.request_config


def test_gemini_normalize_grounding():
    raw = {"modelVersion": "gemini-2.5-flash", "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4},
           "candidates": [{"content": {"parts": [{"text": "Answer"}]}, "groundingMetadata": {"webSearchQueries": ["q"],
                           "groundingChunks": [{"web": {"uri": "https://news.example.org/a", "title": "News"}}]}}]}
    a = GeminiAdapter(credentials={"api_key": "k"}).normalize(CollectResult(raw=raw, meta={"latency_ms": 1, "model": "gemini-2.5-flash", "request": {}}))
    assert a.grounded and a.citations[0].domain == "news.example.org" and a.text == "Answer"


def test_perplexity_always_grounded():
    raw = {"model": "sonar", "choices": [{"message": {"content": "Hi"}}], "citations": ["https://a.com/1", "https://a.com/1"], "usage": {}}
    a = PerplexityAdapter(credentials={"api_key": "k"}).normalize(CollectResult(raw=raw, meta={"latency_ms": 1, "request": {"model": "sonar", "messages": []}}))
    assert a.grounded and a.grounding_type == "provider_search" and len(a.citations) == 1
