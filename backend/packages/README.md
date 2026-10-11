# Shared libraries (uv workspace members)

## hm_storage (packages/storage)

S3-compatible object storage, Postgres (SQLAlchemy + pgvector), and Valkey/Redis helpers.

Reads credentials from environment variables with multiple naming conventions:
- `OBJECT_STORAGE_ACCESS_KEY` (pydantic default)
- `OBJ_ACCESS_KEY` (preferred short form)
- `LINODE_OBJ_ACCESS_KEY` (fallback for stored credentials)

Same pattern applies to `*_SECRET_KEY`, `*_ENDPOINT`, `*_BUCKET`, `*_REGION`.

```python
from hm_storage import ObjectStore

store = ObjectStore()  # reads config from env
store.put_bytes("invoices/inv-123/doc.pdf", pdf_bytes)
data = store.get_bytes("invoices/inv-123/doc.pdf")
keys = store.list_keys("invoices/inv-123/")
```
