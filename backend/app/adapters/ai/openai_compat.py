"""OpenAI-compatible Chat Completions adapters: generic (any base URL), Ollama (local), Perplexity (grounded)."""
from __future__ import annotations

import json
import time
from typing import Any, ClassVar

import httpx

from app.adapters.ai.common import AIAnswer, ChatTurn, Citation, ToolCall, dedupe_citations, domain_of
from app.adapters.base import Capabilities, CollectResult, ConfigField, CredentialField, HealthResult, ProviderAdapter, ProviderError, UsageEstimate


class OpenAICompatibleAdapter(ProviderAdapter):
    key: ClassVar[str] = "openai_compatible"
    category: ClassVar[str] = "ai"
    vendor: ClassVar[str] = "OpenAI-compatible API"
    display_name: ClassVar[str] = "OpenAI-compatible API"
    description: ClassVar[str] = "Any provider exposing the OpenAI Chat Completions API (Groq, Together, DeepSeek, vLLM, ...)."
    credential_fields: ClassVar[list[CredentialField]] = [CredentialField("api_key", "API key", required=False)]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("base_url", "API base URL", "string", "https://api.example.com/v1"),
        ConfigField("model", "Model for visibility sampling", "string", ""),
        ConfigField("analysis_model", "Model for analysis (tool calling)", "string", ""),
        ConfigField("temperature", "Temperature", "number", 1.0),
        ConfigField("use_for_analysis", "Use this connection for the AI analyst", "boolean", False),
    ]
    grounding_type: ClassVar[str] = "none"
    always_grounded: ClassVar[bool] = False

    def _client(self) -> httpx.Client:
        headers = {}
        if self.credentials.get("api_key"):
            headers["Authorization"] = f"Bearer {self.credentials['api_key']}"
        base = (self.config.get("base_url") or "").rstrip("/")
        if not base:
            raise ProviderError("base_url is not configured")
        return httpx.Client(base_url=base, headers=headers, timeout=180)

    def health_check(self) -> HealthResult:
        try:
            with self._client() as c:
                r = c.get("/models")
            if r.status_code == 200:
                models = [m.get("id") for m in (r.json().get("data") or [])][:20]
                return HealthResult(True, f"Reachable. {len(models)} model(s) listed.", {"models": models})
            return HealthResult(False, f"Endpoint responded {r.status_code}: {r.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Check failed: {exc}")

    def get_capabilities(self) -> Capabilities:
        feats = ["answer_sampling", "tool_calling"] + (["provider_search_grounding"] if self.always_grounded else [])
        return Capabilities(category="ai", measurement_type="observed", features=feats)

    def estimate_usage(self, request: dict[str, Any]) -> UsageEstimate:
        n = int(request.get("samples", 1))
        return UsageEstimate(requests=n, tokens=n * 1200, unit_type="tokens")

    def _build_body(self, request: dict[str, Any]) -> dict[str, Any]:
        model = request.get("model") or self.config.get("model")
        if not model:
            raise ProviderError("No model configured for this connection")
        language, country = request.get("language", "en"), request.get("country", "US")
        return {"model": model, "temperature": float(self.config.get("temperature") or 1.0),
                "messages": [{"role": "system", "content": f"Answer as you would for a user in {country} writing in language '{language}'."},
                             {"role": "user", "content": request["prompt"]}]}

    def collect(self, request: dict[str, Any]) -> CollectResult:
        body = self._build_body(request)
        t0 = time.monotonic()
        with self._client() as c:
            r = c.post("/chat/completions", json=body)
        if r.status_code != 200:
            raise ProviderError(f"{self.display_name} error {r.status_code}: {r.text[:300]}")
        return CollectResult(raw=r.json(), meta={"latency_ms": int((time.monotonic() - t0) * 1000), "request": body})

    def normalize(self, result: CollectResult) -> AIAnswer:
        raw = result.raw
        msg = (raw.get("choices") or [{}])[0].get("message", {})
        text = msg.get("content") or ""
        citations = self._extract_citations(raw)
        req = dict(result.meta["request"])
        req.pop("messages", None)
        grounded = self.always_grounded or bool(citations)
        return AIAnswer(text=text.strip(), model=raw.get("model") or req["model"], model_version=raw.get("model"),
                        grounded=grounded, grounding_type=self.grounding_type if grounded else "none",
                        citations=dedupe_citations(citations), usage=raw.get("usage") or {},
                        latency_ms=result.meta["latency_ms"], request_config=req, raw=raw)

    def _extract_citations(self, raw: dict[str, Any]) -> list[Citation]:
        out = []
        for url in raw.get("citations") or []:
            if isinstance(url, str):
                out.append(Citation(url, domain_of(url)))
        for sr in raw.get("search_results") or []:
            if isinstance(sr, dict) and sr.get("url"):
                out.append(Citation(sr["url"], domain_of(sr["url"]), sr.get("title")))
        return out

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             model: str | None = None) -> ChatTurn:
        model = model or self.config.get("analysis_model") or self.config.get("model")
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        with self._client() as c:
            r = c.post("/chat/completions", json=body)
        if r.status_code != 200:
            raise ProviderError(f"{self.display_name} chat error {r.status_code}: {r.text[:300]}")
        data = r.json()
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append(ToolCall(tc.get("id") or tc["function"]["name"], tc["function"]["name"], args))
        return ChatTurn(text=msg.get("content"), tool_calls=calls, usage=data.get("usage") or {}, raw_message=msg)

    @staticmethod
    def tool_result_message(call: ToolCall, content: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": call.id, "content": content}


class OllamaAdapter(OpenAICompatibleAdapter):
    key: ClassVar[str] = "ollama"
    vendor: ClassVar[str] = "Ollama"
    vendor_url: ClassVar[str] = "https://ollama.com"
    display_name: ClassVar[str] = "Ollama (local models)"
    description: ClassVar[str] = "Local models through Ollama's OpenAI-compatible endpoint. No data leaves your network."
    docs_url: ClassVar[str] = "https://github.com/ollama/ollama/blob/main/docs/openai.md"
    credential_fields: ClassVar[list[CredentialField]] = []
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("base_url", "Ollama OpenAI-compatible URL", "string", "http://host.docker.internal:11434/v1"),
        ConfigField("model", "Model for visibility sampling", "string", "llama3.1"),
        ConfigField("analysis_model", "Model for analysis (tool calling)", "string", "llama3.1"),
        ConfigField("temperature", "Temperature", "number", 1.0),
        ConfigField("use_for_analysis", "Use this connection for the AI analyst", "boolean", False),
    ]


