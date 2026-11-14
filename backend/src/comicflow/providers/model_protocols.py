"""Validated configuration for existing adapters; never execute template code."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from comicflow.domain.errors import DomainError

USAGES = {
    "story": "故事生成",
    "script": "剧本拆分",
    "character-prompt": "人物提示词",
    "video-prompt": "视频提示词润色",
    "image": "角色/场景文生图",
    "image-edit": "参考图/三视图编辑",
    "video": "镜头视频",
}
TEXT_USAGES = ["story", "script", "character-prompt", "video-prompt"]
PROTOCOLS: dict[str, dict[str, Any]] = {
    "chat-completions": {
        "name": "Chat Completions 兼容文本",
        "provider": "bailian",
        "usages": TEXT_USAGES,
        "defaults": {"timeoutMs": 120000},
    },
    "doubao-chat": {
        "name": "火山方舟 Chat Completions",
        "provider": "doubao",
        "usages": TEXT_USAGES,
        "defaults": {"timeoutMs": 120000},
    },
    "chat-image": {
        "name": "Chat Completions 图片（Markdown Base64）",
        "provider": "openai-image",
        "usages": ["image"],
        "defaults": {"timeoutMs": 180000, "request": {"path": "/v1/chat/completions"}},
    },
    "wan-image": {
        "name": "万相文生图 V2",
        "provider": "bailian-image",
        "usages": ["image"],
        "defaults": {"timeoutMs": 180000, "size": "720*1280", "imageProtocol": "wan-v2"},
    },
    "wan26-image": {
        "name": "万相 2.6 图片/编辑",
        "provider": "bailian-image",
        "usages": ["image", "image-edit"],
        "defaults": {"timeoutMs": 180000, "size": "720*1280", "imageProtocol": "wan26-image"},
    },
    "compshare-h3": {
        "name": "优云 MiniMax H3",
        "provider": "compshare-h3",
        "usages": ["video"],
        "defaults": {
            "timeoutMs": 600000,
            "resolution": "768P",
            "h3PromptMode": "context-ir",
            "submitPath": "/minimax/v2/video_generation",
            "queryPath": "/minimax/v2/query/video_generation/{task_id}",
        },
    },
    "xiangongyun-h3": {
        "name": "仙宫云 MiniMax H3",
        "provider": "xiangongyun-h3",
        "usages": ["video"],
        "defaults": {
            "timeoutMs": 600000, "resolution": "0.5P",
            "inferenceProfile": "turbo8_av_sol_gpu_te",
            "h3PromptMode": "context-ir",
        },
    },
    "wan-video": {
        "name": "百炼万相视频",
        "provider": "bailian-video",
        "usages": ["video"],
        "defaults": {"timeoutMs": 600000, "resolution": "720P", "generationType": "i2v"},
    },
}
VARIABLES = {"model", "messages", "prompt", "body", "stream", "apiKey"}


def validate_endpoint(protocol: str, base_url: str) -> None:
    parsed = urlparse(base_url)
    host = parsed.hostname or ''
    if (
        protocol in {'wan-image', 'wan26-image', 'wan-video'}
        and (host == 'dashscope.aliyuncs.com' or host.startswith('dashscope-')
             and host.endswith('.aliyuncs.com'))
        and parsed.path.rstrip('/') == '/compatible-mode/v1'
    ):
        raise DomainError('MODEL_ENDPOINT_MISMATCH')


def invalid() -> None:
    raise DomainError("MODEL_CONFIG_INVALID")


def relative_path(path: Any, *, task: bool = False) -> None:
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        invalid()
    if "\\" in path or urlparse(path).netloc or urlparse(path).fragment:
        invalid()
    if task and "{task_id}" not in path:
        invalid()


def render(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables) for v in value]
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\{\{(\w+)\}\}", value)
    if match:
        if match[1] not in variables:
            invalid()
        return deepcopy(variables[match[1]])

    def substitute(match: re.Match[str]) -> str:
        replacement = variables.get(match[1])
        if not isinstance(replacement, str):
            invalid()
        return str(replacement)

    return re.sub(r"\{\{(\w+)\}\}", substitute, value)


def validate_config(protocol: str, raw: dict[str, Any]) -> dict[str, Any]:
    if protocol not in PROTOCOLS or not isinstance(raw, dict):
        invalid()
    defaults = PROTOCOLS[protocol]["defaults"]
    allowed = set(defaults) | {"timeoutMs"}
    if protocol in {"chat-completions", "doubao-chat", "chat-image"}:
        allowed |= {"request", "responseTextPath"}
    if protocol in {"wan-image", "wan26-image", "wan-video"}:
        allowed |= {"requestPath", "statusPath"}
    if set(raw) - allowed:
        invalid()
    config = {**deepcopy(defaults), **deepcopy(raw)}
    if isinstance(config.get('request'), dict):
        config['request'] = {**deepcopy(defaults.get('request', {})), **config['request']}
    for field in (
        "resolution", "h3PromptMode", "generationType", "imageProtocol", "inferenceProfile",
    ):
        if field in config and not isinstance(config[field], str):
            invalid()
    timeout = config["timeoutMs"]
    if type(timeout) is not int or not 1000 <= timeout <= 900000:
        invalid()
    if protocol in {"chat-completions", "doubao-chat"} and timeout > 300000:
        invalid()
    if protocol == "compshare-h3":
        if config["resolution"] not in {"768P", "1080P", "2K"}:
            invalid()
        if config["h3PromptMode"] not in {"local-skill", "context-ir"}:
            invalid()
        relative_path(config["submitPath"])
        relative_path(config["queryPath"], task=True)
    if protocol == "xiangongyun-h3":
        if config["resolution"] not in {"1.0P", "0.9P", "0.8P", "0.7P", "0.6P", "0.5P", "0.4P"}:
            invalid()
        if config["h3PromptMode"] not in {"local-skill", "context-ir"}:
            invalid()
        if config["inferenceProfile"] not in {
            "turbo4_av_sol_gpu_te", "turbo8_av_sol_gpu_te", "quality_av_sol_gpu_te",
        }:
            invalid()
    if protocol == "wan-video":
        if config["generationType"] not in {"t2v", "i2v"}:
            invalid()
        if config["resolution"] not in {"480P", "720P", "1080P"}:
            invalid()
    if protocol in {"wan-image", "wan26-image"}:
        if config["imageProtocol"] != defaults["imageProtocol"]:
            invalid()
        if not isinstance(config["size"], str) or not re.fullmatch(
            r"\d{2,4}\*\d{2,4}", config["size"]
        ):
            invalid()
    for field in ("requestPath", "statusPath"):
        if config.get(field):
            relative_path(config[field], task=field == "statusPath")
    request = config.get("request", {})
    if not isinstance(request, dict) or set(request) - {"path", "body", "headers"}:
        invalid()
    if "path" in request:
        relative_path(request["path"])
    body = request.get("body")
    if body is not None:
        if not isinstance(body, dict):
            invalid()
        # These adapters implement Chat Completions, not arbitrary message protocols.
        # Preserve the selected model and all Skill/system messages exactly.
        if body.get("model") != "{{model}}" or body.get("messages") != "{{messages}}":
            invalid()
        if "stream" in body and body["stream"] is not False and body["stream"] != "{{stream}}":
            invalid()
        if "{{apiKey}}" in json.dumps(body):
            invalid()
    headers = request.get("headers", {})
    if not isinstance(headers, dict) or any(not isinstance(v, str) for v in headers.values()):
        invalid()
    for name, value in headers.items():
        if name.lower() not in {"authorization", "x-api-key", "content-type"}:
            invalid()
        if "\r" in value or "\n" in value:
            invalid()
        if name.lower() != "content-type" and "{{apiKey}}" not in value:
            invalid()
        if set(re.findall(r"\{\{(\w+)\}\}", value)) - {"apiKey"}:
            invalid()
    variables = re.findall(r"\{\{(\w+)\}\}", json.dumps(request))
    if set(variables) - VARIABLES:
        invalid()
    path = config.get("responseTextPath", "choices[0].message.content")
    if not isinstance(path, str) or not re.fullmatch(r"\w+(?:\[\d+\]|\.\w+)*", path):
        invalid()
    # Also reject string interpolation of arrays/booleans at save time.
    render(
        request,
        {
            "model": "example",
            "messages": [],
            "prompt": "example",
            "body": {},
            "stream": False,
            "apiKey": "<secret>",
        },
    )
    return config


class TemplateTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        config: dict[str, Any],
        base_url: str,
        api_key: str,
        inner: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config, self.base_url, self.api_key = config, base_url, api_key
        self.inner = inner or httpx.AsyncHTTPTransport()

    def payload(self, body: dict[str, Any]) -> dict[str, Any]:
        variables = {
            "body": body,
            "model": body.get("model"),
            "messages": body.get("messages", []),
            "stream": body.get("stream", False),
            "prompt": body.get("messages", [{}])[-1].get("content", ""),
            "apiKey": self.api_key,
        }
        result = cast(
            dict[str, Any],
            render(
                self.config.get("request", {}).get("body", "{{body}}"),
                variables,
            ),
        )
        if body.get('stream') is True:
            result['stream'] = True
        return result

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        submission = request.method == "POST"
        if request.method == "POST":
            body = json.loads(request.content)
            config = self.config.get("request", {})
            url = self.base_url.rstrip("/") + config.get("path", "/chat/completions")
            headers = dict(request.headers)
            headers.pop("host", None)
            headers.pop("content-length", None)
            headers.update(
                {
                    k.lower(): v
                    for k, v in render(
                        config.get("headers", {}),
                        {"apiKey": self.api_key},
                    ).items()
                }
            )
            request = httpx.Request(
                "POST", url, headers=headers, json=self.payload(body), extensions=request.extensions
            )
        response = await self.inner.handle_async_request(request)
        path = self.config.get("responseTextPath", "choices[0].message.content")
        if submission and path != "choices[0].message.content" and response.is_success:
            await response.aread()
            try:
                value: Any = response.json()
                for token in re.findall(r"\w+|\[\d+\]", path):
                    value = value[int(token[1:-1])] if token.startswith("[") else value[token]
                return httpx.Response(200, json={"choices": [{"message": {"content": value}}]})
            except (KeyError, IndexError, TypeError, ValueError):
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from None
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
