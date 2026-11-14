import json

import httpx
import pytest
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider


@pytest.mark.parametrize(
    "status,code",
    [(401, "PROVIDER_AUTH_FAILED"), (429, "VIDEO_RATE_LIMITED"), (500, "PROVIDER_HTTP_ERROR")],
)
async def test_video_http_failures_are_not_retried(status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    provider = BailianImageToVideoProvider(
        api_key="offline", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeError, match=code):
        await provider.generate(
            {
                "id": "s1",
                "durationSec": 5,
                "firstFrameUrl": "https://assets.test/f.png",
                "visualDescription": "雨夜车站",
            },
            [],
        )
    assert len(calls) == 1


async def test_t2v_27_uses_resolution_ratio_without_image():
    provider = BailianImageToVideoProvider(
        api_key="offline", model="wan2.7-t2v", generation_type="t2v", resolution="720P"
    )
    payload = provider._request(
        {"id": "s1", "durationSec": 5, "visualDescription": "城市夜景，雨水滑落玻璃"}, []
    )
    expected_prompt = (
        "城市夜景，雨水滑落玻璃。真实自然的运动节奏，避免过度平滑或机械化的动作，"
        "保持画面细节和纹理的真实感，自然的光影变化"
    )
    assert payload["input"] == {"prompt": expected_prompt}
    assert payload["parameters"] == {
        "resolution": "720P",
        "ratio": "9:16",
        "duration": 5,
        "prompt_extend": False,
    }


@pytest.mark.parametrize("input_kind", ["single-character", "shot-image", "text-only"])
async def test_wan_pipeline_selects_input_without_h3_reference_mode(input_kind):
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime

    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="一个女孩在雨夜的车站等待朋友，灯光映照她的侧脸。",
            duration_sec=30,
            mode="import_story",
        )
    )
    pid = created["project"]["id"]
    record = await pipeline._repository.get(pid)
    card = {
        "id": "c1",
        "name": "小雨",
        "appearance": "短发",
        "clothing": "蓝色外套",
        "personality": "沉稳",
        "voice": {},
        "referenceImageUrl": "https://assets.test/c.png",
    }
    await pipeline._character_repository.save(card)
    record.project["script"] = {
        "scenes": [{"id": "scene1", "shotIds": ["s1"]}],
        "shots": [
            {
                "id": "s1",
                "sceneId": "scene1",
                "order": 1,
                "durationSec": 5,
                "characterIds": ["c1"],
                "generationMode": "t2va",
                "visualDescription": "雨夜等车",
            }
        ],
    }
    if input_kind == "shot-image":
        record.project["visualAssets"] = [
            {
                "id": "old-image",
                "shotId": "s1",
                "valid": True,
                "mediaType": "image",
                "sourceUrl": "https://assets.test/shot.png",
            }
        ]
    await pipeline._repository.save(record)
    bodies = []

    def handler(request):
        if request.method == "POST":
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"output": {"task_id": "v1"}})
        if "/tasks/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "output": {"task_status": "SUCCEEDED", "video_url": "https://assets.test/v.mp4"}
                },
            )
        return httpx.Response(200, content=b"video")

    pipeline.set_video_provider(
        BailianImageToVideoProvider(
            api_key="offline",
            transport=httpx.MockTransport(handler),
            generation_type="t2v" if input_kind == "text-only" else "i2v",
            model="wan2.7-t2v" if input_kind == "text-only" else "wan2.2-i2v-flash",
            resolution="720P" if input_kind == "text-only" else "480P",
        )
    )
    result = await pipeline.generate_shot_visual(
        pid, "s1", expected_version=record.project["version"]
    )
    assert result["asset"]["mediaType"] == "video"
    expected = {
        "single-character": "https://assets.test/c.png",
        "shot-image": "https://assets.test/shot.png",
        "text-only": None,
    }[input_kind]
    assert bodies[0]["input"].get("img_url") == expected
    assert "reference_images" not in bodies[0]["input"]


