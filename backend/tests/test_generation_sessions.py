from collections.abc import AsyncIterator

import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.mock import MockTextProvider


class StoryTextProvider:
    async def generate_story_text(self, _story: str, _project_id: str) -> str:
        return "雨夜的末班车驶入空站，姐姐从最后一排回头。"

    async def split_script(self, _story_text: str, project_id: str) -> dict[str, object]:
        message = await MockTextProvider().split_script(_story_text, project_id)
        message["content"]["title"] = "雨夜末班车"
        return message


class StructuredStreamProvider(StoryTextProvider):
    async def stream_story_text(
        self, _story: str, _project_id: str, target_duration_sec: int = 60
    ) -> AsyncIterator[str]:
        del target_duration_sec
        yield '{"kind":"story_text","version":1,"mode":"automatic","task":"story_expansion",'
        yield '"content":{"title":"雨夜","logline":"这是一个足够长并且包含完整冲突的故事梗概",'
        yield '"characters":[{"name":"林默","goal":"找回姐姐"}],'
        yield '"setting":"暴雨夜的末班车与终点站","beats":['
        yield '{"type":"setup","text":"林默登上末班车寻找失踪姐姐，并确认自己必须查明'
        yield '旧事故真相。"},'
        yield '{"type":"development","text":"车厢里的线索不断逼迫林默面对被掩盖多年的'
        yield '事故和现实代价。"},'
        yield '{"type":"turn","text":"姐姐终于现身，并揭开自己多年躲藏背后的真正原因与关键证据。"},'
        yield '{"type":"ending","text":"林默选择带着真相走进雨幕重新开始，同时留下'
        yield '继续追查的余波。"}],'
        yield '"text":"' + ("林默在暴雨夜寻找姐姐并查明真相。" * 40) + '"}}'

    async def split_script(self, _story_text: str, project_id: str) -> dict[str, object]:
        shot_id = f"{project_id}-shot-1"
        return {
            "title": "雨夜末班车",
            "scenes": [{"id": "scene-1", "title": "车站", "shotIds": [shot_id]}],
            "shots": [
                {
                    "id": shot_id,
                    "order": 1,
                    "title": "姐姐回头",
                    "action": "回头",
                    "emotion": "惊讶",
                    "shotSize": "特写",
                    "durationSec": 30,
                    "visualDescription": "姐姐从最后一排回头",
                    "dialogue": "",
                    "narration": "雨声",
                }
            ],
        }


class CumulativeStreamProvider(StoryTextProvider):
    async def stream_story_text(
        self, _story: str, _project_id: str, target_duration_sec: int = 60
    ) -> AsyncIterator[str]:
        del target_duration_sec
        first = "第一段故事内容" * 30
        complete = first + "第二段故事内容" * 30
        yield first
        yield first
        yield complete


class MalformedStoryStreamProvider(StoryTextProvider):
    async def stream_story_text(
        self, _story: str, _project_id: str, target_duration_sec: int = 60
    ) -> AsyncIterator[str]:
        del target_duration_sec
        yield '{"kind":"story_text","version":1,"content":{"characters":{},"beats":{}}}'

    async def generate_story_text(
        self, _story: str, _project_id: str, target_duration_sec: int = 60
    ) -> str:
        del target_duration_sec
        raise AssertionError("Must not make a second model request")


class ShortStoryTextProvider:
    async def generate_story_text(self, _story: str, _project_id: str) -> str:
        return "十几个字"


class FailingStoryTextProvider:
    async def generate_story_text(self, _story: str, _project_id: str) -> str:
        raise RuntimeError("PROVIDER_RESPONSE_INVALID")


async def test_automatic_story_text_is_expanded_when_provider_returns_too_little() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(ShortStoryTextProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=60, mode="automatic"
        )
    )
    result = await runtime.pipeline.generate_story_text(created["project"]["id"])
    assert len(result["storyText"]) >= 600


