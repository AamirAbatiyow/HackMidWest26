"""S3-compatible object storage client with local-disk fallback.

Reads credentials from environment variables with fallback naming:
  - OBJ_ACCESS_KEY or LINODE_OBJ_ACCESS_KEY (preferred: OBJ_*)
  - OBJ_SECRET_KEY or LINODE_OBJ_SECRET_KEY
  - OBJ_ENDPOINT, OBJ_BUCKET, OBJ_REGION

When credentials are unset, stores files locally under data_dir/objects/.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

log = logging.getLogger(__name__)


def _env(primary: str, fallback: str | None = None) -> str:
    """Read an env var, with optional fallback name."""
    val = os.environ.get(primary, "")
    if not val and fallback:
        val = os.environ.get(fallback, "")
    return val


@dataclass
class ObjectStoreConfig:
    """Configuration for the object store, read from environment or passed explicitly."""

    endpoint: str = ""
    bucket: str = ""
    region: str = ""
    access_key: str = ""
    secret_key: str = ""
    data_dir: Path = field(default_factory=lambda: Path("data"))

    @classmethod
    def from_env(cls, data_dir: Path | None = None) -> "ObjectStoreConfig":
        """Load config from environment variables.

        Accepts both OBJ_* (preferred) and LINODE_OBJ_* naming conventions.
        """
        return cls(
            endpoint=_env("OBJ_ENDPOINT"),
            bucket=_env("OBJ_BUCKET"),
            region=_env("OBJ_REGION"),
            access_key=_env("OBJ_ACCESS_KEY", "LINODE_OBJ_ACCESS_KEY"),
            secret_key=_env("OBJ_SECRET_KEY", "LINODE_OBJ_SECRET_KEY"),
            data_dir=data_dir or Path(_env("VOUCH_DATA_DIR") or "data"),
        )

    @property
    def is_configured(self) -> bool:
        """True if all required S3 settings are present."""
        return all([self.endpoint, self.bucket, self.access_key, self.secret_key])


class ObjectStore:
    """S3-compatible object storage client with local-disk fallback.

    Use for invoice files, attachments, and audit artifacts keyed by invoice id.
    Falls back to local disk when OBJ_* credentials are not set, so tests and CI
    run without cloud access.
    """

    def __init__(self, config: ObjectStoreConfig | None = None) -> None:
        self.config = config or ObjectStoreConfig.from_env()
        self.backend = "local"
        self._s3 = None
        self.local_dir = self.config.data_dir / "objects"

        if self.config.is_configured:
            try:
                import boto3

                endpoint = self.config.endpoint
                if not endpoint.startswith("http"):
                    endpoint = f"https://{endpoint}"

                self._s3 = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    aws_access_key_id=self.config.access_key,
                    aws_secret_access_key=self.config.secret_key,
                    region_name=self.config.region or None,
                )
                self.backend = "object-storage"
                log.info(
                    "ObjectStore: using S3-compatible storage at %s/%s",
                    endpoint,
                    self.config.bucket,
                )
            except Exception as exc:
                log.warning(
                    "ObjectStore: S3 configured but boto3 failed (%s); using local disk",
                    exc,
                )

        if self.backend == "local":
            self.local_dir.mkdir(parents=True, exist_ok=True)
            log.info("ObjectStore: using local disk at %s", self.local_dir)

    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an object and return its URI (s3:// or local path)."""
        if isinstance(data, bytes):
            body = data
        else:
            body = data.read()

        if self._s3 is not None:
            self._s3.put_object(
                Bucket=self.config.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
            return f"s3://{self.config.bucket}/{key}"

        path = self.local_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return str(path)

    def get(self, key: str) -> bytes | None:
        """Retrieve an object by key, or None if not found."""
        if self._s3 is not None:
            try:
                resp = self._s3.get_object(Bucket=self.config.bucket, Key=key)
                return resp["Body"].read()
            except self._s3.exceptions.NoSuchKey:
                return None
            except Exception:
                return None

        path = self.local_dir / key
        if path.exists():
            return path.read_bytes()
        return None

    def exists(self, key: str) -> bool:
        """Check if an object exists."""
        if self._s3 is not None:
            try:
                self._s3.head_object(Bucket=self.config.bucket, Key=key)
                return True
            except Exception:
                return False

        return (self.local_dir / key).exists()

    def delete(self, key: str) -> bool:
        """Delete an object. Returns True if deleted, False if not found."""
        if self._s3 is not None:
            try:
                self._s3.delete_object(Bucket=self.config.bucket, Key=key)
                return True
            except Exception:
                return False

        path = self.local_dir / key
        if path.exists():
            path.unlink()
            return True
        return False

    def list_prefix(self, prefix: str) -> list[str]:
        """List all keys with the given prefix."""
        if self._s3 is not None:
            try:
                resp = self._s3.list_objects_v2(
                    Bucket=self.config.bucket,
                    Prefix=prefix,
                )
                return [obj["Key"] for obj in resp.get("Contents", [])]
            except Exception:
                return []

        keys = []
        prefix_path = self.local_dir / prefix
        base = prefix_path.parent if not prefix_path.is_dir() else prefix_path
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(self.local_dir)
                    if str(rel).startswith(prefix):
                        keys.append(str(rel))
        return keys

    def ping(self) -> tuple[bool, str]:
        """Health check: returns (ok, description)."""
        if self._s3 is None:
            return True, f"local disk {self.local_dir} (OBJ_* not set)"
        try:
            self._s3.head_bucket(Bucket=self.config.bucket)
            return True, f"bucket {self.config.bucket} @ {self.config.endpoint}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:100]}"

    # --- Convenience methods for invoice-related storage ---

    @staticmethod
    def invoice_key(invoice_id: str, filename: str, sha256: str | None = None) -> str:
        """Generate a storage key for an invoice file.

        Format: invoices/{invoice_id}/{hash_prefix}{suffix}
        """
        suffix = Path(filename).suffix.lower() or ".bin"
        if sha256:
            return f"invoices/{invoice_id}/{sha256[:16]}{suffix}"
        return f"invoices/{invoice_id}/{filename}"

    @staticmethod
    def attachment_key(invoice_id: str, filename: str, data: bytes) -> str:
        """Generate a storage key for an attachment, using content hash."""
        sha = hashlib.sha256(data).hexdigest()
        suffix = Path(filename).suffix.lower() or ".bin"
        return f"attachments/{invoice_id}/{sha[:16]}{suffix}"

    @staticmethod
    def audit_key(invoice_id: str, artifact_name: str) -> str:
        """Generate a storage key for an audit artifact."""
        return f"audit/{invoice_id}/{artifact_name}"

    def put_invoice(
        self,
        invoice_id: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an original invoice file."""
        sha = hashlib.sha256(data).hexdigest()
        key = self.invoice_key(invoice_id, filename, sha)
        return self.put(key, data, content_type)

    def put_attachment(
        self,
        invoice_id: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an attachment."""
        key = self.attachment_key(invoice_id, filename, data)
        return self.put(key, data, content_type)

    def put_audit_artifact(
        self,
        invoice_id: str,
        artifact_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an audit artifact (e.g., LIME explanation, policy trace)."""
        key = self.audit_key(invoice_id, artifact_name)
        return self.put(key, data, content_type)

    def get_invoice_files(self, invoice_id: str) -> list[str]:
        """List all files for an invoice."""
        return self.list_prefix(f"invoices/{invoice_id}/")

    def get_attachments(self, invoice_id: str) -> list[str]:
        """List all attachments for an invoice."""
        return self.list_prefix(f"attachments/{invoice_id}/")

    def get_audit_artifacts(self, invoice_id: str) -> list[str]:
        """List all audit artifacts for an invoice."""
        return self.list_prefix(f"audit/{invoice_id}/")
