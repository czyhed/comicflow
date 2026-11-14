"""Explicit one-shot checks; address reachability is never model verification."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

import httpx

from comicflow.domain.errors import DomainError
from comicflow.providers.model_protocols import TemplateTransport
from comicflow.providers.text_errors import text_request_error

REASONS = {
    "authentication": "API Key 鉴权失败",
    "permission_denied": "当前 Key 没有请求权限",
    "rate_limited": "供应商限流或额度受限",
    "service_error": "供应商服务暂时不可用",
    "request_rejected": "供应商拒绝请求，请核对模型 ID、API 地址及调用参数",
    "invalid_parameter": "供应商不接受请求参数",
    "model_or_endpoint_not_found": "找不到模型或推理接入点",
    "model_not_enabled": "当前账号尚未开通该模型",
    "timeout": "连接或响应超时（本次测试上限15秒）",
    "connection_error": "无法连接服务，请检查地址、DNS、证书或代理",
    "invalid_response": "响应不符合文本协议，不能确认模型可用",
    "redirect": "接口返回重定向，未携带密钥继续跳转；请填写最终 API 地址",
}


class CheckTransport(TemplateTransport):
    def payload(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = super().payload(body)
        # Bound AFTER template expansion: a saved max_tokens/n cannot turn a
        # connection check into an expensive full-sized completion.
        payload["stream"] = False
        if "n" in payload:
            payload["n"] = 1
        if "max_completion_tokens" in payload:
            payload["max_completion_tokens"] = 1
            payload.pop("max_tokens", None)
        else:
            payload["max_tokens"] = 1
        if "max_output_tokens" in payload:
            payload["max_output_tokens"] = 1
        return payload


async def check_connection(
    connection: dict[str, Any],
    model: dict[str, Any] | None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    started = monotonic()
    result: dict[str, Any] = {"scope": "text" if model else "address", "status": "failed"}
    if model:
        if model["protocol"] not in {"chat-completions", "doubao-chat"}:
            raise DomainError("MODEL_CAPABILITY_UNSUPPORTED")
        if not connection.get("apiKey"):
            raise DomainError("PROVIDER_NOT_CONFIGURED")
        result["model"] = model["model"]
    try:
        async with asyncio.timeout(15):
            if model is None:
                # No Key and no redirects: this is only the configured address,
                # not an invented /models endpoint for a private media protocol.
                async with httpx.AsyncClient(
                    timeout=15,
                    follow_redirects=False,
                    transport=transport,
                ) as client:
                    async with client.stream("GET", connection["baseUrl"]) as response:
                        result.update(
                            status="partial",
                            upstreamStatus=response.status_code,
                            message=(
                                "已收到服务 HTTP 响应；仅证明地址可达，"
                                "未验证 Key、模型或生成能力。"
                            ),
                        )
            else:
                config = model["config"]
                adapter = CheckTransport(
                    config,
                    connection["baseUrl"],
                    connection["apiKey"],
                    inner=transport,
                )
                async with httpx.AsyncClient(
                    timeout=min(config.get("timeoutMs", 15000) / 1000, 15),
                    follow_redirects=False,
                    transport=adapter,
                ) as client:
                    response = await client.post(
                        connection["baseUrl"].rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {connection['apiKey']}"},
                        json={
                            "model": model["model"],
                            "messages": [
                                {"role": "user", "content": "ping"},
                            ],
                            "max_tokens": 1,
                        },
                    )
                result["upstreamStatus"] = response.status_code
                if response.is_redirect:
                    result["reason"] = "redirect"
                elif not response.is_success:
                    error = await text_request_error(response, "PROVIDER_REQUEST_INVALID")
                    result.update({k: v for k, v in error.detail.items() if k != "stage"})
                else:
                    body = response.json()
                    choices = body.get("choices") if isinstance(body, dict) else None
                    first = choices[0] if isinstance(choices, list) and choices else None
                    message = first.get("message") if isinstance(first, dict) else None
                    if (
                        isinstance(body, dict)
                        and not body.get("error")
                        and isinstance(message, dict)
                        and not message.get("refusal")
                        and isinstance(message.get("content"), str)
                    ):
                        result.update(
                            status="ok",
                            message=(
                                "文本最小请求通过，所选模型已接受请求；不代表故事契约或图片、视频生成已验证。"
                            ),
                        )
                    else:
                        result["reason"] = "invalid_response"
    except (TimeoutError, httpx.TimeoutException):
        result["reason"] = "timeout"
    except httpx.HTTPError:
        result["reason"] = "connection_error"
    except (ValueError, TypeError, RuntimeError):
        result["reason"] = "invalid_response"
    if result.get("reason"):
        result["message"] = REASONS.get(result["reason"], REASONS["request_rejected"])
    result["elapsedMs"] = int((monotonic() - started) * 1000)
    return result
