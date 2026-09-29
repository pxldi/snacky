#!/usr/bin/env bash
# (Lives in ci/, not scripts/: the Dockerfile copies scripts/, so an edit there would rebuild the BLS stage.)
# Run an image the way the cluster does (read-only root, a fresh /data, no
# Tandoor or openGym) and exercise it with ci/smoke_test.py.
# Usage: ci/smoke-image.sh IMAGE
set -euo pipefail

image=${1:?usage: smoke-image.sh IMAGE}
here=$(cd "$(dirname "$0")" && pwd)

# The cluster mounts /data for uid 1000; a tmpfs owned by that uid stands in for it.
container=$(docker run -d --read-only \
  --tmpfs /data:rw,uid=1000,gid=1000,mode=0755 \
  -p 127.0.0.1::8000 -p 127.0.0.1::8080 "$image")
trap 'docker logs "$container" 2>&1 | tail -n 40; docker rm -f "$container" >/dev/null' EXIT

mcp_url="http://$(docker port "$container" 8000/tcp | head -n 1)"
web_url="http://$(docker port "$container" 8080/tcp | head -n 1)"

for _ in $(seq 1 60); do
  if curl -fsS "$mcp_url/health" >/dev/null 2>&1; then
    break
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$container")" != true ]; then
    echo "FAIL: the container exited before /health answered" >&2
    exit 1
  fi
  sleep 1
done
curl -fsS "$mcp_url/health"
echo

python3 "$here/smoke_test.py" "$mcp_url" "$web_url"
