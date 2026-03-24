"""Multi-provider LLM routing with retries, rate limiting, and cost tracking."""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class RetryPolicy:
    """Retry behavior for transient provider failures."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_seconds: float = 0.25


@dataclass
class ModelConfig:
    """Provider/model selection and operational settings."""

    provider: str
    model: str
    role: str = "default"
    api_key_env: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 30.0
    requests_per_minute: int = 60
    input_cost_per_1k_tokens: float = 0.0
    output_cost_per_1k_tokens: float = 0.0


@dataclass
class LLMRequest:
    """Unified request payload used by all provider clients."""

    prompt: str
    system: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1000
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Unified response payload emitted by all provider clients."""

    provider: str
    model: str
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    """Protocol for concrete provider clients."""

    def complete(self, request: LLMRequest, retry_policy: RetryPolicy) -> LLMResponse:
        """Return one completion result for the provided request."""


class RateLimiter:
    """Simple thread-safe request-per-minute limiter."""

    def __init__(self, requests_per_minute: int) -> None:
        self.requests_per_minute = max(1, int(requests_per_minute))
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        """Block until a request slot is available."""
        while True:
            with self._lock:
                now = time.time()
                cutoff = now - 60.0
                while self._calls and self._calls[0] < cutoff:
                    self._calls.popleft()

                if len(self._calls) < self.requests_per_minute:
                    self._calls.append(now)
                    return

                wait_for = 60.0 - (now - self._calls[0])

            time.sleep(max(0.01, wait_for))


class _BaseHTTPProvider:
    """Shared HTTP client functionality for provider implementations."""

    def __init__(self, model_config: ModelConfig) -> None:
        self.model_config = model_config
        self.rate_limiter = RateLimiter(model_config.requests_per_minute)

    def complete(self, request: LLMRequest, retry_policy: RetryPolicy) -> LLMResponse:
        """Issue a request with provider-side rate limiting."""
        del retry_policy  # Retries are applied by router so providers stay stateless.
        self.rate_limiter.acquire()
        start = time.monotonic()
        response = self._send_request(request)
        response.latency_ms = round((time.monotonic() - start) * 1000.0, 2)
        return response

    def _send_request(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - abstract helper
        raise NotImplementedError

    def _http_post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        encoded = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url=url, data=encoded, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.model_config.timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)


class OpenAIProvider(_BaseHTTPProvider):
    """Provider for OpenAI chat-completions compatible APIs."""

    def _send_request(self, request: LLMRequest) -> LLMResponse:
        import os

        api_key = os.environ.get(self.model_config.api_key_env or "OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("Missing OpenAI API key")

        base_url = self.model_config.base_url or "https://api.openai.com"
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "v1/chat/completions")

        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload = {
            "model": self.model_config.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = self._http_post(url, payload, headers)

        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))

        return LLMResponse(
            provider="openai",
            model=self.model_config.model,
            text=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=0.0,
            metadata={"raw_id": data.get("id")},
        )


class OpenAICompatibleProvider(OpenAIProvider):
    """Provider for local/self-hosted OpenAI-compatible endpoints."""

    pass


