from __future__ import annotations

from comicflow.domain.models import ProjectRecord
from comicflow.identity.legacy_migration import (
    DEFAULT_TARGET_OWNER,
    migrate_legacy_owners,
)
from comicflow.infrastructure.memory import InMemoryProjectRepository


async def _repository() -> InMemoryProjectRepository:
    repository = InMemoryProjectRepository()
    records = [
        ProjectRecord(project={"id": "prj_guest", "ownerUserId": "gst_abc"},
                      guest_session={"id": "gst_abc"}),
        ProjectRecord(project={"id": "prj_magic", "ownerUserId": "user_creator@example.com"},
                      guest_session={}),
        ProjectRecord(project={"id": "prj_unowned", "ownerUserId": None}, guest_session={}),
        ProjectRecord(project={"id": "prj_target", "ownerUserId": DEFAULT_TARGET_OWNER},
                      guest_session={}),
        ProjectRecord(project={"id": "prj_other", "ownerUserId": "service:internal"},
                      guest_session={}),
    ]
    for record in records:
        await repository.save(record)
    return repository


async def test_dry_run_counts_legacy_owners_without_writing() -> None:
    repository = await _repository()

    report = await migrate_legacy_owners(repository, dry_run=True)

    assert report.scanned == 5
    assert report.eligible == 3
    assert report.already_target == 1
    assert report.skipped == 1
    assert report.applied == 0
    assert {change.project_id for change in report.changes} == {
        "prj_guest", "prj_magic", "prj_unowned",
    }

    untouched = await repository.get("prj_guest")
    assert untouched is not None
    assert untouched.project["ownerUserId"] == "gst_abc"


async def test_apply_moves_legacy_and_unowned_projects_and_keeps_other_owners() -> None:
    repository = await _repository()

    report = await migrate_legacy_owners(repository, dry_run=False)

    assert report.applied == 3
    assert report.failed == []

    guest = await repository.get("prj_guest")
    magic = await repository.get("prj_magic")
    unowned = await repository.get("prj_unowned")
    target = await repository.get("prj_target")
    other = await repository.get("prj_other")

    assert guest is not None and guest.project["ownerUserId"] == DEFAULT_TARGET_OWNER
    assert guest.project["legacyOwnerUserId"] == "gst_abc"
    assert magic is not None and magic.project["ownerUserId"] == DEFAULT_TARGET_OWNER
    assert magic.project["legacyOwnerUserId"] == "user_creator@example.com"
    assert unowned is not None and unowned.project["ownerUserId"] == DEFAULT_TARGET_OWNER
    assert "legacyOwnerUserId" not in unowned.project
    assert target is not None and target.project["ownerUserId"] == DEFAULT_TARGET_OWNER
    assert other is not None and other.project["ownerUserId"] == "service:internal"


async def test_skip_unowned_leaves_anonymous_projects_untouched() -> None:
    repository = await _repository()

    report = await migrate_legacy_owners(repository, include_unowned=False, dry_run=False)

    assert report.eligible == 2
    assert report.applied == 2
    unowned = await repository.get("prj_unowned")
    assert unowned is not None
    assert unowned.project["ownerUserId"] is None
