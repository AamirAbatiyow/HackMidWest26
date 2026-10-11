import pytest
from moto import mock_aws
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from hm_core.errors import NotFoundError
from hm_storage import Base, ObjectStore, StorageSettings, make_engine, make_s3_client, ping, session_scope


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        s = StorageSettings(_env_file=None, object_storage_region="us-east-1")
        st = ObjectStore("test-bucket", client=make_s3_client(s, endpoint_url=""), settings=s)
        st.ensure_bucket()
        yield st


def test_object_store_roundtrip(store):
    store.put_json("runs/1.json", {"a": 1})
    assert store.get_json("runs/1.json") == {"a": 1}
    assert store.list_keys("runs/") == ["runs/1.json"]
    assert "runs/1.json" in store.presigned_get_url("runs/1.json")
    assert "X-Amz-Signature" in store.presigned_put_url("uploads/p.jpg", content_type="image/jpeg")
    with pytest.raises(NotFoundError):
        store.get_bytes("missing")


class Note(Base):
    __tablename__ = "test_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(String(100))


def test_session_scope_with_sqlite():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert ping(engine)
    with session_scope(engine) as s:
        s.add(Note(body="hello"))
    with session_scope(engine) as s:
        assert s.query(Note).one().body == "hello"
    with pytest.raises(RuntimeError), session_scope(engine) as s:
        s.add(Note(body="rolled back"))
        raise RuntimeError
    with session_scope(engine) as s:
        assert s.query(Note).count() == 1
