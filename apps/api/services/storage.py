"""Object storage.

`StorageBackend` is the only interface the rest of the engine touches, so
swapping the local dev directory for Cloudflare R2 is a config change.

Nothing here returns a permanent public URL for private objects: callers get a
key plus, when the backend supports it, a short-lived signed URL.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from app.config import Settings
from app.errors import StorageError

logger = logging.getLogger("viralcut.storage")


class StorageBackend(ABC):
    name = "abstract"

    @abstractmethod
    def put_file(self, key: str, path: str | Path, *, content_type: str | None = None) -> str: ...

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> str: ...

    @abstractmethod
    def get_file(self, key: str, dest: str | Path) -> Path: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def signed_url(self, key: str, *, expires_in: int = 3600) -> str: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    # -- conveniences -------------------------------------------------------
    def open(self, key: str) -> BinaryIO:
        raise NotImplementedError

    def copy_to_local(self, key: str, work_dir: Path) -> Path:
        """Materialise an object on local disk so FFmpeg can read it."""
        work_dir.mkdir(parents=True, exist_ok=True)
        dest = work_dir / Path(key).name
        return self.get_file(key, dest)

    @staticmethod
    def guess_content_type(key: str) -> str:
        return mimetypes.guess_type(key)[0] or "application/octet-stream"


class LocalStorage(StorageBackend):
    """Filesystem backend for development and single-node deployments.

    Signed URLs are HMAC-signed, time-limited paths served by the web app, so
    the dev path exercises the same access-control shape as R2.
    """

    name = "local"

    def __init__(self, root: Path, *, public_base_url: str = "", signing_key: str = "") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url.rstrip("/")
        self.signing_key = signing_key

    def _abs(self, key: str) -> Path:
        key = key.lstrip("/")
        candidate = (self.root / key).resolve()
        # Refuse path traversal (`../../etc/passwd`).
        if not str(candidate).startswith(str(self.root.resolve())):
            raise StorageError("Invalid storage key.", details={"key": key})
        return candidate

    def put_file(self, key: str, path: str | Path, *, content_type: str | None = None) -> str:
        dest = self._abs(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        return key

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        dest = self._abs(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return key

    def get_file(self, key: str, dest: str | Path) -> Path:
        src = self._abs(key)
        if not src.exists():
            raise StorageError("Object not found in storage.", details={"key": key})
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() != src.resolve():
            shutil.copyfile(src, dest)
        return dest

    def exists(self, key: str) -> bool:
        return self._abs(key).exists()

    def delete(self, key: str) -> None:
        target = self._abs(key)
        if target.exists():
            target.unlink()

    def size(self, key: str) -> int:
        target = self._abs(key)
        return target.stat().st_size if target.exists() else 0

    def signed_url(self, key: str, *, expires_in: int = 3600) -> str:
        if not self.public_base_url:
            return f"/api/media/{key}"
        expires = int(time.time()) + expires_in
        if not self.signing_key:
            return f"{self.public_base_url}/{key}?expires={expires}"
        import hashlib
        import hmac

        signature = hmac.new(
            self.signing_key.encode(), f"{key}:{expires}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        return f"{self.public_base_url}/{key}?expires={expires}&sig={signature}"


class S3Storage(StorageBackend):
    """Cloudflare R2 (or any S3-compatible bucket)."""

    name = "s3"

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_url: str = "",
        endpoint: str = "",
        region: str = "auto",
    ) -> None:
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as err:  # pragma: no cover - optional dependency
            raise StorageError(
                "S3 storage is configured but boto3 is not installed. Run `pip install boto3`."
            ) from err

        self.bucket = bucket
        self.public_url = public_url.rstrip("/")
        self._boto3 = boto3
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put_file(self, key: str, path: str | Path, *, content_type: str | None = None) -> str:
        self._client.upload_file(
            str(path), self.bucket, key, ExtraArgs={"ContentType": content_type or self.guess_content_type(key)}
        )
        return key

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type or self.guess_content_type(key),
        )
        return key

    def get_file(self, key: str, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(self.bucket, key, str(dest))
        except self._client.exceptions.NoSuchKey as err:  # pragma: no cover
            raise StorageError("Object not found in storage.", details={"key": key}) from err
        return dest

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def size(self, key: str) -> int:
        try:
            return int(self._client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except Exception:
            return 0

    def signed_url(self, key: str, *, expires_in: int = 3600) -> str:
        from botocore.exceptions import ClientError

        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except ClientError as err:  # pragma: no cover
            raise StorageError("Could not sign a URL for that object.") from err

    def iter_objects(self, prefix: str) -> Iterator[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield obj["Key"]


def create_storage(settings: Settings | None = None) -> StorageBackend:
    settings = settings or _settings()
    if settings.storage_backend == "s3":
        if not settings.r2_configured:
            raise StorageError(
                "STORAGE_BACKEND=s3 but the R2 credentials are incomplete. "
                "Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME."
            )
        return S3Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket_name,
            public_url=settings.r2_public_url,
            endpoint=settings.r2_endpoint,
        )
    return LocalStorage(
        settings.storage_local_dir,
        public_base_url=settings.r2_public_url,
        signing_key=os.environ.get("MEDIA_URL_SIGNING_KEY", ""),
    )


def _settings() -> Settings:
    from app.config import get_settings

    return get_settings()


def key_for(*parts: str) -> str:
    """Build an object key. Kept in one place so cleanup jobs can glob by prefix."""
    return "/".join(str(p).strip("/") for p in parts if str(p).strip("/"))
