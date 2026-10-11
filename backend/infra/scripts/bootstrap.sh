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

# Image invoices (PNG/JPEG, scanned PDFs) need the Tesseract binary; pytesseract alone reads nothing.
if ! command -v tesseract >/dev/null; then
  if command -v apt-get >/dev/null; then
    echo "installing tesseract-ocr (image invoice OCR)..."
    sudo_cmd=""; [[ $EUID -ne 0 ]] && command -v sudo >/dev/null && sudo_cmd="sudo"
    $sudo_cmd apt-get install -y -qq tesseract-ocr tesseract-ocr-eng \
      || echo "warning: could not install tesseract-ocr; image invoices will be held as unreadable"
  else
    echo "warning: tesseract not found (brew install tesseract / apt-get install tesseract-ocr tesseract-ocr-eng)"
  fi
fi
echo "ready: edit .env (AKAMAI_INFERENCE_API_KEY), then 'make test', 'make demo-vouch' and 'make run-vouch'"
