# syntax=docker/dockerfile:1
# Only trusted toolchains are installed at image-build time. Submitted code never
# enters a build context. Each final image ID is approved by the local operator.
FROM python@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS base
USER root
# Debian signatures remain mandatory; proxy CA is a temporary build-only mount.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources

FROM base AS native
RUN --mount=type=secret,id=proxy_ca,mode=0444 \
    set -eu; if [ -f /run/secrets/proxy_ca ]; then export APT_CA='-o Acquire::https::CaInfo=/run/secrets/proxy_ca'; else export APT_CA=''; fi; \
    apt-get $APT_CA update && apt-get $APT_CA install -y --no-install-recommends gcc=4:14.2.0-1 g++=4:14.2.0-1 libc6-dev && \
    test "$(gcc -dumpfullversion)" = '14.2.0' && test "$(g++ -dumpfullversion)" = '14.2.0' && \
    rm -rf /var/lib/apt/lists/*
LABEL org.agentshield.runtime.family="native" org.agentshield.runtime.revision="1"
USER 65534:65534
WORKDIR /tmp

FROM base AS java
RUN --mount=type=secret,id=proxy_ca,mode=0444 \
    set -eu; if [ -f /run/secrets/proxy_ca ]; then export APT_CA='-o Acquire::https::CaInfo=/run/secrets/proxy_ca'; else export APT_CA=''; fi; \
    apt-get $APT_CA update && apt-get $APT_CA install -y --no-install-recommends openjdk-21-jdk-headless=21.0.13+9-1~deb13u2 openjdk-21-jre-headless=21.0.13+9-1~deb13u2 && \
    test "$(javac -version)" = 'javac 21.0.13' && rm -rf /var/lib/apt/lists/*
LABEL org.agentshield.runtime.family="java" org.agentshield.runtime.revision="1"
USER 65534:65534
WORKDIR /tmp

FROM base AS node
RUN --mount=type=secret,id=proxy_ca,mode=0444 \
    set -eu; if [ -f /run/secrets/proxy_ca ]; then export APT_CA='-o Acquire::https::CaInfo=/run/secrets/proxy_ca'; export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; else export APT_CA=''; fi; \
    apt-get $APT_CA update && apt-get $APT_CA install -y --no-install-recommends nodejs=20.19.2+dfsg-1+deb13u3 libnode115=20.19.2+dfsg-1+deb13u3 npm=9.2.0~ds1-3 && \
    npm install --global --ignore-scripts --no-audit --no-fund typescript@5.9.3 && \
    test "$(node --version)" = 'v20.19.2' && test "$(tsc --version)" = 'Version 5.9.3' && \
    apt-get purge -y npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* /root/.npm
LABEL org.agentshield.runtime.family="node" org.agentshield.runtime.revision="1"
USER 65534:65534
WORKDIR /tmp
