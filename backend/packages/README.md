# Shared libraries (uv workspace members)

## hm_storage

S3-compatible object storage wrapper with local-disk fallback for invoice files,
attachments, and audit artifacts.

Reads credentials from environment variables with fallback naming:
- `OBJ_ACCESS_KEY` or `LINODE_OBJ_ACCESS_KEY` (OBJ_* takes precedence)
- `OBJ_SECRET_KEY` or `LINODE_OBJ_SECRET_KEY`
- `OBJ_ENDPOINT`, `OBJ_BUCKET`, `OBJ_REGION`

When credentials are unset, files are stored locally under `data/objects/` so
tests and CI run without cloud access.

```python
from hm_storage import ObjectStore

store = ObjectStore()  # reads config from env
store.put_invoice("inv-123", "invoice.pdf", pdf_bytes)
store.put_attachment("inv-123", "receipt.png", image_bytes)
store.put_audit_artifact("inv-123", "lime.json", json_bytes)

# Health check
ok, desc = store.ping()
```
