"""S3 multipart upload for export streaming (RustFS / MinIO compatible)."""

from __future__ import annotations

import logging
from typing import Any

import aioboto3

log = logging.getLogger(__name__)

# S3 multipart parts must be >= 5 MiB except the last part.
_MIN_PART_BYTES = 5 * 1024 * 1024


class ExportS3Writer:
    """Buffers export bytes and uploads via multipart when the object is large."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region_name: str,
        bucket: str,
        key: str,
        part_size: int = 8 * 1024 * 1024,
        upload_id: str | None = None,
        completed_parts: list[dict[str, Any]] | None = None,
        next_part_number: int = 1,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region_name = region_name
        self._bucket = bucket
        self._key = key
        self._part_size = max(part_size, _MIN_PART_BYTES)
        self._session = aioboto3.Session()
        self._client: Any = None
        self._upload_id = upload_id
        self._parts: list[dict[str, Any]] = list(completed_parts or [])
        self._buf = bytearray()
        self._part_no = next_part_number
        self._closed = False

    @property
    def upload_id(self) -> str | None:
        return self._upload_id

    @property
    def completed_parts(self) -> list[dict[str, Any]]:
        return list(self._parts)

    async def __aenter__(self) -> ExportS3Writer:
        self._client = await self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            region_name=self._region_name,
        ).__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            if exc:
                await self._abort()
            await self._client.__aexit__(*exc)
        self._closed = True

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("ExportS3Writer is closed")
        if not data:
            return
        self._buf.extend(data)
        while len(self._buf) >= self._part_size:
            chunk = bytes(self._buf[: self._part_size])
            del self._buf[: self._part_size]
            await self._upload_part(chunk)

    async def complete(self) -> None:
        if self._closed:
            raise RuntimeError("ExportS3Writer is closed")
        if self._upload_id is None:
            body = bytes(self._buf)
            self._buf.clear()
            assert self._client is not None
            await self._client.put_object(Bucket=self._bucket, Key=self._key, Body=body)
        else:
            if self._buf:
                await self._upload_part(bytes(self._buf))
                self._buf.clear()
            assert self._client is not None
            await self._client.complete_multipart_upload(
                Bucket=self._bucket,
                Key=self._key,
                UploadId=self._upload_id,
                MultipartUpload={"Parts": self._parts},
            )
        self._closed = True

    async def _upload_part(self, body: bytes) -> None:
        if not body:
            return
        assert self._client is not None
        if self._upload_id is None:
            created = await self._client.create_multipart_upload(
                Bucket=self._bucket,
                Key=self._key,
            )
            self._upload_id = created["UploadId"]
        resp = await self._client.upload_part(
            Bucket=self._bucket,
            Key=self._key,
            PartNumber=self._part_no,
            UploadId=self._upload_id,
            Body=body,
        )
        self._parts.append({"ETag": resp["ETag"], "PartNumber": self._part_no})
        self._part_no += 1

    async def _abort(self) -> None:
        if self._upload_id is None or self._client is None:
            return
        try:
            await self._client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=self._key,
                UploadId=self._upload_id,
            )
        except Exception:
            log.exception("abort multipart upload failed for %s", self._key)