@pytest.mark.parametrize('custom_paths', [False, True])
async def test_video_protocol_asset_storage_and_no_key_on_download(custom_paths):
    calls = []
    stored = []
    submit = '/custom/video' if custom_paths else '/services/aigc/video-generation/video-synthesis'
    query = '/custom/jobs/{task_id}' if custom_paths else '/tasks/{task_id}'
    model = 'my-video-deployment' if custom_paths else 'wan2.2-i2v-flash'

    class Store:
        async def put_bytes(self, object_key, content, content_type):
            stored.append((object_key, content, content_type))

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert request.url.path == '/api/v1' + submit
            assert request.headers["X-DashScope-Async"] == "enable"
            body = json.loads(request.content)
            assert body['model'] == model
            assert body["input"]["img_url"] == "https://asset.test/first.png"
            assert body["parameters"]["resolution"] == "480P"
            assert body["parameters"]["duration"] == 5
            assert "first_frame_image" not in body["input"]
            assert "<Subject" not in body["input"]["prompt"]
            return httpx.Response(200, json={"output": {"task_id": "v1"}})
        if request.url.host == 'dashscope.aliyuncs.com':
            assert request.url.path == '/api/v1' + query.replace('{task_id}', 'v1')
            return httpx.Response(
                200,
                json={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "video_url": "https://asset.test/video.mp4",
                    }
                },
            )
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"offline-video")

    provider = BailianImageToVideoProvider(
        api_key="offline",
        model=model,
        submit_path=submit if custom_paths else '', query_path=query if custom_paths else '',
        resolution="480P",
        asset_store=Store(),
        transport=httpx.MockTransport(handler),
        poll_interval_seconds=0,
    )
    asset = await provider.generate(
        {
            "id": "s1",
            "firstFrameUrl": "https://asset.test/first.png",
            "durationSec": 5,
            "visualDescription": "雨夜车站",
            "action": "向前走",
        },
        [],
    )
    assert asset["mediaType"] == "video"
    assert asset["provider"] == "bailian"
    assert asset["durationSec"] == 5
    assert asset["objectKey"] == stored[0][0]
    assert len(calls) == 3


@pytest.mark.parametrize(
    "shot,error",
    [
        ({"durationSec": 5}, "VIDEO_FIRST_FRAME_REQUIRED"),
        (
            {"durationSec": 10, "firstFrameUrl": "https://asset.test/f.png"},
            "VIDEO_DURATION_INVALID",
        ),
        (
            {"durationSec": 5, "firstFrameUrl": "https://asset.test/f.mp4"},
            "REFERENCE_IMAGE_INVALID",
        ),
        (
            {
                "durationSec": 5,
                "firstFrameUrl": "https://asset.test/f.png",
                "generationMode": "ref2va",
            },
            "VIDEO_MODE_UNSUPPORTED",
        ),
    ],
)
async def test_invalid_video_input_never_submits(shot, error):
    def handler(request):
        raise AssertionError("Invalid request must not reach provider")

    provider = BailianImageToVideoProvider(
        api_key="offline", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeError, match=error):
        await provider.generate({"id": "s1", **shot}, [])


async def test_dialogue_is_included_in_prompt():
    """验证对白被包含在视频生成的 prompt 中"""
    provider = BailianImageToVideoProvider(
        api_key="offline", model="wan2.7-i2v", resolution="720P"
    )
    payload = provider._request(
        {
            "id": "s1",
            "durationSec": 5,
            "firstFrameUrl": "https://asset.test/f.png",
            "visualDescription": "女孩站在雨中",
            "dialogue": "你终于来了",
        },
        [],
    )
    assert "你终于来了" in payload["input"]["prompt"]
    assert "女孩站在雨中" in payload["input"]["prompt"]


@pytest.mark.parametrize("model", ["wan2.7-i2v", "wan2.2-i2v-flash"])
async def test_ref2va_is_rejected_before_submission(model):
    """The i2v protocol accepts keyframes, not H3-style reference images."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    provider = BailianImageToVideoProvider(
        api_key="offline", model=model, resolution="720P",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="VIDEO_MODE_UNSUPPORTED"):
        await provider.generate(
            {
                "id": "s1",
                "durationSec": 5,
                "generationMode": "ref2va",
                "referenceImages": [
                    {"url": "https://asset.test/ref1.png", "description": "角色正面"},
                    {"url": "https://asset.test/ref2.png", "description": "场景全景"},
                ],
                "visualDescription": "女孩转身离开",
            },
            [],
        )
    assert calls == []
