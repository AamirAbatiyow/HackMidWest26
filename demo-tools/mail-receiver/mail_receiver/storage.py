"""Persist received mail: local disk always, S3-compatible object storage when configured."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .parse import ParsedMail

log = logging.getLogger(__name__)

_FILE_MODE = 0o640  # never executable


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:  # pragma: no cover - permissions differ on some mounts
        pass


class DiskStore:
    """``<data_dir>/received/<id>/{message.eml,intake.json,meta.json,attachments/*}`` plus a
    ``dead-letter`` folder for deliveries that exhausted their retries."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.received = root / "received"
        self.dead = root / "dead-letter"
        self.received.mkdir(parents=True, exist_ok=True)
        self.dead.mkdir(parents=True, exist_ok=True)

    def dir_for(self, msg_id: str) -> Path:
        return self.received / msg_id

    def save(self, msg_id: str, raw: bytes, parsed: ParsedMail, meta: dict) -> Path:
        d = self.dir_for(msg_id)
        d.mkdir(parents=True, exist_ok=True)
        _write(d / "message.eml", raw)
        _write(d / "intake.json", json.dumps(parsed.intake).encode())
        _write(d / "meta.json", json.dumps(meta, indent=2).encode())
        if parsed.kept_payloads:
            att_dir = d / "attachments"
            att_dir.mkdir(exist_ok=True)
            for safe_name, payload in parsed.kept_payloads.items():
                _write(att_dir / safe_name, payload)
        return d

    def update_meta(self, msg_id: str, **fields) -> dict | None:
        path = self.dir_for(msg_id) / "meta.json"
        if not path.exists():
            return None
        meta = json.loads(path.read_text())
        meta.update(fields)
        _write(path, json.dumps(meta, indent=2).encode())
        return meta

    def load_intake(self, msg_id: str) -> dict:
        return json.loads((self.dir_for(msg_id) / "intake.json").read_text())

    def load_raw(self, msg_id: str) -> bytes:
        return (self.dir_for(msg_id) / "message.eml").read_bytes()

    def load_meta(self, msg_id: str) -> dict | None:
        path = self.dir_for(msg_id) / "meta.json"
        return json.loads(path.read_text()) if path.exists() else None

    def recent_metas(self, limit: int) -> list[dict]:
        dirs = sorted((p for p in self.received.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
        out: list[dict] = []
        for d in dirs[:limit]:
            path = d / "meta.json"
            if path.exists():
                try:
                    out.append(json.loads(path.read_text()))
                except json.JSONDecodeError:
                    continue
        return out

    # ------------------------------------------------------------ dead letters ----
    def write_dead_letter(self, msg_id: str, error: str, attempts: int) -> Path:
        path = self.dead / f"{msg_id}.json"
        record = {
            "id": msg_id,
            "dead_lettered_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "attempts": attempts,
            "error": error,
            "message_dir": str(self.dir_for(msg_id)),
        }
        _write(path, json.dumps(record, indent=2).encode())
        return path

    def dead_letters(self) -> list[Path]:
        return sorted(self.dead.glob("*.json"))

    def dead_letter_count(self) -> int:
        return len(self.dead_letters())

    def remove_dead_letter(self, msg_id: str) -> None:
        path = self.dead / f"{msg_id}.json"
        if path.exists():
            path.unlink()


class ObjectStore:
    """Optional mirror to S3-compatible storage (Akamai / Linode Object Storage)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.has_bucket
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3  # imported lazily: optional dependency

            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.obj_endpoint,
                aws_access_key_id=self.settings.obj_access_key,
                aws_secret_access_key=self.settings.obj_secret_key,
            )
        return self._client

    def upload_dir(self, msg_id: str, directory: Path) -> list[str]:
        """Upload every file under ``directory``; returns the object keys. Blocking (run in a thread)."""
        if not self.enabled:
            return []
        client = self._get_client()
        prefix = self.settings.obj_prefix.strip("/")
        keys: list[str] = []
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            rel = path.relative_to(directory).as_posix()
            key = f"{prefix}/{msg_id}/{rel}" if prefix else f"{msg_id}/{rel}"
            client.put_object(Bucket=self.settings.obj_bucket, Key=key, Body=path.read_bytes())
            keys.append(key)
        log.info(
            "mirrored %s to s3://%s/%s (%d objects)", msg_id, self.settings.obj_bucket, prefix, len(keys)
        )
        return keys
