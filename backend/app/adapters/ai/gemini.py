"""Google Gemini adapter (generateContent). Optional Google Search grounding yields citations via groundingMetadata."""
from __future__ import annotations

import time
from typing import Any, ClassVar

import httpx

from app.adapters.ai.common import AIAnswer, ChatTurn, Citation, ToolCall, dedupe_citations, domain_of
from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAdapter(ProviderAdapter):
    key: ClassVar[str] = "gemini"
    category: ClassVar[str] = "ai"
    vendor: ClassVar[str] = "Google"
    vendor_url: ClassVar[str] = "https://aistudio.google.com"
    display_name: ClassVar[str] = "Google Gemini"
    description: ClassVar[str] = "Gemini models for AI-visibility sampling (optionally grounded with Google Search) and analysis."
    docs_url: ClassVar[str] = "https://ai.google.dev/gemini-api/docs/grounding"
    credential_fields: ClassVar[list[CredentialField]] = [
        CredentialField("api_key", "API key",
                        help="Google AI Studio → Get API key. Leave blank to use GEMINI_API_KEY from the server's "
                             "environment. This is not the same key as GOOGLE_API_KEY, which is a Cloud console "
                             "key for PageSpeed and CrUX."),
    ]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("model", "Model for visibility sampling", "string", "gemini-2.5-flash"),
        ConfigField("analysis_model", "Model for analysis (tool calling)", "string", "gemini-2.5-pro"),
        ConfigField("google_search", "Enable Google Search grounding for sampling", "boolean", True),
        ConfigField("temperature", "Temperature", "number", 1.0),
        ConfigField("use_for_analysis", "Use this connection for the AI analyst", "boolean", False),
    ]

    def _post(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.credentials.get("api_key"):
            raise ProviderError("Gemini API key is not configured")
        r = httpx.post(f"{BASE}/models/{model}:generateContent", params={"key": self.credentials["api_key"]},
                       json=body, timeout=120)
        if r.status_code != 200:
            raise ProviderError(f"Gemini error {r.status_code}: {r.text[:300]}")
        return r.json()

    def health_check(self) -> HealthResult:
        try:
            r = httpx.get(f"{BASE}/models", params={"key": self.credentials.get("api_key", ""), "pageSize": 5}, timeout=30)
            if r.status_code == 200:
                return HealthResult(True, "API key accepted")
            return HealthResult(False, f"Gemini responded {r.status_code}: {r.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Gemini check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(category="ai", measurement_type="observed",
                            features=["answer_sampling", "google_search_grounding", "tool_calling"],
                            notes="API answers do not exactly reproduce the consumer Gemini app; see methodology.")

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        n = int(request.get("samples", 1))
        return UsageEstimate(requests=n, tokens=n * 1500, unit_type="tokens")

    def collect(self, request: dict[str, Any]) -> CollectResult:
        model = request.get("model") or self.config["model"]
        grounded = bool(request.get("google_search", self.config["google_search"]))
        language, country = request.get("language", "en"), request.get("country", "US")
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": f"Answer as you would for a user in {country} writing in language '{language}'."}]},
            "contents": [{"role": "user", "parts": [{"text": request["prompt"]}]}],
            "generationConfig": {"temperature": float(self.config["temperature"])},
        }
        if grounded:
            body["tools"] = [{"google_search": {}}]
        t0 = time.monotonic()
        raw = self._post(model, body)
        return CollectResult(raw=raw, meta={"latency_ms": int((time.monotonic() - t0) * 1000), "model": model,
                                            "request": {"model": model, "tools": body.get("tools"),
                                                        "generationConfig": body["generationConfig"]}})

    def normalize(self, result: CollectResult) -> AIAnswer:
        raw = result.raw
        cand = (raw.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
        gm = cand.get("groundingMetadata") or {}
        citations = []
        for chunk in gm.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            if web.get("uri"):
                citations.append(Citation(web["uri"], domain_of(web.get("uri")), web.get("title")))
        grounded = bool(gm.get("webSearchQueries") or citations)
        return AIAnswer(text=text.strip(), model=result.meta["model"], model_version=raw.get("modelVersion"),
                        grounded=grounded, grounding_type="web_search" if grounded else "none",
                        citations=dedupe_citations(citations), usage=raw.get("usageMetadata") or {},
                        latency_ms=result.meta["latency_ms"], request_config=result.meta["request"], raw=raw)

    # ------------------------------------------------------------ tool calling (analysis)
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             model: str | None = None) -> ChatTurn:
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            if m["role"] == "gemini_raw":
                contents.append(m["content"])
            elif m["role"] == "tool":
                contents.append({"role": "user", "parts": [{"functionResponse": {"name": m["name"], "response": {"result": m["content"]}}}]})
            else:
                contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"] or ""}]})
        body: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": 0.2}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
        raw = self._post(model or self.config["analysis_model"], body)
        cand = (raw.get("candidates") or [{}])[0]
        content = cand.get("content") or {"role": "model", "parts": []}
        text_parts, calls = [], []
        for i, p in enumerate(content.get("parts", [])):
            if "text" in p:
                text_parts.append(p["text"])
            if "functionCall" in p:
                fc = p["functionCall"]
                calls.append(ToolCall(f"{fc['name']}-{i}", fc["name"], fc.get("args") or {}))
        return ChatTurn(text="".join(text_parts) or None, tool_calls=calls, usage=raw.get("usageMetadata") or {},
                        raw_message={"role": "gemini_raw", "content": content})

    @staticmethod
    def tool_result_message(call: ToolCall, content: str) -> dict[str, Any]:
        return {"role": "tool", "name": call.name, "content": content}