class AnthropicProvider(_BaseHTTPProvider):
    """Provider for Anthropic Messages API."""

    def _send_request(self, request: LLMRequest) -> LLMResponse:
        import os

        api_key = os.environ.get(self.model_config.api_key_env or "ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("Missing Anthropic API key")

        base_url = self.model_config.base_url or "https://api.anthropic.com"
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "v1/messages")

        payload = {
            "model": self.model_config.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            payload["system"] = request.system

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        data = self._http_post(url, payload, headers)

        content_chunks = data.get("content") or []
        text = "\n".join(chunk.get("text", "") for chunk in content_chunks if isinstance(chunk, dict))
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens", 0))
        completion_tokens = int(usage.get("output_tokens", 0))
        total_tokens = prompt_tokens + completion_tokens

        return LLMResponse(
            provider="anthropic",
            model=self.model_config.model,
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=0.0,
            metadata={"raw_id": data.get("id")},
        )


class GoogleProvider(_BaseHTTPProvider):
    """Provider for Google Gemini generateContent API."""

    def _send_request(self, request: LLMRequest) -> LLMResponse:
        import os

        api_key = os.environ.get(self.model_config.api_key_env or "GOOGLE_API_KEY", "")
        if not api_key:
            raise RuntimeError("Missing Google API key")

        base_url = self.model_config.base_url or "https://generativelanguage.googleapis.com"
        model = urllib.parse.quote(self.model_config.model, safe="")
        path = f"v1beta/models/{model}:generateContent"
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path)
        url = f"{url}?key={urllib.parse.quote(api_key)}"

        parts = []
        if request.system:
            parts.append({"text": request.system})
        parts.append({"text": request.prompt})

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        headers = {"Content-Type": "application/json"}
        data = self._http_post(url, payload, headers)

        candidates = data.get("candidates") or []
        candidate = candidates[0] if candidates else {}
        content = candidate.get("content") or {}
        candidate_parts = content.get("parts") or []
        text = "\n".join(part.get("text", "") for part in candidate_parts if isinstance(part, dict))

        usage = data.get("usageMetadata") or {}
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))
        total_tokens = int(usage.get("totalTokenCount", prompt_tokens + completion_tokens))

        return LLMResponse(
            provider="google",
            model=self.model_config.model,
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=0.0,
            metadata={"raw_response": data.get("modelVersion", "")},
        )


class MockProvider:
    """Deterministic provider used when real credentials are unavailable."""

    def __init__(self, model_config: ModelConfig) -> None:
        self.model_config = model_config

    def complete(self, request: LLMRequest, retry_policy: RetryPolicy) -> LLMResponse:
        del retry_policy
        text = json.dumps(
            {
                "change_description": "Enable quality boost and strengthen routing instructions",
                "config_section": "prompts",
                "reasoning": "High error/routing buckets suggest improving prompt specificity.",
                "new_config_patch": {
                    "quality_boost": True,
                    "prompts.root_suffix": " Be thorough and verify answers before responding.",
                },
            }
        )
        prompt_tokens = max(1, len(request.prompt.split()))
        completion_tokens = max(1, len(text.split()))
        total_tokens = prompt_tokens + completion_tokens
        return LLMResponse(
            provider=self.model_config.provider,
            model=self.model_config.model,
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=10.0,
            metadata={"proposal_score": 0.5},
        )


@dataclass
class _CostEntry:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0


