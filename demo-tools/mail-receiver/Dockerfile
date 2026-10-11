# Vouch inbound mail receiver — small, non-root, read-only-friendly image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY mail_receiver ./mail_receiver
RUN pip install --no-cache-dir ".[s3]" \
    && useradd --system --uid 10001 --no-create-home mail \
    && mkdir -p /data \
    && chown mail:mail /data

USER mail
VOLUME ["/data"]
# 25 and 2525: SMTP (binding 25 as non-root needs the sysctl set in docker-compose.yml);
# 8025: HTTP health / recent / inbound fallback (keep it inside the VPC).
EXPOSE 25 2525 8025

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8025/health', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "mail_receiver"]
