#!/usr/bin/env bash
# Fresh machine -> ready to code. Usage: infra/scripts/bootstrap.sh [base|ml|agents|all]
set -euo pipefail
cd "$(dirname "$0")/../.."

if ! command -v uv >/dev/null; then
  echo "installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

case "${1:-base}" in
  base) make setup ;;
  ml) make setup-ml ;;
  agents) make setup-agents ;;
  all) make setup-all ;;
  *) echo "usage: $0 [base|ml|agents|all]"; exit 1 ;;
esac

uv run --all-packages pre-commit install >/dev/null 2>&1 || true
echo "ready: edit .env, then 'make test' and 'make run-<project>'"
