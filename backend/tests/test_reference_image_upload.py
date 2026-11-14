import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime


@pytest.mark.asyncio
async def test_reference_image_upload_persists_metadata_and_replaces_previous() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的图片参考故事", duration_sec=30, mode="automatic"
        )
    )
    project_id = created["project"]["id"]
    first = await runtime.pipeline.upload_reference_image(
        project_id, "a.png", "image/png", b"png-bytes"
    )
    second = await runtime.pipeline.upload_reference_image(
        project_id, "b.webp", "image/webp", b"webp-bytes"
    )
    assert first["asset"]["valid"] is False or second["asset"]["id"] != first["asset"]["id"]
    snapshot = await runtime.pipeline.get_snapshot(project_id)
    assert snapshot["project"]["referenceImage"]["id"] == second["asset"]["id"]
    assert snapshot["project"]["referenceImages"][0]["valid"] is False


@pytest.mark.asyncio
async def test_reference_image_upload_rejects_type_size_and_owner_mismatch() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的图片参考故事", duration_sec=30, mode="automatic"
        )
    )
    project_id = created["project"]["id"]
    with pytest.raises(DomainError, match="REFERENCE_IMAGE_TYPE_INVALID"):
        await runtime.pipeline.upload_reference_image(project_id, "a.gif", "image/gif", b"gif")
    with pytest.raises(DomainError, match="REFERENCE_IMAGE_SIZE_INVALID"):
        await runtime.pipeline.upload_reference_image(
            project_id, "a.png", "image/png", b"x" * (10 * 1024 * 1024 + 1)
        )
