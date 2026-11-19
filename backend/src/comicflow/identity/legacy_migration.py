"""Plan and apply the legacy ComicFlow project-owner migration.

Old ComicFlow projects were created against a browser-local guest id (``gst_*``)
or a magic-link identity (``user_*``). The shared ShiploadAI account is
``password:xshipai``; with a shared account model every old project should be
owned by that identity so a new browser can open it.

The planner is read-only. Callers must opt in to writes explicitly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from comicflow.domain.models import ProjectRecord

DEFAULT_TARGET_OWNER = "password:xshipai"
DEFAULT_LEGACY_PREFIXES: tuple[str, ...] = ("gst_", "user_")


class ProjectOwnerRepository(Protocol):
    async def list_projects(self) -> list[ProjectRecord]: ...

    async def save(self, record: ProjectRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class OwnerChange:
    project_id: str
    previous_owner: str | None
    new_owner: str


@dataclass(slots=True)
class MigrationReport:
    target_owner: str
    dry_run: bool
    scanned: int = 0
    already_target: int = 0
    eligible: int = 0
    skipped: int = 0
    applied: int = 0
    failed: list[dict[str, str]] = field(default_factory=list)
    owners: dict[str, int] = field(default_factory=dict)
    changes: list[OwnerChange] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "targetOwner": self.target_owner,
            "dryRun": self.dry_run,
            "scanned": self.scanned,
            "alreadyTarget": self.already_target,
            "eligible": self.eligible,
            "skipped": self.skipped,
            "applied": self.applied,
            "owners": dict(sorted(self.owners.items())),
            "changes": [
                {
                    "projectId": change.project_id,
                    "previousOwner": change.previous_owner,
                    "newOwner": change.new_owner,
                }
                for change in self.changes
            ],
            "failed": self.failed,
        }


def is_legacy_owner(
    owner: str | None,
    *,
    target_owner: str,
    legacy_prefixes: tuple[str, ...] = DEFAULT_LEGACY_PREFIXES,
    include_unowned: bool = True,
) -> bool:
    """Whether an existing owner should be replaced by the shared account."""
    if owner == target_owner:
        return False
    if owner is None:
        return include_unowned
    return any(owner.startswith(prefix) for prefix in legacy_prefixes)


async def migrate_legacy_owners(
    repository: ProjectOwnerRepository,
    *,
    target_owner: str = DEFAULT_TARGET_OWNER,
    legacy_prefixes: tuple[str, ...] = DEFAULT_LEGACY_PREFIXES,
    include_unowned: bool = True,
    dry_run: bool = True,
) -> MigrationReport:
    """Report legacy owners and, unless ``dry_run``, move them to ``target_owner``.

    Every record is fetched first so the report is complete before any write.
    A write keeps the previous owner in ``legacyOwnerUserId`` for traceability.
    """
    if not target_owner or target_owner != target_owner.strip():
        raise ValueError("TARGET_OWNER_INVALID")

    report = MigrationReport(target_owner=target_owner, dry_run=dry_run)
    records = await repository.list_projects()
    owner_counts: Counter[str] = Counter()
    eligible: list[ProjectRecord] = []

    for record in records:
        report.scanned += 1
        owner = record.project.get("ownerUserId")
        owner_key = "<unowned>" if owner is None else str(owner)
        owner_counts[owner_key] += 1
        if owner == target_owner:
            report.already_target += 1
            continue
        if not is_legacy_owner(
            owner if owner is None else str(owner),
            target_owner=target_owner,
            legacy_prefixes=legacy_prefixes,
            include_unowned=include_unowned,
        ):
            report.skipped += 1
            continue
        eligible.append(record)
        report.eligible += 1
        report.changes.append(
            OwnerChange(
                project_id=str(record.project.get("id", "")),
                previous_owner=None if owner is None else str(owner),
                new_owner=target_owner,
            )
        )

    report.owners = dict(owner_counts)
    if dry_run:
        return report

    for record in eligible:
        project = record.project
        previous_owner = project.get("ownerUserId")
        if previous_owner is not None and previous_owner != target_owner:
            project.setdefault("legacyOwnerUserId", previous_owner)
        project["ownerUserId"] = target_owner
        try:
            await repository.save(record)
        except Exception as error:  # Report and keep going; the caller decides to retry.
            report.failed.append(
                {
                    "projectId": str(project.get("id", "")),
                    "error": type(error).__name__,
                }
            )
            continue
        report.applied += 1

    return report
