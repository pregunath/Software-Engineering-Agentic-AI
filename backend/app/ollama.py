from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.llm import LLMError, ModelCapabilities


@dataclass(frozen=True)
class OllamaHealth:
    available: bool
    version: str | None
    detail: str


class OllamaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._timeout = settings.ollama_timeout_seconds
        self._transport = transport

    async def health(self) -> OllamaHealth:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.get("/api/version")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            return OllamaHealth(False, None, f"Ollama unavailable: {error}")

        version = payload.get("version")
        if not isinstance(version, str):
            return OllamaHealth(False, None, "Ollama returned an invalid version response")
        return OllamaHealth(True, version, "Ollama is reachable")

    async def model_capabilities(self, model: str) -> ModelCapabilities:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post("/api/show", json={"name": model})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise LLMError(f"Could not inspect Ollama model '{model}': {error}") from error

        capabilities = payload.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise LLMError("Ollama returned invalid model capabilities")
        return ModelCapabilities(model, tuple(capabilities))

    def _client_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=10.0,
            read=self._timeout,
            write=30.0,
            pool=10.0,
        )

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if tools:
            request["tools"] = tools
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._client_timeout(), transport=self._transport
            ) as client:
                response = await client.post("/api/chat", json=request)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as error:
            raise LLMError(
                f"Ollama timed out after {self._timeout:.0f}s while generating a reply "
                f"with model '{model}'. The model may still be loading; try again, or raise "
                "AGENT_OLLAMA_TIMEOUT_SECONDS."
            ) from error
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:300] if error.response is not None else str(error)
            raise LLMError(
                f"Ollama chat request failed ({error.response.status_code if error.response else '?'}): {detail}"
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise LLMError(f"Ollama chat request failed: {error}") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("message"), dict):
            raise LLMError("Ollama returned a malformed chat response")
        return payload
