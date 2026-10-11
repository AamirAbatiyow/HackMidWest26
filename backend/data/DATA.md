# Data

Folder contents are git-ignored (only `.gitkeep` is tracked). Keep large files out of git; put shared copies in Object Storage (`hm_storage.ObjectStore`).

| Folder | Use |
|---|---|
| `raw/` | Untouched downloads / exports. Never edit in place. |
| `interim/` | Cleaned or joined intermediate files. |
| `processed/` | Model-ready features and synthetic datasets. |

## Sources (fill in for every dataset used)
| Dataset | Project | Source / URL | License / terms | Notes (PII? synthetic?) |
|---|---|---|---|---|
| Synthetic baseline (`hm_ml_common.synthetic`) | all | generated in-repo | n/a | placeholder until real data |

## Rules
- Prefer synthetic or public data with a clear license; note the license here before using it in the demo.
- No real personal or financial data. If a sample looks real, say it is synthetic in the demo.
- Record the generator seed / script for anything in `processed/` so it can be regenerated.
