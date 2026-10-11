# syntax=docker/dockerfile:1.7
# Shared image for every project API and inference service.
#
#   docker build -f infra/docker/python-app.Dockerfile \
#     --build-arg PROJECT=vouch --build-arg EXTRAS="--extra ml --extra cedar" -t vouch-api .
#   docker build -f infra/docker/python-app.Dockerfile \
#     --build-arg PROJECT=vouch --build-arg EXTRAS="--extra ml" \
#     --build-arg APP_MODULE=vouch.services.inference:app -t vouch-inference .
#
# EXTRAS: "--extra ml" (torch CPU for the trained model), "--extra cedar" (real Cedar engine; the Python
# mirror is used otherwise), "--extra ocr-rapid" (OCR without the tesseract binary).
# OCR=1 (default) installs the Tesseract binary + English data in the runtime image: pytesseract is only a
# wrapper, and without the binary every PNG/JPEG invoice is held as unreadable (amount 0). The API image
# needs it; the inference / model-server image passes OCR=0.

ARG PYTHON_VERSION=3.12

FROM ghcr.io/astral-sh/uv:0.13 AS uv

FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
ARG PROJECT
ARG EXTRAS=""
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY projects ./projects
RUN --mount=type=cache,target=/root/.cache/uv \
    test -n "$PROJECT" && \
    uv sync --frozen --no-default-groups --no-editable --package "$PROJECT" $EXTRAS

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG PROJECT
ARG APP_MODULE=""
ARG OCR=1
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 LOG_JSON=true PORT=8000 \
    APP_MODULE=${APP_MODULE:-${PROJECT}.main:app} MODEL_REGISTRY_DIR=/app/artifacts/models \
    VOUCH_DATA_DIR=/app/data
# python:*-slim ships no OCR engine; vouch.intake.extract.ocr_backend() looks for `tesseract` on PATH.
RUN if [ "$OCR" = "1" ]; then \
      apt-get update && \
      apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && \
      rm -rf /var/lib/apt/lists/* && \
      tesseract --version && tesseract --list-langs 2>&1 | grep -qx eng; \
    fi
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
# The trained vouch-risk bundles are tiny (~240 KB) and tracked in git, so the image is self-contained
# (no model download at boot). The Cedar policy ships inside the wheel (see projects/vouch/pyproject.toml).
COPY --chown=app:app artifacts/models /app/artifacts/models
RUN mkdir -p /app/data && chown app:app /app/data
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=2)"
CMD ["sh", "-c", "exec uvicorn \"$APP_MODULE\" --host 0.0.0.0 --port \"$PORT\""]