async def test_story_generation_failure_stops_running_session() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(FailingStoryTextProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=60, mode="automatic"
        )
    )

    with pytest.raises(Exception, match="PROVIDER_INVALID_RESPONSE"):
        await runtime.pipeline.generate_story_text(created["project"]["id"])

    snapshot = await runtime.pipeline.get_snapshot(created["project"]["id"])
    assert snapshot["project"]["generationSession"]["stage"] == "story-failed"
    assert snapshot["project"]["generationSession"]["status"] == "failed"


class FailingGuidanceProvider:
    async def generate_guided_question(
        self, *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        raise RuntimeError("PROVIDER_TIMEOUT")

    async def generate_detailed_script(
        self, *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        raise RuntimeError("PROVIDER_RESPONSE_INVALID")


async def test_guided_question_answer_is_bounded_and_persisted() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步剧本故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)

    first = await runtime.pipeline.ask_guided_question(project_id)
    assert first["guided"]["questionCount"] == 0
    assert first["guided"]["currentQuestion"]
    second = await runtime.pipeline.answer_guided_question(project_id, "结尾要有反转")
    assert second["guided"]["questionCount"] == 1
    assert len(second["guided"]["transcript"]) == 1


async def test_guided_question_skip_records_target_and_asks_next_question() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步剧本故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)
    await runtime.pipeline.ask_guided_question(project_id)
    session = await runtime.pipeline.skip_guided_question(project_id)
    assert session["guided"]["skippedTargets"]
    assert session["guided"]["transcript"][0]["answer"] == ""
    assert session["guided"]["currentQuestion"]


async def test_mock_guidance_follows_story_closure_order() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步剧本故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)

    first = await runtime.pipeline.ask_guided_question(project_id)
    assert "主角" in first["guided"]["currentQuestion"]
    second = await runtime.pipeline.answer_guided_question(project_id, "弟弟想找回姐姐")
    assert "冲突" in second["guided"]["currentQuestion"]


async def test_guided_question_cap_marks_session_done() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步剧本故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)
    for answer in (
        "回答一",
        "回答二",
        "回答三",
        "回答四",
        "回答五",
        "回答六",
        "回答七",
        "回答八",
        "回答九",
    ):
        await runtime.pipeline.ask_guided_question(project_id)
        session = await runtime.pipeline.answer_guided_question(project_id, answer)
    assert session["guided"]["questionCount"] == 9
    assert session["guided"]["done"] is True


async def test_detailed_script_generation_updates_saved_script() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步剧本故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)
    result = await runtime.pipeline.generate_detailed_script(project_id)
    assert result["script"]["title"] == "雨夜的最后一班车"
    assert (await runtime.pipeline.get_snapshot(project_id))["project"]["version"] == 2


async def test_guidance_provider_errors_use_stable_domain_codes() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story",
            story="一个足够长的逐步剧本故事",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)
    runtime.pipeline.set_text_provider(FailingGuidanceProvider())

    with pytest.raises(Exception, match="PROVIDER_TIMEOUT"):
        await runtime.pipeline.ask_guided_question(project_id)

    with pytest.raises(Exception, match="PROVIDER_INVALID_RESPONSE"):
        await runtime.pipeline.generate_detailed_script(project_id)


async def test_legacy_guidance_count_defaults_to_transcript_length() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步剧本故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)
    record = await runtime.pipeline._repository.get(project_id)  # type: ignore[attr-defined]
    assert record is not None
    guided = record.project["generationSession"]["guided"]
    guided.pop("questionCount", None)
    guided["transcript"] = [
        {"question": f"问题 {index}", "answer": f"回答 {index}"} for index in range(9)
    ]
    await runtime.pipeline._repository.save(record)  # type: ignore[attr-defined]

    session = await runtime.pipeline.ask_guided_question(project_id)
    assert session["guided"]["questionCount"] == 9
    assert session["guided"]["done"] is True


