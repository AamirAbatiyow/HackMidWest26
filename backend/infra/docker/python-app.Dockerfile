# syntax=docker/dockerfile:1.7
# Shared image for every project API and inference service.
#
#   docker build -f infra/docker/python-app.Dockerfile \
#     --build-arg PROJECT=vouch --build-arg EXTRAS="--extra agents" -t vouch-api .
#   docker build -f infra/docker/python-app.Dockerfile \
#     --build-arg PROJECT=vouch --build-arg EXTRAS="--extra explain" \
#     --build-arg APP_MODULE=vouch.services.inference:app -t vouch-inference .
#
# EXTRAS: "--extra agents" (Strands), "--extra explain" (LIME+sklearn), "--extra ml" (torch CPU).

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
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 LOG_JSON=true PORT=8000 \
    APP_MODULE=${APP_MODULE:-${PROJECT}.main:app} MODEL_REGISTRY_DIR=/app/artifacts/models
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
RUN mkdir -p /app/artifacts && chown app:app /app/artifacts
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=2)"
CMD ["sh", "-c", "exec uvicorn \"$APP_MODULE\" --host 0.0.0.0 --port \"$PORT\""]
