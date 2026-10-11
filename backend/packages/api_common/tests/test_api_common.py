from fastapi import Depends
from fastapi.testclient import TestClient

from hm_api_common import create_app, require_api_key
from hm_core import AppSettings, NotFoundError
from hm_core.config import get_app_settings


def make_client(checks=None, **settings_kw):
    settings = AppSettings(_env_file=None, **settings_kw)
    app = create_app("svc", settings=settings, readiness_checks=checks, configure_logs=False)

    @app.get("/boom")
    def boom():
        raise NotFoundError("nope")

    @app.get("/crash")
    def crash():
        raise RuntimeError("bug")

    @app.get("/secure", dependencies=[Depends(require_api_key)])
    def secure():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_health_and_request_id():
    r = make_client().get("/health", headers={"X-Request-ID": "rid-1"})
    assert r.status_code == 200
    assert r.json()["service"] == "svc"
    assert r.headers["x-request-id"] == "rid-1"


def test_ready_reports_failures():
    async def db_ok():
        return True

    def model_missing():
        raise FileNotFoundError

    r = make_client(checks={"db": db_ok, "model": model_missing}).get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"] == {"db": "ok", "model": "error: FileNotFoundError"}


def test_app_error_and_unhandled_error_are_json():
    client = make_client()
    r = client.get("/boom")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.get("/crash")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"


def test_cors_from_settings():
    client = make_client(cors_allow_origins="http://front.test")
    r = client.options(
        "/health", headers={"Origin": "http://front.test", "Access-Control-Request-Method": "GET"}
    )
    assert r.headers["access-control-allow-origin"] == "http://front.test"


def test_api_key_auth(monkeypatch):
    get_app_settings.cache_clear()
    monkeypatch.setenv("API_KEYS", "secret-1")
    try:
        client = make_client()
        assert client.get("/secure").status_code == 401
        assert client.get("/secure", headers={"X-API-Key": "secret-1"}).status_code == 200
    finally:
        get_app_settings.cache_clear()
