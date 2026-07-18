ARG GPU_BASE_IMAGE=rocm/dev-ubuntu-24.04:7.2.4@sha256:bdc8e61026cbb844ede93d44d2c50055f51ebb2041906b60182bf3bee3139054
FROM ${GPU_BASE_IMAGE}

ARG GPU_BASE_IMAGE
ARG SOURCE_COMMIT=unknown
ARG LOCK_SHA256=unknown
LABEL org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.vendor="AI Tester" \
      org.opencontainers.image.base.name="${GPU_BASE_IMAGE}" \
      io.ai-tester.requirements-lock-sha256="${LOCK_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OLLAMA_BASE_URL=http://host.containers.internal:11434 \
    AI_TESTER_ALLOWED_DESTINATIONS=/data/allowed_destinations.json

WORKDIR /opt/ai-tester

COPY deploy/airgap/requirements.lock /tmp/requirements.lock
RUN python3 -m pip install --break-system-packages --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock

COPY ai_tester ./ai_tester
COPY config ./config
COPY deploy/gpu/rocm-smi /usr/local/bin/rocm-smi
COPY deploy/gpu/nvidia-smi /usr/local/bin/nvidia-smi

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin ai-tester \
    && install -d -o ai-tester -g ai-tester /data \
    && install -o ai-tester -g ai-tester -m 0644 \
       config/allowed_destinations.json /data/allowed_destinations.json \
    && chmod 0755 /usr/local/bin/rocm-smi /usr/local/bin/nvidia-smi \
    && test -x /opt/rocm/bin/rocm-smi

USER ai-tester
EXPOSE 5000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3).read(1)"]

CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "ai_tester.web:app"]
