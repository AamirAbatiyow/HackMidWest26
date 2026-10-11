"""Thin wrapper over boto3 S3 for Akamai Object Storage (S3-compatible), SeaweedFS (local), and MinIO."""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from hm_core.errors import NotFoundError
from hm_storage.settings import StorageSettings, get_storage_settings


def make_s3_client(settings: StorageSettings | None = None, endpoint_url: str | None = None) -> Any:
    s = settings or get_storage_settings()
    access = s.object_storage_access_key.get_secret_value() or None
    secret = s.object_storage_secret_key.get_secret_value() or None
    return boto3.client(
        "s3",
        endpoint_url=(endpoint_url if endpoint_url is not None else s.object_storage_endpoint) or None,
        region_name=s.object_storage_region,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


class ObjectStore:
    def __init__(
        self, bucket: str | None = None, client: Any = None, settings: StorageSettings | None = None
    ):
        s = settings or get_storage_settings()
        self.bucket = bucket or s.object_storage_bucket
        self.client = client or make_s3_client(s)

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def get_bytes(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise NotFoundError(f"object not found: {key}") from exc
            raise

    def put_json(self, key: str, obj: Any) -> str:
        return self.put_bytes(key, json.dumps(obj, default=str).encode(), "application/json")

    def get_json(self, key: str) -> Any:
        return json.loads(self.get_bytes(key))

    def upload_file(self, path: str, key: str) -> str:
        self.client.upload_file(path, self.bucket, key)
        return key

    def download_file(self, key: str, path: str) -> str:
        self.client.download_file(self.bucket, key, path)
        return path

    def list_keys(self, prefix: str = "") -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        return [
            obj["Key"]
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            for obj in page.get("Contents", [])
        ]

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in
        )

    def presigned_put_url(self, key: str, expires_in: int = 3600, content_type: str | None = None) -> str:
        """For direct browser/phone uploads (e.g. photo proofs) without proxying bytes through the API."""
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return self.client.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in)
