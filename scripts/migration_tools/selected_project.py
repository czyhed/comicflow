"""Insert-only transfer of one project. No application runtime, models or queues."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from botocore.exceptions import ClientError
from dotenv import dotenv_values

from .bundle import checked_file, file_hash, write_json
from .inventory import SCHEMA, connect, digest, media_references, s3
from .projects import character_ids

TABLES = ("project_states", "characters", "image_generation_jobs", "video_generation_jobs")
JOB_TERMINAL = {"succeeded", "failed", "cancelled"}
LEGACY_TERMINAL = JOB_TERMINAL | {"stale", "completed"}
SECRET_FIELDS = {
    "apikey",
    "apikeyencrypted",
    "password",
    "authorization",
    "accesskey",
    "secretkey",
    "secretaccesskey",
    "modelconfigencryptionkey",
}


def config(path):
    """Explicit existing dotenv or runtime compose file; never print its contents."""
    path = Path(path)
    if path.suffix == ".json":
        values = json.loads(path.read_text(encoding="utf-8-sig"))["services"]["api"]["environment"]
    else:
        values = dotenv_values(path)
    required = [
        "DATABASE_URL",
        "S3_ENDPOINT",
        "S3_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    ]
    if not all(isinstance(values.get(k), str) and values[k] for k in required):
        raise ValueError("CONFIG_INCOMPLETE")
    return dict(
        database_url=values["DATABASE_URL"],
        s3_endpoint=values["S3_ENDPOINT"],
        s3_bucket=values["S3_BUCKET"],
        s3_access_key=values["S3_ACCESS_KEY_ID"],
        s3_secret_key=values["S3_SECRET_ACCESS_KEY"],
        s3_region=values.get("S3_REGION") or "us-east-1",
    )


def identity(cfg):
    db = urlsplit(cfg["database_url"].replace("+asyncpg", ""))
    return digest(
        [db.hostname, db.port or 5432, db.path, cfg["s3_endpoint"].rstrip("/"), cfg["s3_bucket"]]
    )


def no_secrets(value):
    if isinstance(value, dict):
        for name, child in value.items():
            normalized = re.sub("[^a-z]", "", name.lower())
            if normalized in SECRET_FIELDS and child:
                raise ValueError("CREDENTIAL_FIELD_IN_PROJECT")
            no_secrets(child)
    elif isinstance(value, list):
        for child in value:
            no_secrets(child)


def retained_media_references(value):
    # sourceUrl records provider provenance; only an objectKey proves a retained copy.
    value = deepcopy(value)

    def visit(item):
        if isinstance(item, dict):
            if item.get("objectKey"):
                item.pop("sourceUrl", None)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return media_references(value)


def validate_rows(rows, pid):
    if set(rows) != set(TABLES) or len(rows["project_states"]) != 1:
        raise ValueError("PROJECT_SCOPE_INVALID")
    row = rows["project_states"][0]
    project = row["payload"].get("project", {})
    if row["id"] != pid or project.get("id") != pid:
        raise ValueError("PROJECT_SCOPE_INVALID")
    status = (project.get("generationSession") or {}).get("status")
    if status not in (
        None,
        "ready",
        "failed",
        "cancelled",
        "completed",
        "succeeded",
        "waiting-retry",
        "paused",
    ):
        raise ValueError("PROJECT_SESSION_NOT_IDLE")
    if any(j.get("status") not in LEGACY_TERMINAL for j in row["payload"].get("jobs", [])):
        raise ValueError("LEGACY_JOB_NOT_TERMINAL")
    refs = character_ids(row["payload"])
    for table in TABLES[2:]:
        for job in rows[table]:
            payload = job["payload"]
            if job["project_id"] != pid or payload.get("projectId") != pid:
                raise ValueError("JOB_SCOPE_INVALID")
            if job["id"] != payload.get("id") or job["operation_key"] != payload.get(
                "operationKey"
            ):
                raise ValueError("JOB_IDENTITY_MISMATCH")
            if (
                payload.get("status") not in JOB_TERMINAL
                or job.get("active_slot")
                or payload.get("leaseUntil", 0) > time.time()
            ):
                raise ValueError("JOB_NOT_TERMINAL")
            refs.update(character_ids(payload))
            if payload.get("characterId"):
                refs.add(payload["characterId"])
    cards = rows["characters"]
    ids = {c["id"] for c in cards}
    if refs - ids:
        raise ValueError("CHARACTER_REFERENCE_MISSING")
    for card in cards:
        if card["payload"].get("id") != card["id"]:
            raise ValueError("CHARACTER_IDENTITY_MISMATCH")
        if card["id"] not in refs and card["payload"].get("projectId") != pid:
            raise ValueError("CHARACTER_SCOPE_INVALID")
    for records in rows.values():
        if len({r["id"] for r in records}) != len(records):
            raise ValueError("DUPLICATE_ROW_ID")
    no_secrets(rows)
    keys, unresolved = retained_media_references(rows)
    if unresolved:
        raise ValueError("MEDIA_REFERENCE_UNRESOLVED")
    return keys


async def schema(conn):
    if await conn.fetchval("SELECT version_num FROM alembic_version") != SCHEMA:
        raise ValueError("SCHEMA_MISMATCH")


async def read_selected(conn, pid):
    row = await conn.fetchrow("SELECT * FROM project_states WHERE id=$1", pid)
    if not row:
        raise ValueError("SOURCE_PROJECT_MISSING")
    rows = {"project_states": [dict(row)]}
    refs = character_ids(row["payload"])
    for table in TABLES[2:]:
        rows[table] = [
            dict(r)
            for r in await conn.fetch(f"SELECT * FROM {table} WHERE project_id=$1 ORDER BY id", pid)
        ]
        for job in rows[table]:
            refs.update(character_ids(job["payload"]))
            if job["payload"].get("characterId"):
                refs.add(job["payload"]["characterId"])
    rows["characters"] = [
        dict(r)
        for r in await conn.fetch(
            "SELECT * FROM characters WHERE id=ANY($1::varchar[]) "
            "OR payload->>'projectId'=$2 ORDER BY id",
            sorted(refs),
            pid,
        )
    ]
    validate_rows(rows, pid)
    # A stable JSON representation also normalizes timestamp values for comparison.
    return json.loads(json.dumps(rows, default=str))


def object_info(store, bucket, key, destination=None):
    try:
        response = store.get_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise
    sha = hashlib.sha256()
    size = 0
    output = destination.open("xb") if destination else None
    try:
        for block in response["Body"].iter_chunks(1024 * 1024):
            sha.update(block)
            size += len(block)
            if output:
                output.write(block)
    finally:
        response["Body"].close()
        if output:
            output.close()
    if size != response["ContentLength"]:
        raise ValueError("OBJECT_LENGTH_MISMATCH")
    return {
        "key": key,
        "size": size,
        "sha256": sha.hexdigest(),
        "contentType": response.get("ContentType", "application/octet-stream"),
        "metadata": response.get("Metadata", {}),
    }


async def export_project(cfg, pid, root):
    root.mkdir(parents=True, exist_ok=False)
    (root / "objects").mkdir()
    conn = await connect(cfg)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            await schema(conn)
            rows = await read_selected(conn, pid)
    finally:
        await conn.close()
    keys = validate_rows(rows, pid)
    store = s3(cfg)
    objects = []
    for key in sorted(keys):
        name = "objects/" + hashlib.sha256(key.encode()).hexdigest()
        info = await asyncio.to_thread(object_info, store, cfg["s3_bucket"], key, root / name)
        if info is None:
            raise ValueError("SOURCE_OBJECT_MISSING")
        objects.append(dict(info, file=name))
    # Re-read source rows and objects, rejecting edits while the package was copied.
    conn = await connect(cfg)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            if digest(await read_selected(conn, pid)) != digest(rows):
                raise ValueError("SOURCE_CHANGED_DURING_EXPORT")
    finally:
        await conn.close()
    for item in objects:
        current = await asyncio.to_thread(object_info, store, cfg["s3_bucket"], item["key"])
        if not current or current["sha256"] != item["sha256"] or current["size"] != item["size"]:
            raise ValueError("SOURCE_OBJECT_CHANGED")
    write_json(root / "rows.json", rows)
    manifest = {
        "format": "comicflow-project-transfer-v1",
        "complete": True,
        "schema": SCHEMA,
        "projectId": pid,
        "sourceIdentity": identity(cfg),
        "createdAt": datetime.now(UTC).isoformat(),
        "rowsSha256": digest(rows),
        "objects": objects,
    }
    write_json(root / "manifest.json", manifest)
    return manifest


def validate_bundle(root):
    manifest = json.loads(checked_file(root, "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("format") != "comicflow-project-transfer-v1"
        or manifest.get("complete") is not True
        or manifest.get("schema") != SCHEMA
    ):
        raise ValueError("BUNDLE_FORMAT_INVALID")
    rows = json.loads(checked_file(root, "rows.json").read_text(encoding="utf-8"))
    if digest(rows) != manifest.get("rowsSha256"):
        raise ValueError("ROWS_CHECKSUM_MISMATCH")
    keys = validate_rows(rows, manifest["projectId"])
    objects = manifest["objects"]
    if len({o["key"] for o in objects}) != len(objects) or {o["key"] for o in objects} != keys:
        raise ValueError("OBJECT_REFERENCE_MISMATCH")
    for item in objects:
        path = checked_file(root, item["file"])
        if path.stat().st_size != item["size"] or file_hash(path) != item["sha256"]:
            raise ValueError("OBJECT_CHECKSUM_MISMATCH")
    return manifest, rows


def compare_row(source, target):
    if target is None:
        return "insert"
    target = json.loads(json.dumps(dict(target), default=str))
    if digest(source) != digest(target):
        raise ValueError("TARGET_ROW_CONFLICT")
    return "reuse"


def transfer_object(store, bucket, root, item):
    old = object_info(store, bucket, item["key"])
    if old is None:
        args = dict(
            Bucket=bucket,
            Key=item["key"],
            IfNoneMatch="*",
            ContentType=item.get("contentType", "application/octet-stream"),
            Metadata=item.get("metadata", {}),
        )
        try:
            with checked_file(root, item["file"]).open("rb") as stream:
                store.put_object(Body=stream, **args)
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise
        result = "insert"
    else:
        result = "reuse"
    current = object_info(store, bucket, item["key"])
    if not current or (current["sha256"], current["size"]) != (item["sha256"], item["size"]):
        raise ValueError("TARGET_OBJECT_CONFLICT")
    return result


async def row_plan(conn, rows):
    counts = {table: {"insert": 0, "reuse": 0} for table in TABLES}
    for table in TABLES:
        for source in rows[table]:
            target = await conn.fetchrow(f"SELECT * FROM {table} WHERE id=$1", source["id"])
            action = compare_row(source, target)
            if table in TABLES[2:]:
                operation = await conn.fetchrow(
                    f"SELECT id FROM {table} WHERE operation_key=$1", source["operation_key"]
                )
                if operation and operation["id"] != source["id"]:
                    raise ValueError("TARGET_OPERATION_CONFLICT")
            counts[table][action] += 1
    return counts


async def backup_target(conn, path):
    """Consistent logical row snapshot, not a pg_dump or a physical server backup."""
    tables = [
        r["tablename"]
        for r in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
    ]
    data = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        data[table] = [dict(r) for r in await conn.fetch(f"SELECT * FROM {quoted}")]
    value = {
        "format": "comicflow-logical-rows-v1",
        "createdAt": datetime.now(UTC).isoformat(),
        "tables": data,
        "sha256": digest(data),
    }
    write_json(path, value)
    return {table: len(records) for table, records in data.items()}


async def check_target(cfg, root):
    manifest, rows = validate_bundle(root)
    if identity(cfg) == manifest.get("sourceIdentity"):
        raise ValueError("SOURCE_AND_TARGET_IDENTICAL")
    conn = await connect(cfg)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            await schema(conn)
            plan = await row_plan(conn, rows)
    finally:
        await conn.close()
    store = s3(cfg)
    objects = {"insert": 0, "reuse": 0}
    for item in manifest["objects"]:
        current = await asyncio.to_thread(object_info, store, cfg["s3_bucket"], item["key"])
        if current and (current["sha256"], current["size"]) != (item["sha256"], item["size"]):
            raise ValueError("TARGET_OBJECT_CONFLICT")
        objects["reuse" if current else "insert"] += 1
    return {
        "targetIdentity": identity(cfg),
        "projectId": manifest["projectId"],
        "rows": plan,
        "objects": objects,
    }


async def insert_selected(conn, rows, pid):
    async with conn.transaction(isolation="serializable"):
        await conn.execute("SET LOCAL lock_timeout = '5s'")
        await conn.execute("SET LOCAL statement_timeout = '30s'")
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext($1))",
            "project-transfer:" + pid,
        )
        await schema(conn)
        await row_plan(conn, rows)
        for table in TABLES:
            for source in rows[table]:
                target = await conn.fetchrow(f"SELECT * FROM {table} WHERE id=$1", source["id"])
                if compare_row(source, target) == "reuse":
                    continue
                columns = tuple(source)
                allowed = (
                    {"id", "payload", "updated_at"}
                    if table in TABLES[:2]
                    else {
                        "id",
                        "project_id",
                        "operation_key",
                        "active_slot",
                        "revision",
                        "payload",
                    }
                )
                if set(columns) != allowed:
                    raise ValueError("ROW_COLUMNS_INVALID")
                values = [
                    datetime.fromisoformat(source[k]) if k == "updated_at" else source[k]
                    for k in columns
                ]
                placeholders = ",".join("$" + str(i + 1) for i in range(len(columns)))
                quoted = ",".join('"' + c + '"' for c in columns)
                await conn.execute(
                    f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})", *values
                )


async def import_project(cfg, root, backup_path, confirm_target):
    manifest, rows = validate_bundle(root)
    if identity(cfg) != confirm_target:
        raise ValueError("TARGET_CONFIRMATION_MISMATCH")
    await check_target(cfg, root)
    conn = await connect(cfg)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            await schema(conn)
            baseline = await backup_target(conn, backup_path)
    finally:
        await conn.close()
    store = s3(cfg)
    # Files must be available before the project becomes visible to the application.
    for item in manifest["objects"]:
        await asyncio.to_thread(transfer_object, store, cfg["s3_bucket"], root, item)
    conn = await connect(cfg)
    try:
        await insert_selected(conn, rows, manifest["projectId"])
    finally:
        await conn.close()
    result = await check_target(cfg, root)
    if any(plan["insert"] for plan in result["rows"].values()) or result["objects"]["insert"]:
        raise ValueError("POST_IMPORT_INCOMPLETE")
    result.update(completed=True, backupRowCounts=baseline, modelCalls=0)
    return result
