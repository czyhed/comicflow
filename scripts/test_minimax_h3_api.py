"""Minimal real API probe for MiniMax H3.

The request fields are intentionally printed and configurable so the first
run can be compared with the Compshare gateway documentation/account.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider, minimax_config_from_env


async def main() -> None:
    config = minimax_config_from_env()
    if not config["api_key"]:
        raise SystemExit("Set MINIMAX_API_KEY before running this probe.")
    if not os.getenv("BAILIAN_API_KEY"):
        raise SystemExit(
            "Export BAILIAN_API_KEY for the H3 Skill text model before this paid probe."
        )
    text_provider = BailianTextProvider(
        api_key=os.environ["BAILIAN_API_KEY"],
        base_url=os.getenv("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model=os.getenv("TEXT_PROVIDER_MODEL", "qwen-plus"),
        timeout_seconds=120,
        max_retries=0,
    )
    started = time.monotonic()
    provider = MinimaxH3Provider(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        submit_path=config["submit_path"],
        query_path=config["query_path"],
        prompt_writer=H3SkillPromptWriter(text_provider.compile_h3_prompt),
    )
    result = await provider.generate(
        {
            "id": "probe-shot",
            "visualDescription": "竖屏动漫风格，雨夜车站，一名角色缓慢回头",
            "durationSec": int(os.getenv("MINIMAX_PROBE_DURATION", "5")),
            "generationMode": "t2va",
        },
        [],
    )
    print(f"model={config['model']}")
    print(f"task_id={result.get('requestReference')}")
    print(f"video_url={result.get('sourceUrl')}")
    print(f"downloaded_bytes={result.get('bytes')}")
    print(f"elapsed_seconds={time.monotonic() - started:.1f}")


async def check_points() -> None:
    config = minimax_config_from_env()
    async with httpx.AsyncClient(
        base_url=config["base_url"],
        headers={"Authorization": f"Bearer {config['api_key']}"},
        timeout=30,
    ) as client:
        response = await client.get("/minimax/v2/query/point_usage_summary")
        response.raise_for_status()
        print(f"point_balance={response.json()}")


if __name__ == "__main__":
    asyncio.run(main())
