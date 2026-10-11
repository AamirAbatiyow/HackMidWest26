import pytest
from fastapi.testclient import TestClient

from hm_ml_common import ModelRegistry
from vouch.features import NUMERIC_FEATURES


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


def test_model_scores_in_api_payloads_and_audit(trained, monkeypatch):
    """Model scores flow into the frontend API and audit records with LIME factors."""
    root, version = trained
    monkeypatch.setenv("MODEL_REGISTRY_DIR", str(root))
    monkeypatch.setenv("VOUCH_SCORER", "local")
    from datetime import date

    from hm_settlement import MockSettlementAdapter
    from vouch.config import reset_settings_cache
    from vouch.demo import demo_submissions, seed
    from vouch.engine import VouchEngine
    from vouch.llm import LLMRuntime
    from vouch.pipeline import execute

    reset_settings_cache()
    from vouch.config import get_settings

    settings = get_settings()
    assert settings.scorer == "local"

    llm = LLMRuntime("offline", settings=settings)
    engine = VouchEngine(
        settings=settings, llm=llm, adapter=MockSettlementAdapter(), today=date(2026, 10, 10)
    )
    seed(engine, background_vendors=60)

    run = engine.new_run(demo_submissions(engine.today))
    execute(engine, run)

    cards = run.card_list()
    assert len(cards) == 6

    for card in cards:
        if card.invoice.is_credit_note:
            continue
        s = card.scores
        assert s is not None, f"card {card.id} has no scores"
        assert s.scorer == "local-torch"
        assert version in s.model_version
        assert 0 <= s.legitimacy <= 1
        assert set(s.risk.keys()) == {"ato_bec", "insider", "fake_vendor"}
        assert s.lime, f"card {card.id} has no LIME factors"
        for factor in s.lime:
            assert {"feature", "label", "weight"} <= set(factor.keys())

    risky_card = next(c for c in cards if c.invoice.vendor_name == "Apex Global Trading LLC")
    assert risky_card.scores.risk["fake_vendor"] > 0.5
    assert risky_card.policy.lane.value == "hold"

    clean_card = next(c for c in cards if c.invoice.vendor_name == "Prairie Packaging Supply")
    assert clean_card.scores.legitimacy > 0.8
    assert clean_card.policy.lane.value == "fast_pay"

    reset_settings_cache()