async def test_generation_session_supports_pause_resume_cancel_and_retry() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的会话控制故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]

    assert (await runtime.pipeline.update_generation_session(project_id, "pause"))[
        "status"
    ] == "paused"
    assert (await runtime.pipeline.update_generation_session(project_id, "resume"))[
        "status"
    ] == "ready"
    retried = await runtime.pipeline.update_generation_session(project_id, "retry")
    assert retried["retryCount"] == 1
    assert (await runtime.pipeline.update_generation_session(project_id, "cancel"))[
        "status"
    ] == "cancelled"


async def test_generation_session_rejects_unknown_action() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的会话控制故事", duration_sec=60, mode="guided"
        )
    )

    with pytest.raises(Exception, match="SESSION_ACTION_INVALID"):
        await runtime.pipeline.update_generation_session(created["project"]["id"], "rewind")


async def test_generation_session_rejects_actions_after_cancel() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的会话控制故事", duration_sec=60, mode="automatic"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.update_generation_session(project_id, "cancel")
    with pytest.raises(Exception, match="SESSION_ACTION_INVALID"):
        await runtime.pipeline.update_generation_session(project_id, "retry")


async def test_retry_generation_session_is_requeued() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的会话控制故事", duration_sec=60, mode="automatic"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.update_generation_session(project_id, "pause")
    await runtime.pipeline.update_generation_session(project_id, "resume")
    retried = await runtime.pipeline.update_generation_session(project_id, "retry")
    assert retried["status"] == "ready"


async def test_automatic_generation_saves_story_text_before_script_split() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(StoryTextProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=60, mode="automatic"
        )
    )
    project_id = created["project"]["id"]

    result = await runtime.pipeline.generate_story_text(project_id)

    assert result["storyText"].startswith("雨夜的末班车驶入空站，姐姐从最后一排回头。")
    assert len(result["storyText"]) >= 600
    assert result["project"]["stage"] == "story-generated"
    assert result["project"]["script"] is None


async def test_automatic_generation_records_mode_and_stream_events() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=60, mode="automatic"
        )
    )
    project_id = created["project"]["id"]

    await runtime.pipeline.generate_story_text(project_id)

    state = await runtime.generation_state_store.get_state(project_id)
    events = await runtime.generation_state_store.read_events(project_id)
    assert state is not None
    assert state["mode"] == "automatic"
    assert state["task"] == "story_expansion"
    assert [event["data"]["type"] for event in events[:2]] == [
        "generation_started",
        "generation_delta",
    ]
    assert events[-1]["data"]["type"] == "generation_completed"


async def test_streamed_story_json_is_normalized_before_persistence() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(StructuredStreamProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=60, mode="automatic"
        )
    )

    result = await runtime.pipeline.generate_story_text(created["project"]["id"])

    assert result["storyText"].startswith("林默在暴雨夜寻找姐姐并查明真相。")
    assert not result["storyText"].startswith("{")


async def test_cumulative_stream_chunks_are_not_repeated_in_story_text() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(CumulativeStreamProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=30, mode="automatic"
        )
    )

    result = await runtime.pipeline.generate_story_text(created["project"]["id"])

    assert result["storyText"] == "第一段故事内容" * 30 + "第二段故事内容" * 30


async def test_malformed_story_stream_fails_without_non_streaming_resubmission() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(MalformedStoryStreamProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=30, mode="automatic"
        )
    )

    with pytest.raises(Exception, match="PROVIDER_INVALID_RESPONSE"):
        await runtime.pipeline.generate_story_text(created["project"]["id"])
    snapshot = await runtime.pipeline.get_snapshot(created["project"]["id"])
    assert snapshot["project"]["stage"] == "story-failed"


async def test_story_expansion_rejects_guided_projects() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步确认故事", duration_sec=60, mode="guided"
        )
    )

    with pytest.raises(Exception, match="WORKFLOW_MODE_MISMATCH"):
        await runtime.pipeline.generate_story_text(created["project"]["id"])


