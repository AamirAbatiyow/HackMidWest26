"""Shared ML utilities. Heavy deps (torch, lime, sklearn) are imported only by the submodules that need them:

- `hm_ml_common.synthetic`, `.metrics`, `.registry`: numpy only (always available)
- `hm_ml_common.explain`: needs the `explain` extra (lime + scikit-learn)
- `hm_ml_common.training`: needs the `ml` extra (torch)
"""

from hm_ml_common.metrics import best_threshold, classification_report, precision_at_k
from hm_ml_common.registry import ModelRegistry
from hm_ml_common.synthetic import Dataset, make_classification_data, train_val_test_split

__all__ = [
    "Dataset",
    "ModelRegistry",
    "best_threshold",
    "classification_report",
    "make_classification_data",
    "precision_at_k",
    "train_val_test_split",
]
