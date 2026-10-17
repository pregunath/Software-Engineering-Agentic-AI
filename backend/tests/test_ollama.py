import httpx
import pytest
from app.config import Settings
from app.llm import LLMError
from app.ollama import OllamaClient

pytestmark = pytest.mark.asyncio


def make_client(handler):
    return OllamaClient(
        Settings(ollama_model="test-model"),
        transport=httpx.MockTransport(handler),
    )


async def test_model_capabilities_and_chat() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"]})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "done"}})

    client = make_client(handler)
    capabilities = await client.model_capabilities("test-model")
    response = await client.chat("test-model", [{"role": "user", "content": "hello"}])

    assert capabilities.supports_tools
    assert response["message"]["content"] == "done"


async def test_malformed_chat_response_is_rejected() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(LLMError, match="malformed"):
        await make_client(handler).chat("test-model", [])
