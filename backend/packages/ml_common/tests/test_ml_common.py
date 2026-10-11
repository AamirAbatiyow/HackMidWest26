import numpy as np
import pytest

from hm_ml_common import (
    ModelRegistry,
    best_threshold,
    classification_report,
    make_classification_data,
    precision_at_k,
    train_val_test_split,
)
from hm_ml_common.metrics import roc_auc


def test_synthetic_and_split_are_stratified():
    ds = make_classification_data(n_samples=1000, positive_rate=0.2, seed=1)
    (Xtr, ytr), (Xva, yva), (Xte, yte) = train_val_test_split(ds.X, ds.y, seed=1)
    assert len(ytr) + len(yva) + len(yte) == 1000
    assert abs(yte.mean() - ds.y.mean()) < 0.03


def test_metrics_known_values():
    y = np.array([0, 0, 1, 1])
    s = np.array([0.1, 0.4, 0.35, 0.8])
    assert roc_auc(y, s) == pytest.approx(0.75)
    rep = classification_report(y, s, threshold=0.5)
    assert rep["confusion"] == {"tp": 1, "fp": 0, "fn": 1, "tn": 2}
    assert rep["precision"] == 1.0 and rep["recall"] == 0.5
    assert precision_at_k(y, s, 1) == 1.0
    assert 0 < best_threshold(y, s) <= 0.8


class Threshold:
    def __init__(self, t):
        self.t = t


def test_registry_roundtrip(tmp_path):
    reg = ModelRegistry(tmp_path)
    v1 = reg.save("toy", Threshold(0.3), metrics={"f1": 0.5}, version="v1")
    reg.save("toy", Threshold(0.4), version="v2")
    assert reg.list_versions("toy") == ["v1", "v2"]
    assert reg.load("toy").t == 0.4
    assert reg.load("toy", v1).t == 0.3
    assert reg.meta("toy", "v1")["metrics"] == {"f1": 0.5}
    with pytest.raises(FileNotFoundError):
        reg.meta("missing")


def test_lime_wrapper_smoke_with_toy_model():
    pytest.importorskip("lime")
    from sklearn.linear_model import LogisticRegression

    from hm_ml_common.explain import TabularExplainer

    ds = make_classification_data(n_samples=600, n_features=5, n_informative=2, positive_rate=0.3, signal=2.5)
    clf = LogisticRegression(max_iter=500).fit(ds.X, ds.y)
    explainer = TabularExplainer(ds.X, ds.feature_names, class_names=["ok", "fraud"])
    exp = explainer.explain(ds.X[np.argmax(ds.y)], clf.predict_proba, num_features=5, num_samples=500)

    assert set(exp.probabilities) == {"ok", "fraud"}
    assert len(exp.contributions) == 5
    top_features = " ".join(c.feature for c in exp.top(2))
    assert "f0" in top_features or "f1" in top_features
    assert exp.to_text().startswith("Predicted")
    assert exp.model_dump_json()


def test_text_explainer_smoke():
    pytest.importorskip("lime")
    from hm_ml_common.explain import TextExplainer

    def predict(texts):
        p = np.array([0.9 if "invoice" in t else 0.1 for t in texts])
        return np.stack([1 - p, p], axis=1)

    exp = TextExplainer(["personal", "business"]).explain(
        "invoice for office chairs", predict, num_samples=200
    )
    assert exp.explained_class == "business"
    assert exp.top(1)[0].feature == "invoice"


def test_torch_training_loop():
    pytest.importorskip("torch")
    from hm_ml_common.training import TabularMLP, make_loader, predict_proba_fn, set_seed, train_classifier

    set_seed(0)
    ds = make_classification_data(n_samples=800, positive_rate=0.3, signal=2.0)
    (Xtr, ytr), (Xva, yva), (Xte, yte) = train_val_test_split(ds.X, ds.y)
    model = TabularMLP(ds.X.shape[1])
    hist = train_classifier(model, make_loader(Xtr, ytr), make_loader(Xva, yva, shuffle=False), epochs=15)
    assert hist.best_epoch >= 0 and hist.val_loss
    probs = predict_proba_fn(model)(Xte)[:, 1]
    assert roc_auc(yte, probs) > 0.85
