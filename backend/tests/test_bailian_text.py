import json

import httpx
import pytest
from comicflow.providers.bailian_text import BailianTextProvider


def _provider(handler) -> BailianTextProvider:
    return BailianTextProvider(
        api_key="secret-key",
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )


async def test_text_provider_parses_structured_script_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-key"
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        assert "6 到 12 个 shots" in prompt
        assert "durationSec（数字）" in prompt
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title":"雨夜","scenes":[],"shots":[]}'}}]},
        )

    result = await _provider(handler).generate_script("故事", "project-1")
    assert result == {"title": "雨夜", "scenes": [], "shots": []}


async def test_text_provider_marks_guided_prompt_and_streams_automatic_story() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        if payload.get("stream"):
            assert "mode=automatic" in system
            assert "task=story_expansion" in system
            assert "characters 必须是数组" in system
            assert "beats 必须是数组" in system
            assert "setup、development、turn、ending" in system
            assert payload["response_format"] == {"type": "json_object"}
            return httpx.Response(
                200,
                text=(
                    'data: {"choices":[{"delta":{"content":"第一段"}}]}\n\n'
                    'data: {"choices":[{"delta":{"content":"第二段"}}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        assert "mode=guided" in system
        assert "task=script_outline" in system
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title":"雨夜","scenes":[],"shots":[]}'}}]},
        )

    provider = _provider(handler)
    assert [chunk async for chunk in provider.stream_story_text("故事", "project-1")] == [
        "第一段",
        "第二段",
    ]
    assert (await provider.generate_script("故事", "project-1"))["title"] == "雨夜"


async def test_text_provider_rejects_non_success_without_leaking_key() -> None:
    provider = _provider(lambda _request: httpx.Response(429, text="rate limited"))
    with pytest.raises(RuntimeError, match="PROVIDER_RATE_LIMITED") as error:
        await provider.generate_script("故事", "project-1")
    assert "secret-key" not in str(error.value)


async def test_stream_story_classifies_auth_failure() -> None:
    provider = _provider(lambda _request: httpx.Response(401, text="unauthorized"))
    with pytest.raises(RuntimeError, match="PROVIDER_AUTH_FAILED"):
        _ = [chunk async for chunk in provider.stream_story_text("故事", "project-1")]


async def test_text_provider_rejects_invalid_script_shape() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"title":"缺字段"}'}}]},
        )
    )
    with pytest.raises(RuntimeError, match="PROVIDER_RESPONSE_INVALID"):
        await provider.generate_script("故事", "project-1")


async def test_text_provider_normalizes_bailian_storyboard_shape() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"雨夜","scenes":[{"scene_id":1,'
                                '"name":"车站","shots":[{"shot_id":"1-1",'
                                '"shot_type":"中景","camera":"固定","duration":30,'
                                '"description":"车站","audio":"雨声"}]}]}'
                            )
                        }
                    }
                ]
            },
        )
    )
    result = await provider.generate_script("故事", "project-1")
    assert result["scenes"] == [{"id": "scene-1", "title": "车站", "shotIds": ["1-1"]}]
    assert result["shots"] == [
        {
            "id": "1-1",
            "order": 1,
            "title": "车站",
            "action": "固定",
            "emotion": "平静",
            "shotSize": "中景",
            "durationSec": 30,
            "visualDescription": "车站",
            "dialogue": "",
            "narration": "雨声",
            "characters": [],
            "characterIds": [],
            "cameraMovement": "固定镜头",
            "visualStyle": "统一漫画风格，色彩和线条保持连续",
            "soundscape": "安静的环境声",
            "music": "克制的背景音乐，无突兀变化",
            "generationMode": "t2va",
        }
    ]


async def test_text_provider_extracts_json_after_reasoning_and_markdown() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>先整理故事</think>下面是结果：\n"
                                "```json\n"
                                '{"title":"雨夜","scenes":[],"shots":[]}\n'
                                "```\n"
                            )
                        }
                    }
                ]
            },
        )
    )
    assert await provider.generate_script("故事", "project-1") == {
        "title": "雨夜",
        "scenes": [],
        "shots": [],
    }


