from __future__ import annotations

import asyncio
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, cast

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True, slots=True)
class S3AssetStore:
    """S3-compatible asset adapter; blocking boto calls run off the event loop.

    ``public_endpoint`` rewrites the host of presigned URLs so clients outside the
    storage network (e.g. a browser on the host) can reach the bucket.
    """

    endpoint_url: str
    region_name: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    public_endpoint: str | None = None

    def _client(self) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region_name,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
        )

    async def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str:
        def upload() -> None:
            self._client().put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=content,
                ContentType=content_type,
            )

        await asyncio.to_thread(upload)
        return object_key

    async def exists(self, object_key: str) -> bool:
        def head() -> bool:
            try:
                self._client().head_object(Bucket=self.bucket, Key=object_key)
            except ClientError as error:
                code = str(error.response.get('Error', {}).get('Code'))
                if code in {'404', 'NoSuchKey', 'NotFound'}:
                    return False
                raise
            return True
        return await asyncio.to_thread(head)

    async def presigned_download_url(
        self, object_key: str, filename: str, expires_in: int = 900,
    ) -> str:
        safe_filename = urllib.parse.quote(filename, safe='')
        url = await asyncio.to_thread(lambda: self._client().generate_presigned_url(
            'get_object', Params={'Bucket': self.bucket, 'Key': object_key,
                                 'ResponseContentDisposition':
                                     f"attachment; filename*=UTF-8''{safe_filename}"},
            ExpiresIn=expires_in,
        ))
        return rewrite_presigned_host(cast(str, url), self.public_endpoint)

    async def get_bytes(self, object_key: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        def download() -> bytes:
            response = self._client().get_object(Bucket=self.bucket, Key=object_key)
            body = response['Body']
            try:
                content = bytes(body.read(max_bytes + 1))
            finally:
                body.close()
            if len(content) > max_bytes:
                raise ValueError("ASSET_TOO_LARGE")
            return content

        return await asyncio.to_thread(download)

    async def presigned_get_url(
        self, object_key: str, expires_in: int = 900, *, rewrite_public: bool = True
    ) -> str:
        url = await asyncio.to_thread(
            lambda: self._client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=expires_in,
            )
        )
        if rewrite_public:
            return rewrite_presigned_host(cast(str, url), self.public_endpoint)
        return cast(str, url)


def rewrite_presigned_host(url: str, public_endpoint: str | None) -> str:
    """Replace the scheme/host of a presigned URL with ``public_endpoint``."""
    if not public_endpoint:
        return url
    public = urllib.parse.urlparse(public_endpoint)
    scheme = public.scheme or "http"
    netloc = public.netloc or public_endpoint
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(
        (scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def create_configured_asset_store() -> S3AssetStore:
    required = ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing object storage configuration: {', '.join(missing)}")
    return S3AssetStore(
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.getenv("S3_REGION", "us-east-1"),
        bucket=os.environ["S3_BUCKET"],
        access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        public_endpoint=os.getenv("S3_PUBLIC_ENDPOINT") or None,
    )


def create_optional_asset_store() -> S3AssetStore | None:
    """Return the asset adapter when configured; assets are optional for local API startup."""
    required = ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    if any(not os.getenv(name) for name in required):
        return None
    return create_configured_asset_store()
