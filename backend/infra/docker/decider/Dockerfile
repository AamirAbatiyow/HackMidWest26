# Strands Decider 2B: CPU-only decision model server.
# https://github.com/strands-labs/strands-decider (Apache-2.0)
#
# Build:
#   docker build -t strands-decider:local -f infra/docker/decider/Dockerfile .
#
# Run (weights download on first start, ~4.5 GB):
#   docker run -p 8099:8099 -v decider-cache:/app/.cache strands-decider:local
#
# With pre-downloaded weights:
#   docker run -p 8099:8099 -v /path/to/hf-cache:/app/.cache strands-decider:local

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Strands Decider 2B"
LABEL org.opencontainers.image.description="CPU decision model server for agentic workflows"
LABEL org.opencontainers.image.source="https://github.com/strands-labs/strands-decider"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip wheel && \
    git clone --depth 1 https://github.com/strands-labs/strands-decider.git /tmp/strands-decider && \
    pip install "/tmp/strands-decider[cpu]" && \
    rm -rf /tmp/strands-decider

ARG DECIDER_MODEL=StrandsAgents/strands-decider-2B-qwen3.5-v1-2610

RUN python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('${DECIDER_MODEL}', cache_dir='${HF_HOME}')" && \
    echo "Model ${DECIDER_MODEL} pre-downloaded."

COPY infra/docker/decider/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -sf http://localhost:8099/health || exit 1

ENV DECIDER_MODEL=${DECIDER_MODEL}
ENV DECIDER_PORT=8099

ENTRYPOINT ["/app/entrypoint.sh"]
