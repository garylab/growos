# GrowOS backend image. One body, two targets:
#
#   app      — the API, the migrations and the general worker. Plain Debian; no crawler binary.
#   crawler  — the crawl worker. Adds the SiteOne Crawler binary, which needs glibc >= 2.38, so this target alone
#              is built on Debian trixie by passing BASE. Keeping that requirement here is the point of the split:
#              one 32MB binary used by one task should not decide the operating system of the API and the database
#              migrations, and upgrading it should not rebuild them.
#
# Build:  docker build --target app .
#         docker build --target crawler --build-arg BASE=python:3.12-slim-trixie .
ARG BASE=python:3.12-slim

FROM ${BASE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
# Install dependencies only first (layer cache), then the code.
RUN python - <<'PY'
import tomllib, subprocess, sys
data = tomllib.load(open("pyproject.toml", "rb"))
deps = data["project"]["dependencies"] + data["project"]["optional-dependencies"]["dev"]
subprocess.check_call([sys.executable, "-m", "pip", "install", *deps])
PY
COPY . .

RUN useradd --create-home --uid 10001 growos && mkdir -p /data/artifacts && chown -R growos:growos /data /app
ENV ARTIFACTS_DIR=/data/artifacts
ENTRYPOINT ["/usr/bin/tini", "--"]

# ---------------------------------------------------------------------------- API, migrations, general worker
FROM runtime AS app
USER growos
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

# ---------------------------------------------------------------------------- crawl worker
FROM runtime AS crawler
ARG SITEONE_VERSION=2.5.1
# SiteOne Crawler (MIT) — single static-ish binary
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64) s1="x64";; arm64) s1="arm64";; *) echo "unsupported arch $arch"; exit 1;; esac; \
    curl -fsSL -o /tmp/siteone.tgz "https://github.com/janreges/siteone-crawler/releases/download/v${SITEONE_VERSION}/siteone-crawler-v${SITEONE_VERSION}-linux-${s1}.tar.gz"; \
    mkdir -p /opt/siteone-crawler; tar -xzf /tmp/siteone.tgz -C /opt/siteone-crawler --strip-components=1; rm /tmp/siteone.tgz; \
    /opt/siteone-crawler/siteone-crawler --version 2>&1 | grep -q "Version: ${SITEONE_VERSION}"
USER growos
ENV SITEONE_BIN=/opt/siteone-crawler/siteone-crawler WORKER_QUEUE=crawler
CMD ["python", "-m", "worker.main"]
