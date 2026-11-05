#!/usr/bin/env bash
# Trusted, disposable CI database only. Does not configure the execution sandbox.
set -Eeuo pipefail
container="${CI_MONGODB_CONTAINER:-agentshield-ci-mongo}"
port="${CI_MONGODB_PORT:-27017}"
image="${CI_MONGODB_IMAGE:-mongo:7}"
[[ "$container" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || exit 2
[[ "$port" =~ ^[0-9]{4,5}$ ]] && (( port >= 1024 && port <= 65535 )) || exit 2

# Inspect only lifecycle/health data, never Config.Env or credential files.
diagnose() {
  docker version --format 'Docker client={{.Client.Version}} server={{.Server.Version}}' || true
  uname -sm
  if docker container inspect "$container" >/dev/null 2>&1; then
    docker inspect --format '{{json .State}}' "$container" || true
    docker logs --tail 120 "$container" || true
  fi
}
failed() {
  result=$?
  trap - ERR
  echo "MongoDB startup/readiness failed (exit $result)." >&2
  diagnose
  exit "$result"
}

case "${1:-}" in
  start)
    trap failed ERR
    if docker container inspect "$container" >/dev/null 2>&1; then
      echo "Refusing to replace existing container: $container" >&2
      exit 1
    fi
    docker pull "$image"
    docker run --detach --name "$container" \
      --publish "127.0.0.1:${port}:27017" \
      --health-cmd "mongosh --quiet --norc 'mongodb://127.0.0.1:27017/admin?serverSelectionTimeoutMS=2000' --eval 'quit(db.adminCommand({ping:1}).ok === 1 ? 0 : 1)'" \
      --health-start-period 30s --health-interval 5s --health-timeout 10s --health-retries 12 \
      "$image" --bind_ip_all --wiredTigerCacheSizeGB 0.25
    deadline=$((SECONDS + 180))
    while (( SECONDS < deadline )); do
      state="$(docker inspect --format '{{.State.Status}}' "$container")"
      health="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
      if [[ "$state" != running || "$health" == unhealthy ]]; then
        echo "MongoDB state=$state health=$health" >&2
        false
      fi
      if [[ "$health" == healthy ]]; then
        echo "MongoDB ready on loopback port $port."
        exit 0
      fi
      sleep 2
    done
    echo "MongoDB did not become healthy within 180 seconds." >&2
    false
    ;;
  diagnose) diagnose ;;
  stop)
    if docker container inspect "$container" >/dev/null 2>&1; then
      docker rm --force --volumes "$container"
    fi
    ;;
  *) echo 'Usage: mongodb.sh start|diagnose|stop' >&2; exit 2 ;;
esac
