from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime


async def test_confirmed_script_is_available_as_an_immutable_version() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的历史剧本故事", duration_sec=60, mode="guided"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_script(project_id)
    snapshot = await runtime.pipeline.get_snapshot(project_id)
    await runtime.pipeline.confirm_script(
        project_id, expected_version=snapshot["project"]["version"]
    )

    versions = await runtime.pipeline.list_script_versions(project_id)

    assert len(versions) == 1
    assert versions[0]["projectId"] == project_id
    assert versions[0]["script"]["title"]


async def test_project_duplicate_has_independent_identity() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的可复制故事", duration_sec=60, mode="guided"
        )
    )

    duplicate = await runtime.pipeline.duplicate_project(created["project"]["id"])

    assert duplicate["project"]["id"] != created["project"]["id"]
    assert duplicate["project"]["input"] == created["project"]["input"]


async def test_generation_session_snapshot_tracks_mode_and_stage() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的会话故事", duration_sec=60, mode="automatic"
        )
    )

    session = await runtime.pipeline.get_generation_session(created["project"]["id"])

    assert session["projectId"] == created["project"]["id"]
    assert session["mode"] == "automatic"
    assert session["stage"] == "story"