class PerplexityAdapter(OpenAICompatibleAdapter):
    key: ClassVar[str] = "perplexity"
    vendor: ClassVar[str] = "Perplexity"
    vendor_url: ClassVar[str] = "https://docs.perplexity.ai"
    display_name: ClassVar[str] = "Perplexity"
    description: ClassVar[str] = "Perplexity Sonar models; answers are always web-grounded and return citations."
    docs_url: ClassVar[str] = "https://docs.perplexity.ai/"
    credential_fields: ClassVar[list[CredentialField]] = [CredentialField("api_key", "API key")]
    config_fields: ClassVar[list[ConfigField]] = [
        ConfigField("base_url", "API base URL", "string", "https://api.perplexity.ai"),
        ConfigField("model", "Model for visibility sampling", "string", "sonar"),
        ConfigField("temperature", "Temperature", "number", 1.0),
    ]
    grounding_type: ClassVar[str] = "provider_search"
    always_grounded: ClassVar[bool] = True

    def health_check(self) -> HealthResult:
        try:
            res = self.collect({"prompt": "Reply with the single word OK.", "language": "en", "country": "US"})
            return HealthResult(True, f"Perplexity reachable (model {res.raw.get('model')})")
        except Exception as exc:  # noqa: BLE001
            return HealthResult(False, f"Perplexity check failed: {exc}")
