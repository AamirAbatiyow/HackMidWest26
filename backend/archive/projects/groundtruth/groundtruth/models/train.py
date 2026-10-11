"""Training entrypoint (`make train-groundtruth`).

Placeholder: trains a logistic-regression baseline on generic synthetic data so the
train -> registry -> /predict -> LIME path works end-to-end on day one.
TODO: swap in the real dataset / domain generator and, if it helps the story, a torch model
(hm_ml_common.training.TabularMLP + registry.save(..., framework="torch")).
"""

from groundtruth.config import get_settings
from hm_ml_common import ModelRegistry, best_threshold, classification_report, make_classification_data
from hm_ml_common.synthetic import train_val_test_split

# TODO: real feature names.
FEATURES = [f"feature_{i}" for i in range(6)]
CLASSES = ["negative", "positive"]


def train(registry: ModelRegistry | None = None, seed: int = 0) -> str:
    from sklearn.linear_model import LogisticRegression

    ds = make_classification_data(n_samples=3000, n_features=len(FEATURES), feature_names=FEATURES, seed=seed)
    (X_tr, y_tr), (X_va, y_va), (X_te, y_te) = train_val_test_split(ds.X, ds.y, seed=seed)
    clf = LogisticRegression(max_iter=1000, class_weight="balanced").fit(X_tr, y_tr)
    threshold = best_threshold(y_va, clf.predict_proba(X_va)[:, 1])
    metrics = classification_report(y_te, clf.predict_proba(X_te)[:, 1], threshold)

    bundle = {
        "model": clf,
        "feature_names": FEATURES,
        "class_names": CLASSES,
        "threshold": threshold,
        "background": X_tr[:500],  # LIME needs a sample of training data
    }
    registry = registry or ModelRegistry()
    version = registry.save(get_settings().model_name, bundle, metrics=metrics, params={"algo": "logreg"})
    print(
        f"saved {get_settings().model_name}:{version}  f1={metrics['f1']:.3f}  roc_auc={metrics['roc_auc']:.3f}"
    )
    return version


def main() -> None:
    train()


if __name__ == "__main__":
    main()
