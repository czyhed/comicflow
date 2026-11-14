from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ProviderMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


@dataclass(frozen=True, slots=True, repr=False)
class ProviderConfig:
    mode: ProviderMode = ProviderMode.MOCK
    bailian_api_key: str | None = None
    text_provider: str = "bailian"
    text_api_key: str | None = None
    text_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    evaluation_gate: bool = False
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @classmethod
    def from_env(cls, values: Mapping[str, str]) -> ProviderConfig:
        raw_mode = values.get("PROVIDER_MODE", "mock").lower()
        try:
            mode = ProviderMode(raw_mode)
        except ValueError as error:
            raise RuntimeError("PROVIDER_MODE_INVALID") from error
        text_provider = values.get("TEXT_PROVIDER_PROVIDER", "bailian").strip().lower()
        if text_provider not in {"bailian", "doubao"}:
            raise RuntimeError("TEXT_PROVIDER_PROVIDER_INVALID")
        key = (
            values.get("DOUBAO_API_KEY") if text_provider == "doubao"
            else values.get("BAILIAN_API_KEY")
        ) or None
        bailian_base_url = values.get(
            "BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        text_base_url = (
            values.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
            if text_provider == "doubao"
            else bailian_base_url
        )
        gate = values.get("PROVIDER_EVALUATION_GATE", "").lower() in {"passed", "true", "1"}
        if mode is ProviderMode.REAL and not gate:
            raise RuntimeError("PROVIDER_EVALUATION_REQUIRED")
        if mode is ProviderMode.REAL and not key:
            raise RuntimeError(
                "DOUBAO_API_KEY_REQUIRED"
                if text_provider == "doubao"
                else "BAILIAN_API_KEY_REQUIRED"
            )
        return cls(
            mode=mode,
            bailian_api_key=values.get("BAILIAN_API_KEY") or None,
            text_provider=text_provider,
            text_api_key=key,
            text_base_url=text_base_url,
            evaluation_gate=gate,
            base_url=bailian_base_url,
        )

    def __repr__(self) -> str:
        return (
            f"ProviderConfig(mode={self.mode.value!r}, evaluation_gate={self.evaluation_gate!r}, "
            f"base_url={self.base_url!r}, bailian_api_key=<redacted>)"
        )


def select_provider_mode(config: ProviderConfig) -> ProviderMode:
    if config.mode is ProviderMode.REAL and config.evaluation_gate and config.text_api_key:
        return ProviderMode.REAL
    return ProviderMode.MOCK
