"""Attachment storage: Akamai Object Storage (S3 API) when configured, local disk otherwise."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)


class AttachmentStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = "local"
        self._s3 = None
        self.local_dir = settings.data_dir / "attachments"
        if settings.has_bucket:
            try:
                import boto3

                self._s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.obj_endpoint
                    if settings.obj_endpoint.startswith("http")
                    else f"https://{settings.obj_endpoint}",
                    aws_access_key_id=settings.obj_access_key,
                    aws_secret_access_key=settings.obj_secret_key,
                )
                self.backend = "object-storage"
            except Exception as exc:  # pragma: no cover - optional dependency
                log.warning("Object Storage configured but boto3 unavailable (%s); using local disk", exc)
        if self.backend == "local":
            self.local_dir.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if self._s3 is not None:
            self._s3.put_object(Bucket=self.settings.obj_bucket, Key=key, Body=data, ContentType=content_type)
            return f"s3://{self.settings.obj_bucket}/{key}"
        path = self.local_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def ping(self) -> tuple[bool, str]:
        if self._s3 is None:
            return False, f"local disk {self.local_dir} (OBJ_* not set)"
        try:
            self._s3.head_bucket(Bucket=self.settings.obj_bucket)
            return True, f"bucket {self.settings.obj_bucket} @ {self.settings.obj_endpoint}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:100]}"

    @staticmethod
    def key_for(payment_id: str, sha256: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".bin"
        return f"invoices/{payment_id}/{sha256[:16]}{suffix}"