async def test_text_provider_extracts_text_content_block() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": '{"title":"雨夜",'},
                                {"type": "text", "text": '"scenes":[],"shots":[]}'},
                            ]
                        }
                    }
                ]
            },
        )
    )
    assert (await provider.generate_script("故事", "project-1"))["title"] == "雨夜"


async def test_text_provider_normalizes_flat_outline_with_string_durations() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"雨夜","scenes":[{"scene_id":1,'
                                '"title":"车站","time":"夜晚","location":"站台",'
                                '"narrativeGoal":"寻找姐姐","conflict":"暴雨",'
                                '"turningPoint":"姐姐回头"},{"scene_id":2,"title":"回头"}],'
                                '"shots":[{"shot_id":1,"scene_id":1,"shot_size":"中景",'
                                '"camera_movement":"推近","duration":"4秒",'
                                '"description":"雨夜车站",'
                                '"audio":{"dialogue":["你来了"]}},'
                                '{"shot_id":2,"scene_id":2,"shot_size":"特写",'
                                '"camera_movement":"固定","duration":"3秒",'
                                '"description":"姐姐回头","audio":{"dialogue":[]}}]}'
                            )
                        }
                    }
                ]
            },
        )
    )
    result = await provider.generate_script("故事", "project-1")
    assert result["shots"][0]["durationSec"] == 4
    assert result["shots"][0]["shotSize"] == "中景"
    assert result["shots"][0]["action"] == "推近"
    assert result["shots"][0]["dialogue"] == "你来了"
    assert result["scenes"][0]["location"] == "站台"
    assert result["scenes"][0]["narrativeGoal"] == "寻找姐姐"
    assert result["scenes"][0]["shotIds"] == ["1"]


async def test_text_provider_preserves_common_dialogue_aliases_and_speaker_lines() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"雨夜","scenes":[{"scene_id":1,"title":"车站"}],'
                                '"shots":[{"shot_id":1,"scene_id":1,"shot_size":"中景",'
                                '"camera":"固定","duration":30,"description":"车站",'
                                '"dialogueLines":[{"speaker":"弟弟","text":"姐姐，是你吗？"},'
                                '{"speaker":"姐姐","text":"别回头。"}]}]}'
                            )
                        }
                    }
                ]
            },
        )
    )

    result = await provider.generate_script("故事", "project-1")

    assert result["shots"][0]["dialogue"] == "弟弟：姐姐，是你吗？\n姐姐：别回头。"
    assert result["shots"][0]["narration"] == ""


async def test_text_provider_returns_bounded_guided_question() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"question":"主角最害怕失去什么？","done":false}'
                        }
                    }
                ]
            },
        )
    )

    result = await provider.generate_guided_question(
        "故事", {"title": "雨夜", "scenes": [], "shots": []}, [], "project-1"
    )

    assert result == {"question": "主角最害怕失去什么？", "done": False}


async def test_guided_prompt_prioritizes_story_closure_and_tracks_gaps() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured["system"] = payload["messages"][0]["content"]
        captured["user"] = payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"question":"结局如何收束？","done":false}'}},
                ]
            },
        )

    provider = _provider(handler)
    await provider.generate_guided_question(
        "失踪的姐姐在末班车出现",
        {
            "title": "末班车",
            "scenes": [{"id": "scene-1", "title": "车站", "shotIds": ["shot-1"]}],
            "shots": [],
        },
        [{"question": "主角是谁？", "answer": "弟弟"}],
        "project-1",
    )

    system = str(captured["system"])
    user = str(captured["user"])
    assert "角色目标" in system
    assert "核心冲突" in system
    assert "关键转折" in system
    assert "结尾情绪" in system
    assert "已确认信息" in user
    assert "未解决信息" in user
    assert "不能重复" in system
    assert "信息已经足够" in system
    assert "最多 9 轮" in system


async def test_text_provider_returns_done_guided_question() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"question":"","done":true}'}}]},
        )
    )

    result = await provider.generate_guided_question(
        "故事", {"title": "雨夜", "scenes": [], "shots": []}, [], "project-1"
    )

    assert result == {"question": "", "done": True}


