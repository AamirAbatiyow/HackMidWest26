import json
import logging

from hm_core import AppSettings, NotFoundError, configure_logging, find_env_file
from hm_core.logging import JsonFormatter


def test_settings_parse_csv_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("API_KEYS", "k1,k2")
    monkeypatch.setenv("APP_ENV", "test")
    s = AppSettings(_env_file=None)
    assert s.cors_allow_origins == ["http://a.test", "http://b.test"]
    assert s.api_keys == ["k1", "k2"]
    assert s.auth_enabled


def test_settings_defaults(monkeypatch):
    for var in ("CORS_ALLOW_ORIGINS", "API_KEYS", "APP_ENV"):
        monkeypatch.delenv(var, raising=False)
    s = AppSettings(_env_file=None)
    assert s.cors_allow_origins == ["*"]
    assert not s.auth_enabled


def test_find_env_file(tmp_path):
    (tmp_path / ".env").write_text("X=1")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_env_file(nested) == tmp_path / ".env"


def test_error_to_dict():
    err = NotFoundError("missing invoice", details={"id": "inv_1"})
    assert err.status_code == 404
    assert err.to_dict()["error"] == {
        "code": "not_found",
        "message": "missing invoice",
        "details": {"id": "inv_1"},
    }


def test_json_formatter_includes_extras():
    configure_logging("DEBUG", json_logs=True)
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("x",), None)
    record.request_id = "abc"
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "hello x" and out["request_id"] == "abc"
