import pytest
from comicflow.providers.mock import MockTextProvider


@pytest.mark.asyncio
async def test_mock_scripts_are_story_conditioned_and_scale_with_duration() -> None:
    provider = MockTextProvider()
    short = await provider.generate_script("海边灯塔的守夜人等待失联船员", "p1", 30)
    long = await provider.generate_script("城市记者追查失踪的姐姐", "p2", 90)

    # Extract content from envelope
    short_content = short["content"]
    long_content = long["content"]

    assert short_content["title"] != long_content["title"]
    assert len(short_content["scenes"]) == 2
    assert len(short_content["shots"]) == 6
    assert len(long_content["scenes"]) == 4
    assert 10 <= len(long_content["shots"]) <= 12
    assert all("sceneId" in shot for shot in long_content["shots"])
    assert any("记者" in str(shot) or "姐姐" in str(shot) for shot in long_content["shots"])


@pytest.mark.asyncio
async def test_mock_guidance_tracks_targets_and_detailed_script_uses_answers() -> None:
    provider = MockTextProvider()
    script = await provider.generate_script("记者追查失踪的姐姐", "p1", 60)
    first = await provider.generate_guided_question("记者追查失踪的姐姐", script, [], "p1")
    assert first["questionId"]
    assert first["questionType"] == "goal"
    assert first["done"] is False

    transcript = [{"question": first["question"], "answer": "找到姐姐并揭开事故真相"}]
    second = await provider.generate_guided_question("记者追查失踪的姐姐", script, transcript, "p1")
    assert second["questionType"] != "goal"
    detailed = await provider.generate_detailed_script(
        "记者追查失踪的姐姐", script, transcript, "p1", 60
    )
    assert "找到姐姐并揭开事故真相" in str(detailed)