class LLMRouter:
    """Strategy-driven model router supporting single/round-robin/ensemble/mixture."""

    def __init__(
        self,
        *,
        strategy: str,
        models: list[ModelConfig],
        providers: dict[tuple[str, str], LLMProvider] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if not models:
            raise ValueError("LLMRouter requires at least one model")

        self.strategy = strategy
        self.models = models
        self.retry_policy = retry_policy or RetryPolicy()
        self.providers = providers or {
            (model.provider, model.model): self._build_provider(model)
            for model in models
        }
        self._round_robin_index = 0
        self._cost_lock = threading.Lock()
        self._costs: dict[str, _CostEntry] = {}

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one model response based on routing strategy."""
        if self.strategy == "single":
            return self._run_model(self.models[0], request)

        if self.strategy == "round_robin":
            model = self.models[self._round_robin_index % len(self.models)]
            self._round_robin_index = (self._round_robin_index + 1) % len(self.models)
            return self._run_model(model, request)

        if self.strategy in {"ensemble", "mixture"}:
            responses = [self._run_model(model, request) for model in self.models]
            return max(responses, key=lambda item: float(item.metadata.get("proposal_score", 0.0)))

        raise ValueError(f"Unsupported router strategy: {self.strategy}")

    def cost_summary(self) -> dict[str, dict[str, float | int]]:
        """Return current aggregated cost stats keyed by provider:model."""
        with self._cost_lock:
            return {
                key: {
                    "requests": value.requests,
                    "prompt_tokens": value.prompt_tokens,
                    "completion_tokens": value.completion_tokens,
                    "total_cost": round(value.total_cost, 8),
                }
                for key, value in self._costs.items()
            }

    def _run_model(self, model: ModelConfig, request: LLMRequest) -> LLMResponse:
        provider = self.providers.get((model.provider, model.model))
        if provider is None:
            raise ValueError(f"No provider client registered for {model.provider}:{model.model}")

        response = self._call_with_retry(provider, request)
        self._track_cost(model, response)
        return response

    def _call_with_retry(self, provider: LLMProvider, request: LLMRequest) -> LLMResponse:
        last_error: Exception | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                return provider.complete(request, self.retry_policy)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as exc:
                last_error = exc
                if attempt >= self.retry_policy.max_attempts:
                    break
                delay = min(
                    self.retry_policy.max_delay_seconds,
                    self.retry_policy.base_delay_seconds * (2 ** (attempt - 1)),
                )
                jitter = random.uniform(0.0, self.retry_policy.jitter_seconds)
                time.sleep(max(0.0, delay + jitter))

        if last_error is None:
            raise RuntimeError("Provider call failed without raised exception")
        raise last_error

    def _track_cost(self, model: ModelConfig, response: LLMResponse) -> None:
        key = f"{model.provider}:{model.model}"
        input_cost = (response.prompt_tokens / 1000.0) * model.input_cost_per_1k_tokens
        output_cost = (response.completion_tokens / 1000.0) * model.output_cost_per_1k_tokens

        with self._cost_lock:
            entry = self._costs.setdefault(key, _CostEntry())
            entry.requests += 1
            entry.prompt_tokens += response.prompt_tokens
            entry.completion_tokens += response.completion_tokens
            entry.total_cost += input_cost + output_cost

    @staticmethod
    def _build_provider(model: ModelConfig) -> LLMProvider:
        provider_name = model.provider.strip().lower()
        if provider_name == "openai":
            return OpenAIProvider(model)
        if provider_name in {"openai_compatible", "local"}:
            return OpenAICompatibleProvider(model)
        if provider_name == "anthropic":
            return AnthropicProvider(model)
        if provider_name == "google":
            return GoogleProvider(model)
        if provider_name == "mock":
            return MockProvider(model)
        raise ValueError(f"Unsupported provider: {model.provider}")


def build_router_from_runtime_config(optimizer_config: Any) -> LLMRouter:
    """Create an LLMRouter from runtime optimizer config models/settings."""
    model_configs: list[ModelConfig] = []
    provider_clients: dict[tuple[str, str], LLMProvider] = {}

    for model in getattr(optimizer_config, "models", []):
        model_config = ModelConfig(
            provider=str(getattr(model, "provider")),
            model=str(getattr(model, "model")),
            role=str(getattr(model, "role", "default")),
            api_key_env=getattr(model, "api_key_env", None),
            base_url=getattr(model, "base_url", None),
            timeout_seconds=float(getattr(model, "timeout_seconds", 30.0)),
            requests_per_minute=int(getattr(model, "requests_per_minute", 60)),
            input_cost_per_1k_tokens=float(getattr(model, "input_cost_per_1k_tokens", 0.0)),
            output_cost_per_1k_tokens=float(getattr(model, "output_cost_per_1k_tokens", 0.0)),
        )
        model_configs.append(model_config)

        if bool(getattr(optimizer_config, "use_mock", True)):
            provider_clients[(model_config.provider, model_config.model)] = MockProvider(model_config)
        else:
            provider_clients[(model_config.provider, model_config.model)] = LLMRouter._build_provider(model_config)

    if not model_configs:
        fallback = ModelConfig(provider="mock", model="mock-proposer")
        model_configs.append(fallback)
        provider_clients[(fallback.provider, fallback.model)] = MockProvider(fallback)

    retry = getattr(optimizer_config, "retry", None)
    retry_policy = RetryPolicy(
        max_attempts=int(getattr(retry, "max_attempts", 3)),
        base_delay_seconds=float(getattr(retry, "base_delay_seconds", 0.5)),
        max_delay_seconds=float(getattr(retry, "max_delay_seconds", 8.0)),
        jitter_seconds=float(getattr(retry, "jitter_seconds", 0.25)),
    )

    return LLMRouter(
        strategy=str(getattr(optimizer_config, "strategy", "single")),
        models=model_configs,
        providers=provider_clients,
        retry_policy=retry_policy,
    )
