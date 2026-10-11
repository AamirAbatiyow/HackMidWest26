import pytest
from fastapi.testclient import TestClient

from hm_ml_common import ModelRegistry
from PROJECTNAME.main import app
from PROJECTNAME.services import inference


def test_api_health():
    client = TestClient(app)
    assert client.get("/health").json()["service"] == "PROJECTNAME-api"
    assert client.get("/v1/info").json()["project"] == "PROJECTNAME"


def test_inference_without_model_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_REGISTRY_DIR", str(tmp_path))
    inference.reset()
    client = TestClient(inference.app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503


def test_train_then_predict_with_explanation(tmp_path, monkeypatch):
    pytest.importorskip("sklearn")
    pytest.importorskip("lime")
    from PROJECTNAME.models.train import FEATURES, train

    monkeypatch.setenv("MODEL_REGISTRY_DIR", str(tmp_path))
    train(ModelRegistry(tmp_path))
    inference.reset()
    client = TestClient(inference.app)
    assert client.get("/ready").status_code == 200
    body = client.post("/predict", json={"features": dict.fromkeys(FEATURES, 1.0), "explain": True}).json()
    assert 0 <= body["score"] <= 1 and body["explanation"]["contributions"]
    assert client.post("/predict", json={"features": {}}).status_code == 422


def test_agent_builds_offline():
    pytest.importorskip("strands")
    from hm_agents_common.testing import ScriptedModel
    from PROJECTNAME.agents import build_agent

    agent = build_agent(model=ScriptedModel(["ready"]))
    assert "ready" in str(agent("ping"))
