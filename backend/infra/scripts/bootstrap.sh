#!/usr/bin/env bash
# Fresh machine -> ready to code. Usage: infra/scripts/bootstrap.sh [base|min|agents|all]
set -euo pipefail
cd "$(dirname "$0")/../.."

if ! command -v uv >/dev/null; then
  echo "installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

case "${1:-base}" in
  base) make setup ;;
  min) make setup-min ;;
  agents) make setup-agents ;;
  all) make setup-all ;;
  *) echo "usage: $0 [base|min|agents|all]"; exit 1 ;;
esac

uv run --all-packages pre-commit install >/dev/null 2>&1 || true

# Image invoices (PNG/JPG) need the Tesseract binary; pytesseract is only the wrapper. Without it the API runs,
# /v1/health reports ocr "down" and image intake tests skip.
if ! command -v tesseract >/dev/null; then
  echo "note: tesseract not found; image invoice OCR is off. Install it:"
  echo "  Debian/Ubuntu: sudo apt-get install -y tesseract-ocr tesseract-ocr-eng    macOS: brew install tesseract"
fi
echo "ready: edit .env (AKAMAI_INFERENCE_API_KEY), then 'make test', 'make demo-vouch' and 'make run-vouch'"
