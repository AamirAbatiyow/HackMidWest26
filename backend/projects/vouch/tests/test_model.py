import pytest
from fastapi.testclient import TestClient

from vouch.features import NUMERIC_FEATURES
from hm_ml_common import ModelRegistry


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    pytest.importorskip("torch")
    pytest.importorskip("lime")
    from vouch.models.train import train

    root = tmp_path_factory.mktemp("registry")
    version = train(ModelRegistry(root), n_train_vendors=500, n_test_vendors=200, epochs=15, write_card=False)
    return root, version


def test_training_writes_metrics_for_every_class(trained):
    root, version = trained
    meta = ModelRegistry(root).meta("vouch-risk", version)
    m = meta["metrics"]
    for cls in ("ato_bec", "insider", "fake_vendor"):
        assert {f"{cls}_precision", f"{cls}_recall", f"{cls}_roc_auc"} <= m.keys()
    assert m["system_honest_hold_rate"] < 0.15 and m["system_bad_actor_catch_rate"] > 0.7


def test_local_scorer_and_inference_service_return_lime(trained, monkeypatch):
    root, _ = trained
    monkeypatch.setenv("MODEL_REGISTRY_DIR", str(root))
    from vouch.services import inference

    inference.reset()
    client = TestClient(inference.app)
    assert client.get("/ready").status_code == 200
    feats = dict.fromkeys(NUMERIC_FEATURES, 0.0) | {"bank_mismatch": 1.0, "bank_change_unconfirmed": 1.0}
    body = client.post(
        "/score", json={"items": [{"features": feats, "categorical": {"country": "MX"}}]}
    ).json()
    res = body["results"][0]
    assert set(res["risk"]) == {"ato_bec", "insider", "fake_vendor"}
    assert 0 <= res["legitimacy"] <= 1 and res["lime"] and res["scorer"] == "local-torch"
    assert client.post("/score", json={"items": [{"features": {}}]}).status_code == 422
    inference.reset()
