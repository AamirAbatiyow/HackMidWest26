"""hm_storage: S3-compatible object storage with local-disk fallback.

Reads credentials from environment variables with fallback naming:
  - OBJ_ACCESS_KEY or LINODE_OBJ_ACCESS_KEY
  - OBJ_SECRET_KEY or LINODE_OBJ_SECRET_KEY
  - OBJ_ENDPOINT, OBJ_BUCKET, OBJ_REGION

When credentials are unset, stores files locally (no cloud access needed for tests/CI).
"""

from .client import ObjectStore, ObjectStoreConfig

__all__ = ["ObjectStore", "ObjectStoreConfig"]