async def test_script_split_requires_story_text_and_persists_structured_script() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(StoryTextProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=60, mode="automatic"
        )
    )
    project_id = created["project"]["id"]

    with pytest.raises(Exception, match="STORY_TEXT_REQUIRED"):
        await runtime.pipeline.split_script(project_id)
    await runtime.pipeline.generate_story_text(project_id)
    result = await runtime.pipeline.split_script(project_id)

    assert result["script"]["title"] == "雨夜末班车"
    assert result["project"]["version"] == 3
    assert result["project"]["stage"] == "script-completed"


async def test_automatic_session_waits_at_story_generated_without_downstream_jobs() -> None:
    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(StoryTextProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动文本故事", duration_sec=60, mode="automatic"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_story_text(project_id)

    session = await runtime.pipeline.advance_generation_session(project_id)
    snapshot = await runtime.pipeline.get_snapshot(project_id)

    assert session["stage"] == "story-generated"
    assert session["status"] == "ready"
    assert snapshot["jobs"] == []


async def test_automatic_session_advances_each_stage_and_queues_composition() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story",
            story="暴雨夜的末班车驶入车站，姐姐从最后一排回头",
            duration_sec=60,
            mode="automatic",
        )
    )
    project_id = created["project"]["id"]

    await runtime.pipeline.generate_story_text(project_id)
    await runtime.pipeline.split_script(project_id)
    assert (await runtime.pipeline.get_generation_session(project_id))[
        "stage"
    ] == "script-completed"

    assert (await runtime.pipeline.advance_generation_session(project_id))[
        "stage"
    ] == "storyboard-ready"
    shots = (await runtime.pipeline.get_snapshot(project_id))['script']['shots']
    for shot in shots:
        paused = await runtime.pipeline.advance_generation_session(project_id)
        assert paused['status'] == 'paused'
        assert paused['waitingShotId'] == shot['id']
        await runtime.pipeline.adopt_video_job(project_id, paused['waitingJobId'])
        await runtime.pipeline.update_generation_session(project_id, 'resume')
    checkpoint = await runtime.pipeline.advance_generation_session(project_id)
    assert checkpoint['stage'] == 'visual-completed'
    assert (await runtime.pipeline.advance_generation_session(project_id))[
        "stage"
    ] == "audio-completed"
    checkpoint = await runtime.pipeline.advance_generation_session(project_id)
    assert checkpoint["stage"] == "composition-queued"

    snapshot = await runtime.pipeline.get_snapshot(project_id)
    assert snapshot["jobs"][0]["type"] == "composition"
    assert snapshot["jobs"][0]["status"] == "queued"


async def test_automatic_session_marks_exported_after_composition_succeeds() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story",
            story="暴雨夜的末班车驶入车站，姐姐从最后一排回头",
            duration_sec=60,
            mode="automatic",
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_story_text(project_id)
    await runtime.pipeline.split_script(project_id)
    await runtime.pipeline.advance_generation_session(project_id)
    shots = (await runtime.pipeline.get_snapshot(project_id))['script']['shots']
    for shot in shots:
        paused = await runtime.pipeline.advance_generation_session(project_id)
        assert paused['status'] == 'paused' and paused['waitingShotId'] == shot['id']
        await runtime.pipeline.adopt_video_job(project_id, paused['waitingJobId'])
        await runtime.pipeline.update_generation_session(project_id, 'resume')
    for _ in range(3):
        await runtime.pipeline.advance_generation_session(project_id)

    job_id = (await runtime.pipeline.get_snapshot(project_id))["jobs"][0]["id"]
    await runtime.pipeline.run_job(job_id)
    session = await runtime.pipeline.advance_generation_session(project_id)
    assert session["stage"] == "exported"
    assert session["status"] == "completed"
