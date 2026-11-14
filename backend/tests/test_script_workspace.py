from copy import deepcopy

import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime


async def test_creator_can_edit_and_confirm_script_with_optimistic_versioning() -> None:
    pipeline = create_memory_runtime().pipeline
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
    edited_script = deepcopy(generated["script"])
    edited_script["scenes"][0]["title"] = "修改后的午夜车站"

    edited = await pipeline.update_script(
        project_id, edited_script, expected_version=generated["project"]["version"]
    )

    assert edited["project"]["version"] == 2
    assert edited["script"]["scenes"][0]["title"] == "修改后的午夜车站"

    with pytest.raises(DomainError, match="VERSION_CONFLICT"):
        await pipeline.update_script(project_id, edited_script, expected_version=1)

    confirmed = await pipeline.confirm_script(
        project_id, expected_version=edited["project"]["version"]
    )
    assert confirmed["project"]["stage"] == "storyboard-ready"
    assert confirmed["project"]["scriptConfirmedVersion"] == 2


async def test_creator_can_add_duplicate_reorder_and_delete_shots() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="idea",
            story="一封来自未来的信改变了整座城市的命运",
            duration_sec=60,
            mode="guided",
        )
    )
    generated = await pipeline.generate_script(created["project"]["id"])
    project_id = created["project"]["id"]

    added = await pipeline.add_shot(
        project_id,
        {
            "title": "新镜头",
            "action": "奔跑",
            "narration": "他冲向车站。",
            "emotion": "紧张",
            "shotSize": "中景",
            "durationSec": 5,
            "visualDescription": "雨中的奔跑",
        },
        expected_version=generated["project"]["version"],
    )
    copied = await pipeline.duplicate_shot(
        project_id,
        added["script"]["shots"][0]["id"],
        expected_version=added["project"]["version"],
    )
    reversed_ids = [shot["id"] for shot in reversed(copied["script"]["shots"])]
    reordered = await pipeline.reorder_shots(
        project_id, reversed_ids, expected_version=copied["project"]["version"]
    )
    deleted = await pipeline.delete_shot(
        project_id,
        reordered["script"]["shots"][0]["id"],
        expected_version=reordered["project"]["version"],
    )

    assert len(deleted["script"]["shots"]) == 10
    assert [shot["order"] for shot in deleted["script"]["shots"]] == list(range(1, 11))
