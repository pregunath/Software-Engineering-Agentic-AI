from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelCapabilities:
    name: str
    capabilities: tuple[str, ...]

    @property
    def supports_tools(self) -> bool:
        return "tools" in self.capabilities


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    async def model_capabilities(self) -> ModelCapabilities: ...

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...
