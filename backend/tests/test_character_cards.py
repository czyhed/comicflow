import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import Actor, CreateProject
from comicflow.infrastructure.memory import create_memory_runtime

CHARACTER = {
    "name": "林默",
    "appearance": "黑色短发，清瘦",
    "clothing": "深灰风衣",
    "personality": "克制寡言",
    "voice": {"provider": "yun-free", "voiceId": "male-calm", "language": "zh-CN"},
}


async def test_character_cards_are_reusable_but_shot_assignments_allow_only_two() -> None:
    pipeline = create_memory_runtime().pipeline
    templates = await pipeline.list_character_templates()
    assert templates[0]["source"] == "system"

    personal = await pipeline.create_character(CHARACTER, actor=Actor.user("user-1"))
    created = await pipeline.create_project(
        CreateProject(
            input_type="idea",
            story="雨夜车站里出现一辆不存在的列车",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    generated = await pipeline.generate_script(project_id)
    shot_id = generated["script"]["shots"][0]["id"]
    guest = Actor.guest(created["guestSession"]["id"])
    temporary = await pipeline.create_character(
        {**CHARACTER, "name": "姐姐"}, actor=guest, project_id=project_id
    )
    third = await pipeline.create_character(
        {**CHARACTER, "name": "站长"}, actor=guest, project_id=project_id
    )

    assigned = await pipeline.assign_shot_characters(
        project_id,
        shot_id,
        [personal["id"], temporary["id"]],
        expected_version=generated["project"]["version"],
    )
    assert assigned["characterIds"] == [personal["id"], temporary["id"]]

    with pytest.raises(DomainError, match="SHOT_CHARACTER_LIMIT"):
        await pipeline.assign_shot_characters(
            project_id,
            shot_id,
            [personal["id"], temporary["id"], third["id"]],
            expected_version=assigned["projectVersion"],
        )

    provider_input = await pipeline.get_shot_character_input(project_id, shot_id)
    assert provider_input[0]["voice"]["voiceId"] == "male-calm"
