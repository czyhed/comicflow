"""Safety checks for an insert-only project transfer into an existing deployment."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from migration_tools.selected_project import (
    compare_row,
    digest,
    transfer_object,
    validate_bundle,
    validate_rows,
)


def rows():
    return {
        "project_states": [
            {
                "id": "p",
                "updated_at": "2026-10-23T00:00:00+00:00",
                "payload": {
                    "project": {
                        "id": "p",
                        "script": {"shots": [{"characterIds": ["c"]}]},
                        "generationSession": {"status": "ready"},
                    },
                    "jobs": [],
                },
            }
        ],
        "characters": [
            {
                "id": "c",
                "updated_at": "2026-10-23T00:00:00+00:00",
                "payload": {"id": "c", "projectId": "p"},
            }
        ],
        "image_generation_jobs": [],
        "video_generation_jobs": [
            {
                "id": "j",
                "project_id": "p",
                "operation_key": "op",
                "active_slot": None,
                "revision": 2,
                "payload": {
                    "id": "j",
                    "projectId": "p",
                    "operationKey": "op",
                    "status": "succeeded",
                    "leaseUntil": 0,
                },
            }
        ],
    }


def test_selected_rows_keep_identity_and_reject_unrelated_data():
    data = rows()
    assert validate_rows(data, "p") == set()
    data["characters"][0]["payload"]["projectId"] = "other"
    # A referenced cross-project card is allowed unchanged.
    assert validate_rows(data, "p") == set()
    data["characters"].append({"id": "unrelated", "payload": {"id": "unrelated"}})
    with pytest.raises(ValueError, match="CHARACTER_SCOPE"):
        validate_rows(data, "p")


@pytest.mark.parametrize(
    "change",
    [
        "queued",
        "slot",
        "lease",
        "session",
        "secret",
        "missing",
        "other-job",
        "mismatch",
        "extra-table",
    ],
)
def test_unsafe_source_is_rejected(change):
    data = rows()
    job = data["video_generation_jobs"][0]
    if change == "queued":
        job["payload"]["status"] = "unknown"
    if change == "slot":
        job["active_slot"] = "active"
    if change == "lease":
        job["payload"]["leaseUntil"] = 9999999999
    if change == "session":
        data["project_states"][0]["payload"]["project"]["generationSession"]["status"] = "running"
    if change == "secret":
        job["payload"]["apiKey"] = "should-not-transfer"
    if change == "missing":
        data["characters"] = []
    if change == "other-job":
        job["project_id"] = "other"
    if change == "mismatch":
        job["payload"]["operationKey"] = "different"
    if change == "extra-table":
        data["model_registry_versions"] = []
    with pytest.raises(ValueError):
        validate_rows(data, "p")


def test_existing_rows_are_only_reused_if_identical():
    row = rows()["characters"][0]
    assert compare_row(row, None) == "insert"
    assert compare_row(row, copy.deepcopy(row)) == "reuse"
    changed = copy.deepcopy(row)
    changed["payload"]["name"] = "remote edit"
    with pytest.raises(ValueError, match="TARGET_ROW_CONFLICT"):
        compare_row(row, changed)


def test_bundle_integrity_and_path_escape(tmp_path):
    data = rows()
    (tmp_path / "rows.json").write_text(json.dumps(data), encoding="utf-8")
    manifest = {
        "format": "comicflow-project-transfer-v1",
        "complete": True,
        "schema": "0004_image_jobs",
        "projectId": "p",
        "objects": [],
        "rowsSha256": digest(data),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_bundle(tmp_path)[1] == data
    manifest["objects"] = [{"key": "a.png", "file": "../outside", "sha256": "x", "size": 1}]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_bundle(tmp_path)
    manifest["objects"] = []
    manifest["rowsSha256"] = "changed"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="ROWS_CHECKSUM"):
        validate_bundle(tmp_path)


class Store:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.writes = []

    def get_object(self, Bucket, Key):
        import io

        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "GetObject",
            )
        from botocore.response import StreamingBody

        return {
            "Body": StreamingBody(io.BytesIO(self.objects[Key]), len(self.objects[Key])),
            "ContentLength": len(self.objects[Key]),
        }

    def put_object(self, Bucket, Key, Body, IfNoneMatch, **kwargs):
        assert IfNoneMatch == "*"
        if Key in self.objects:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        self.writes.append(Key)
        self.objects[Key] = Body.read()


def test_object_conflicts_never_overwrite_and_matching_objects_are_reused(tmp_path):
    content = b"project-media"
    path = tmp_path / "media"
    path.write_bytes(content)
    item = {
        "key": "asset.mp4",
        "file": "media",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "metadata": {},
    }
    store = Store({"asset.mp4": b"different"})
    with pytest.raises(ValueError, match="TARGET_OBJECT_CONFLICT"):
        transfer_object(store, "bucket", tmp_path, item)
    assert store.writes == [] and store.objects["asset.mp4"] == b"different"
    store = Store({})
    assert transfer_object(store, "bucket", tmp_path, item) == "insert"
    assert transfer_object(store, "bucket", tmp_path, item) == "reuse"
    assert store.writes == ["asset.mp4"]


def test_dormant_failed_session_is_preserved_without_scheduling():
    data = rows()
    session = data["project_states"][0]["payload"]["project"]["generationSession"]
    session.update(status="waiting-retry", lastError="COMPOSITION_MEDIA_UNREADABLE")
    before = copy.deepcopy(data)
    assert validate_rows(data, "p") == set()
    assert data == before


def test_source_url_is_provenance_only_when_local_object_exists():
    data = rows()
    data["project_states"][0]["payload"]["project"]["visualAssets"] = [
        {"objectKey": "saved.mp4", "sourceUrl": "https://provider.invalid/source"}
    ]
    assert validate_rows(data, "p") == {"saved.mp4"}
    del data["project_states"][0]["payload"]["project"]["visualAssets"][0]["objectKey"]
    with pytest.raises(ValueError, match="MEDIA_REFERENCE_UNRESOLVED"):
        validate_rows(data, "p")
