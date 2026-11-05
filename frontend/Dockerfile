# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
# Optional CA bundle for a managed build proxy. No credentials or CAs are copied.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --no-audit --no-fund

FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
ARG API_INTERNAL_URL=http://backend:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL NEXT_TELEMETRY_DISABLED=1 BUILD_STANDALONE=true
RUN mkdir -p public && npm run build

FROM node:24-bookworm-slim AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app
WORKDIR /app
COPY --from=build --chown=10001:10001 /app/.next/standalone ./
COPY --from=build --chown=10001:10001 /app/.next/static ./.next/static
COPY --from=build --chown=10001:10001 /app/public ./public
USER 10001:10001
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login',{signal:AbortSignal.timeout(3000)}).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