async def test_text_provider_generates_detailed_script_from_context() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"详细雨夜","scenes":[{"id":"s1",'
                                '"title":"车站","shots":[{"id":"shot-1",'
                                '"title":"回头","action":"回头","emotion":"惊讶",'
                                '"shotSize":"特写","durationSec":30,"visualDescription":"姐姐回头",'
                                '"dialogue":"你来了","narration":""}]}],"shots":[]}'
                            )
                        }
                    }
                ]
            },
        )
    )

    result = await provider.generate_detailed_script(
        "故事", {"title": "雨夜", "scenes": [], "shots": []}, [], "project-1"
    )

    assert result["title"] == "详细雨夜"
    assert result["shots"][0]["visualDescription"] == "姐姐回头"


async def test_text_provider_generates_plain_story_text_without_script_requirement() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "雨夜的末班车驶入空站，姐姐从最后一排回头。"}},
                ]
            },
        )
    )

    result = await provider.generate_story_text("失踪十年的姐姐出现", "project-1")

    assert result == "雨夜的末班车驶入空站，姐姐从最后一排回头。"


async def test_text_provider_rejects_invalid_story_without_paid_repair() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"kind":"story_text","version":1,"content":{"title":"过短"}}',
        }}]})

    with pytest.raises(RuntimeError, match='PROVIDER_RESPONSE_INVALID'):
        await _provider(handler).generate_story_text("失踪的姐姐在末班车出现", "project-1")
    assert len(calls) == 1


async def test_text_provider_uses_story_text_when_optional_metadata_stays_invalid() -> None:
    long_text = "林默在暴雨夜的末班车上寻找失踪的姐姐，并逐步查明旧事故真相。" * 25
    content = json.dumps(
        {
            "kind": "story_text",
            "version": 1,
            "content": {"title": "雨夜回头", "text": long_text},
        },
        ensure_ascii=False,
    )
    provider = _provider(
        lambda _request: httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )
    )

    result = await provider.generate_story_text("失踪的姐姐在末班车出现", "project-1")

    assert result == long_text


async def test_text_provider_splits_story_text_into_normalized_script() -> None:
    provider = _provider(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"雨夜","scenes":[{"id":"s1","title":"车站",'
                                '"shots":[{"id":"shot-1","title":"回头","action":"固定",'
                                '"emotion":"惊讶","shotSize":"特写","durationSec":30,'
                                '"visualDescription":"姐姐回头","dialogue":"","narration":"雨声"}]}],'
                                '"shots":[]}'
                            )
                        }
                    }
                ]
            },
        )
    )

    with pytest.raises(RuntimeError, match="PROVIDER_RESPONSE_INVALID"):
        await provider.split_script("雨夜的末班车驶入空站", "project-1")


@pytest.mark.parametrize('explicit_silence', [True, False])
async def test_text_provider_distinguishes_silent_split_shot_from_missing_speech(
    explicit_silence,
) -> None:
    shots = [
        {
            "id": f"shot-{index}",
            "sceneId": "scene-1",
            "title": f"镜头{index}",
            "action": "固定",
            "emotion": "平静",
            "shotSize": "中景",
            "durationSec": 7.5,
            "visualDescription": "车站",
            "dialogue": "" if index == 8 else "继续前进。",
            "narration": "" if index == 8 else "雨声。",
        }
        for index in range(1, 9)
    ]
    if not explicit_silence:
        shots[-1].pop('dialogue')
        shots[-1].pop('narration')
    body = {"title": "雨夜", "scenes": [{"id": "scene-1", "title": "车站"}], "shots": shots}
    provider = _provider(
        lambda _request: httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]}
        )
    )

    if explicit_silence:
        result = await provider.split_script("雨夜的末班车驶入空站", "project-1")
        assert result['shots'][-1]['dialogue'] == result['shots'][-1]['narration'] == ''
    else:
        with pytest.raises(RuntimeError, match="PROVIDER_RESPONSE_INVALID"):
            await provider.split_script("雨夜的末班车驶入空站", "project-1")
