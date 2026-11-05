# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS dependencies
WORKDIR /build
COPY requirements.txt ./
# Optional CA bundle for a managed build proxy. The mount never enters a layer.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    python -m venv /opt/venv && \
    /opt/venv/bin/python -m pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=10001:10001 app ./app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--ws", "websockets", "--ws-max-size", "1024", "--ws-max-queue", "8", "--limit-concurrency", "64", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "30"]
