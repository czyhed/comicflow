import os

import pytest
from botocore.exceptions import ClientError
from comicflow.providers.s3 import (
    S3AssetStore,
    create_configured_asset_store,
    rewrite_presigned_host,
)

SIGNED = (
    "http://object-store:9000/comicflow/exports/video.mp4"
    "?AWSAccessKeyId=comicflow&Signature=abc123%3D&Expires=1788689357"
)


@pytest.mark.parametrize(
    ("public_endpoint", "expected_prefix"),
    [
        ("http://127.0.0.1:19000", "http://127.0.0.1:19000/comicflow/exports/video.mp4?"),
        ("https://s3.example.com", "https://s3.example.com/comicflow/exports/video.mp4?"),
        ("127.0.0.1:19000", "http://127.0.0.1:19000/comicflow/exports/video.mp4?"),
    ],
)
def test_rewrite_presigned_host_replaces_scheme_and_netloc(
    public_endpoint: str, expected_prefix: str
) -> None:
    rewritten = rewrite_presigned_host(SIGNED, public_endpoint)
    assert rewritten.startswith(expected_prefix)
    assert "Signature=abc123%3D" in rewritten


@pytest.mark.parametrize("public_endpoint", [None, ""])
def test_rewrite_keeps_url_without_public_endpoint(public_endpoint: str | None) -> None:
    assert rewrite_presigned_host(SIGNED, public_endpoint) == SIGNED


def test_configured_store_reads_optional_public_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    required = {
        "S3_ENDPOINT": "http://object-store:9000",
        "S3_BUCKET": "comicflow",
        "S3_ACCESS_KEY_ID": "comicflow",
        "S3_SECRET_ACCESS_KEY": "secret",
    }
    for name, value in required.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("S3_PUBLIC_ENDPOINT", "http://127.0.0.1:19000")
    store = create_configured_asset_store()
    assert isinstance(store, S3AssetStore)
    assert store.endpoint_url == "http://object-store:9000"
    assert store.public_endpoint == "http://127.0.0.1:19000"


def test_configured_store_defaults_public_endpoint_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "S3_ENDPOINT": "http://object-store:9000",
        "S3_BUCKET": "comicflow",
        "S3_ACCESS_KEY_ID": "comicflow",
        "S3_SECRET_ACCESS_KEY": "secret",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("S3_PUBLIC_ENDPOINT", raising=False)
    assert os.getenv("S3_PUBLIC_ENDPOINT") is None
    store = create_configured_asset_store()
    assert store.public_endpoint is None


@pytest.mark.parametrize('code', [None, '404', 'NoSuchKey', '403', '500'])
async def test_head_distinguishes_absent_object_from_storage_errors(monkeypatch, code):
    store = S3AssetStore('http://storage.invalid', 'us-east-1', 'test', 'key', 'secret')

    class Client:
        def head_object(self, **params):
            assert params == {'Bucket': 'test', 'Key': 'old.mp4'}
            if code:
                raise ClientError({'Error': {'Code': code}}, 'HeadObject')

    monkeypatch.setattr(S3AssetStore, '_client', lambda self: Client())
    if code in {'403', '500'}:
        with pytest.raises(ClientError):
            await store.exists('old.mp4')
    else:
        assert await store.exists('old.mp4') is (code is None)


async def test_download_signature_contains_attachment_and_expiry(monkeypatch):
    store = S3AssetStore('http://storage.invalid', 'us-east-1', 'test', 'key', 'secret')

    class Client:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            assert operation == 'get_object'
            assert Params == {'Bucket': 'test', 'Key': 'old.mp4',
                              'ResponseContentDisposition':
                                  "attachment; filename*=UTF-8''video%20old.mp4"}
            assert ExpiresIn == 900
            return SIGNED

    monkeypatch.setattr(S3AssetStore, '_client', lambda self: Client())
    assert await store.presigned_download_url('old.mp4', 'video old.mp4') == SIGNED
