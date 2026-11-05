"""OpenAI adapter using the Responses API (supports the hosted web_search tool for grounded answers) and the
Chat Completions API for tool-calling analysis. Perplexity/Ollama/other OpenAI-compatible APIs use openai_compat."""
from __future__ import annotations

import time
from typing import Any, ClassVar

import httpx

from app.adapters.ai.common import AIAnswer, ChatTurn, Citation, ToolCall, dedupe_citations, domain_of
from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate


class OpenAIAdapter(ProviderAdapter):
    key: ClassVar[str] = "openai"
    category: ClassVar[str] = "ai"
    vendor: ClassVar[str] = "OpenAI"
    vendor_url: ClassVar[str] = "https://platform.openai.com"
    display_name: ClassVar[str] = "OpenAI"
    description: ClassVar[str] = "OpenAI models for AI-visibility sampling (optionally with web search grounding) and analysis."
    docs_url: ClassVar[str] = "https://platform.openai.com/docs/api-reference/responses"
    credential_fields: ClassVar[list[CredentialField]] = [CredentialField("api_key", "API key")]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("model", "Model for visibility sampling", "string", "gpt-4.1-mini"),
        ConfigField("analysis_model", "Model for analysis (tool calling)", "string", "gpt-4.1"),
        ConfigField("web_search", "Enable web search grounding for sampling", "boolean", True),
        ConfigField("temperature", "Temperature", "number", 1.0),
        ConfigField("base_url", "API base URL", "string", "https://api.openai.com/v1"),
        ConfigField("use_for_analysis", "Use this connection for the AI analyst", "boolean", False),
    ]

    def _client(self) -> httpx.Client:
        if not self.credentials.get("api_key"):
            raise ProviderError("OpenAI API key is not configured")
        return httpx.Client(base_url=self.config["base_url"].rstrip("/"),
                            headers={"Authorization": f"Bearer {self.credentials['api_key']}"}, timeout=120)

    def health_check(self) -> HealthResult:
        try:
            with self._client() as c:
                r = c.get("/models", params={"limit": 1})
            if r.status_code == 200:
                return HealthResult(True, "API key accepted")
            return HealthResult(False, f"OpenAI responded {r.status_code}: {r.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"OpenAI check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="ai", measurement_type="observed",
                            features=["answer_sampling", "web_search_grounding", "tool_calling"],
                            notes="API answers do not exactly reproduce consumer ChatGPT; see methodology.")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        n = int(request.get("samples", 1))
        return UsageEstimate(requests=n, tokens=n * 1500, unit_type="tokens")

    # ------------------------------------------------------------ sampling (GEO)
    def collect(self, request: dict[str, Any]) -> CollectResult:
        prompt = request["prompt"]
        model = request.get("model") or self.config["model"]
        grounded = bool(request.get("web_search", self.config["web_search"]))
        language, country = request.get("language", "en"), request.get("country", "US")
        body: dict[str, Any] = {"model": model, "input": prompt, "temperature": float(self.config["temperature"]),
                                "instructions": f"Answer as you would for a user in {country} writing in language '{language}'."}
        if grounded:
            body["tools"] = [{"type": "web_search_preview", "user_location": {"type": "approximate", "country": country}}]
        t0 = time.monotonic()
        with self._client() as c:
            r = c.post("/responses", json=body)
        if r.status_code != 200:
            raise ProviderError(f"OpenAI error {r.status_code}: {r.text[:300]}")
        return CollectResult(raw=r.json(), meta={"latency_ms": int((time.monotonic() - t0) * 1000), "request": body,
                                                 "grounded": grounded})

    def normalize(self, result: CollectResult) -> AIAnswer:
        raw = result.raw
        text_parts: list[str] = []
        citations: list[Citation] = []
        used_search = False
        for item in raw.get("output", []):
            if item.get("type") == "web_search_call":
                used_search = True
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text_parts.append(part.get("text", ""))
                        for ann in part.get("annotations", []):
                            if ann.get("type") == "url_citation" and ann.get("url"):
                                citations.append(Citation(ann["url"], domain_of(ann["url"]), ann.get("title")))
        req = dict(result.meta["request"])
        req.pop("input", None)
        return AIAnswer(text="\n".join(text_parts).strip(), model=raw.get("model") or req.get("model"),
                        model_version=raw.get("model"), grounded=used_search,
                        grounding_type="web_search" if used_search else "none", citations=dedupe_citations(citations),
                        usage=raw.get("usage") or {}, latency_ms=result.meta["latency_ms"], request_config=req, raw=raw)

    # ------------------------------------------------------------ tool calling (analysis)
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             model: str | None = None) -> ChatTurn:
        body: dict[str, Any] = {"model": model or self.config["analysis_model"], "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        with self._client() as c:
            r = c.post("/chat/completions", json=body)
        if r.status_code != 200:
            raise ProviderError(f"OpenAI chat error {r.status_code}: {r.text[:300]}")
        data = r.json()
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            import json as _json
            try:
                args = _json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append(ToolCall(tc["id"], tc["function"]["name"], args))
        return ChatTurn(text=msg.get("content"), tool_calls=calls, usage=data.get("usage") or {}, raw_message=msg)

    @staticmethod
    def tool_result_message(call: ToolCall, content: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call.id, "content": content}
