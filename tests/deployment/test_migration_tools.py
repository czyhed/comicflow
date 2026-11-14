"""Migration safeguards use synthetic inputs and never load business configuration."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from migration_tools.bundle import checked_file, require_safe_inventory
from migration_tools.inventory import classify_jobs, media_references


def test_all_retained_media_and_export_keys_are_collected():
    value = {'visualAssets': [
        {'valid': True, 'objectKey': 'current.mp4', 'downloadUrl': 'https://signed.invalid/a'},
        {'valid': False, 'objectKey': 'history.mp4', 'lastFrameObjectKey': 'tail.jpg'},
    ], 'referenceBoardCandidate': {'objectKey': 'candidate.png'},
        'exportManifest': {'objectKeys': {'video.mp4': 'export.mp4'},
                           'downloads': {'video.mp4': 'https://signed.invalid/b'}}}
    keys, unresolved = media_references(value)
    assert keys == {'current.mp4', 'history.mp4', 'tail.jpg', 'candidate.png', 'export.mp4'}
    assert unresolved == []


def test_url_only_and_local_export_are_reported_without_values():
    keys, unresolved = media_references({'referenceImageUrl': 'https://private.invalid/?secret=abc',
                                        'exportManifest': {'directory': '/private/export'}})
    assert not keys
    assert len(unresolved) == 2
    assert 'secret' not in str(unresolved) and '/private/' not in str(unresolved)


def test_unknown_job_blocks_even_without_slot_and_failed_job_is_retained():
    jobs = [{'id': 'unknown', 'active_slot': None, 'payload': {'status': 'unknown'}},
            {'id': 'failed', 'active_slot': None, 'payload': {'status': 'failed'}}]
    counts, blockers = classify_jobs(jobs)
    assert counts == {'unknown': 1, 'failed': 1}
    assert blockers == ['unknown']


def test_success_with_unreleased_slot_still_blocks():
    assert classify_jobs([{'id': 'j', 'active_slot': 'slot',
                           'payload': {'status': 'succeeded'}}])[1] == ['j']


def test_unsafe_inventory_cannot_be_backed_up():
    with pytest.raises(ValueError, match='SOURCE_NOT_READY'):
        require_safe_inventory({'blockers': ['UNKNOWN_JOB']})


@pytest.mark.parametrize('name', ['../key', '/etc/passwd', 'C:/key', 'objects/../../key'])
def test_bundle_cannot_read_outside_directory(tmp_path, name):
    with pytest.raises(ValueError, match='BUNDLE_PATH_INVALID'):
        checked_file(tmp_path, name)


def test_symlink_cannot_escape_bundle(tmp_path):
    outside = tmp_path.parent / 'outside-secret'
    outside.write_text('synthetic')
    try:
        (tmp_path / 'link').symlink_to(outside)
    except OSError:
        pytest.skip('Symlink permission unavailable on this host')
    with pytest.raises(ValueError, match='BUNDLE_PATH_INVALID'):
        checked_file(tmp_path, 'link')


def bundle_fixture(tmp_path):
    import hashlib
    import json

    from cryptography.fernet import Fernet
    from migration_tools.inventory import SCHEMA

    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    key = tmp_path / 'secret.key'
    key.write_bytes(Fernet.generate_key())
    data = b'synthetic dump'
    (bundle / 'database.dump').write_bytes(data)
    manifest = {'format': 'comicflow-backup-v1', 'complete': True, 'inventory': {
        'blockers': [], 'database': {'schema': SCHEMA, 'keyFingerprint':
                                    hashlib.sha256(key.read_bytes()).hexdigest()}, 'objects': []},
        'databaseDump': {'file': 'database.dump', 'sha256': hashlib.sha256(data).hexdigest()}}
    (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return bundle, {'key_file': str(key)}


def test_corrupt_dump_is_rejected_before_connection(tmp_path):
    from migration_tools.bundle import validate_bundle

    bundle, config = bundle_fixture(tmp_path)
    (bundle / 'database.dump').write_bytes(b'changed')
    with pytest.raises(ValueError, match='BACKUP_CHECKSUM_MISMATCH'):
        validate_bundle(bundle, config)


def test_wrong_key_is_rejected_before_connection(tmp_path):
    from cryptography.fernet import Fernet
    from migration_tools.bundle import validate_bundle

    bundle, config = bundle_fixture(tmp_path)
    Path(config['key_file']).write_bytes(Fernet.generate_key())
    with pytest.raises(ValueError, match='MODEL_KEY_MISMATCH'):
        validate_bundle(bundle, config)


async def test_mutation_requires_stopped_writers_and_explicit_target(tmp_path):
    from migration_tools.bundle import backup, restore

    with pytest.raises(ValueError, match='WRITERS_STOPPED_REQUIRED'):
        await backup({}, tmp_path / 'new', tmp_path / 'key')
    with pytest.raises(ValueError, match='TARGET_CONFIRMATION_MISMATCH'):
        await restore({'label': 'target'}, tmp_path, 'different', True)
    assert list(tmp_path.iterdir()) == []


async def test_inventory_connection_honors_same_ssl_policy_as_pg_client(monkeypatch):
    from unittest.mock import AsyncMock

    from migration_tools import inventory as module

    client = AsyncMock(return_value=AsyncMock())
    monkeypatch.setattr(module.asyncpg, 'connect', client)
    await module.connect({'database_url': 'postgresql://synthetic/db', 'pg_sslmode': 'require'})
    assert client.call_args.kwargs['ssl'] == 'require'
