"""Tests for OpenAI-compatible image generation provider."""

import base64
import json

import httpx
import pytest
from comicflow.providers.openai_image import OpenAIImageProvider


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns predefined responses."""

    def __init__(self, response_body: dict, status_code: int = 200):
        self.response_body = response_body
        self.status_code = status_code
        self.last_request = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        return httpx.Response(
            status_code=self.status_code,
            json=self.response_body,
            request=request,
        )


@pytest.mark.asyncio
async def test_openai_image_generates_and_decodes_base64():
    """OpenAI provider generates image and decodes Base64 from Markdown format."""
    # Create a small test PNG (1x1 transparent pixel)
    test_png = base64.b64encode(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
        b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    ).decode('ascii')

    transport = MockTransport({
        "choices": [{
            "message": {
                "content": f"![image](data:image/png;base64,{test_png})"
            }
        }]
    })

    provider = OpenAIImageProvider(
        api_key="test-key",
        base_url="https://test.api",
        model="gpt-image-2.5",
        timeout_seconds=30,
        asset_store=None,
        transport=transport,
    )

    shot = {
        "id": "shot_1",
        "visualDescription": "一只可爱的小猫",
        "imagePurpose": "character-reference",
    }

    result = await provider.generate(shot, [])

    # Verify request
    assert transport.last_request is not None
    assert transport.last_request.url.path == "/v1/chat/completions"
    assert "Bearer test-key" in transport.last_request.headers.get("Authorization", "")

    request_body = json.loads(transport.last_request.content)
    assert request_body["model"] == "gpt-image-2.5"
    assert request_body["messages"][0]["role"] == "user"
    assert "小猫" in request_body["messages"][0]["content"]

    # Verify result
    assert result["id"] == "img-shot_1"
    assert result["mediaType"] == "image"
    assert result["provider"] == "openai-image"
    assert result["bytes"] > 0
    assert "dataUri" in result
    assert result["dataUri"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_openai_image_builds_character_prompt():
    """Provider builds prompt from character inputs."""
    # Use the same valid PNG as the first test
    test_png = base64.b64encode(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
        b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    ).decode('ascii')

    transport = MockTransport({
        "choices": [{
            "message": {
                "content": f"![image](data:image/png;base64,{test_png})"
            }
        }]
    })

    provider = OpenAIImageProvider(
        api_key="key",
        base_url="https://api",
        model="gpt-image",
        transport=transport,
    )

    shot = {
        "id": "char_ref",
        "visualDescription": "主角站在门口",
        "imagePurpose": "character-reference",
    }

    characters = [
        {
            "name": "小明",
            "appearance": "短发，眼镜",
            "clothing": "校服",
        }
    ]

    await provider.generate(shot, characters)

    request_body = json.loads(transport.last_request.content)
    prompt = request_body["messages"][0]["content"]

    assert "主角站在门口" in prompt
    assert "小明" in prompt
    assert "短发" in prompt
    assert "校服" in prompt
    assert "全身正面角色参考图" in prompt


@pytest.mark.asyncio
async def test_openai_image_handles_http_errors():
    """Provider maps HTTP errors to domain error codes."""
    transport = MockTransport({"error": "unauthorized"}, status_code=401)

    provider = OpenAIImageProvider(
        api_key="bad-key",
        base_url="https://api",
        model="gpt-image",
        transport=transport,
    )

    shot = {"id": "s1", "visualDescription": "test"}

    with pytest.raises(RuntimeError) as exc_info:
        await provider.generate(shot, [])

    assert str(exc_info.value) == "PROVIDER_AUTH_FAILED"


@pytest.mark.asyncio
async def test_openai_image_rejects_invalid_response():
    """Provider raises error when response format is invalid."""
    transport = MockTransport({"choices": []})

    provider = OpenAIImageProvider(
        api_key="key",
        base_url="https://api",
        model="gpt-image",
        transport=transport,
    )

    shot = {"id": "s1", "visualDescription": "test"}

    with pytest.raises(RuntimeError) as exc_info:
        await provider.generate(shot, [])

    assert str(exc_info.value) == "PROVIDER_RESPONSE_INVALID"


@pytest.mark.asyncio
async def test_openai_image_rejects_missing_base64():
    """Provider raises error when Base64 image is missing from content."""
    transport = MockTransport({
        "choices": [{
            "message": {
                "content": "Sorry, I cannot generate that image."
            }
        }]
    })

    provider = OpenAIImageProvider(
        api_key="key",
        base_url="https://api",
        model="gpt-image",
        transport=transport,
    )

    shot = {"id": "s1", "visualDescription": "test"}

    with pytest.raises(RuntimeError) as exc_info:
        await provider.generate(shot, [])

    assert str(exc_info.value) == "IMAGE_RESPONSE_INVALID"
