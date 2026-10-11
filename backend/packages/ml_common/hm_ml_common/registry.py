"""Tiny file-based model registry: artifacts/models/<name>/<version>/{model.*, meta.json}.

Optionally mirrors versions to Object Storage (hm_storage.ObjectStore) so the inference container can
pull weights at startup instead of baking them into the image.
"""

from __future__ import annotations

import json
import os
import pickle
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Framework = Literal["pickle", "torch"]


class ModelRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("MODEL_REGISTRY_DIR", "artifacts/models"))

    def _dir(self, name: str, version: str) -> Path:
        return self.root / name / version

    def list_versions(self, name: str) -> list[str]:
        base = self.root / name
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if (p / "meta.json").is_file())

    def latest(self, name: str) -> str | None:
        versions = self.list_versions(name)
        return versions[-1] if versions else None

    def save(
        self,
        name: str,
        model: Any,
        *,
        framework: Framework = "pickle",
        metrics: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> str:
        """Persist a model. `pickle` for sklearn/numpy objects, `torch` saves `model.state_dict()`."""
        version = version or datetime.now(UTC).strftime("v%Y%m%d-%H%M%S")
        target = self._dir(name, version)
        target.mkdir(parents=True, exist_ok=True)
        if framework == "torch":
            import torch

            torch.save(model.state_dict(), target / "model.pt")
        else:
            with open(target / "model.pkl", "wb") as fh:
                pickle.dump(model, fh)
        meta = {
            "name": name,
            "version": version,
            "framework": framework,
            "created_at": datetime.now(UTC).isoformat(),
            "metrics": metrics or {},
            "params": params or {},
        }
        (target / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
        return version

    def meta(self, name: str, version: str | None = None) -> dict[str, Any]:
        version = version or self.latest(name)
        if version is None:
            raise FileNotFoundError(f"no versions of model '{name}' in {self.root}")
        return json.loads((self._dir(name, version) / "meta.json").read_text())

    def load(self, name: str, version: str | None = None, model: Any = None) -> Any:
        """Load a model. For torch, pass an un-trained `model` instance to receive the weights."""
        meta = self.meta(name, version)
        target = self._dir(name, meta["version"])
        if meta["framework"] == "torch":
            import torch

            if model is None:
                raise ValueError("torch models need an instance: registry.load(name, model=MyNet(...))")
            model.load_state_dict(torch.load(target / "model.pt", map_location="cpu", weights_only=True))
            model.eval()
            return model
        with open(target / "model.pkl", "rb") as fh:
            return pickle.load(fh)  # noqa: S301 - only load artifacts this repo produced

    def push(self, name: str, version: str, store: Any, prefix: str = "models") -> list[str]:
        """Upload a version to Object Storage. `store` is an hm_storage.ObjectStore."""
        keys = []
        for path in self._dir(name, version).iterdir():
            keys.append(store.upload_file(str(path), f"{prefix}/{name}/{version}/{path.name}"))
        return keys

    def pull(self, name: str, version: str, store: Any, prefix: str = "models") -> Path:
        target = self._dir(name, version)
        target.mkdir(parents=True, exist_ok=True)
        for key in store.list_keys(f"{prefix}/{name}/{version}/"):
            store.download_file(key, str(target / key.rsplit("/", 1)[-1]))
        return target
