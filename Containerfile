ARG PYTHON_IMAGE=python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419
FROM ${PYTHON_IMAGE}

ARG SOURCE_COMMIT=unknown
ARG LOCK_SHA256=unknown
LABEL org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.vendor="AI Tester" \
      io.ai-tester.requirements-lock-sha256="${LOCK_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OLLAMA_BASE_URL=http://host.containers.internal:11434 \
    AI_TESTER_ALLOWED_DESTINATIONS=/data/allowed_destinations.json

WORKDIR /opt/ai-tester

COPY deploy/airgap/requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock

COPY ai_tester ./ai_tester
COPY config ./config

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin ai-tester \
    && install -d -o ai-tester -g ai-tester /data \
    && install -o ai-tester -g ai-tester -m 0644 \
       config/allowed_destinations.json /data/allowed_destinations.json

USER ai-tester
EXPOSE 5000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3).read(1)"]

CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "ai_tester.web:app"]
