# Add a new concept project

1. Ask for (or infer) a lowercase name and a one-line pitch.
2. Run `make new-project name=<name> desc="<pitch>"`, then `make test` (uv picks up the new workspace member automatically).
3. Fill `projects/<name>/PLAN.md` (one-liner, demo moment, sponsor hooks) and log the pivot in `docs/DECISIONS.md`.
4. Verify `make run-<name>` serves `/health` on its assigned port (see `projects/<name>/<name>/config.py`).
Do not copy another project folder or touch shared packages for this.
