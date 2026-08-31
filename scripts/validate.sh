#!/usr/bin/env bash
set -euo pipefail

fail=0

echo "==> docker compose config"
if docker compose config >/dev/null; then
  echo "    OK"
else
  echo "    FAIL"; fail=1
fi

echo "==> prometheus config"
if [ -f prometheus/prometheus.yml ]; then
  # Check if docker daemon is available
  set +e
  docker info >/dev/null 2>&1
  daemon_rc=$?
  set -e

  if [ $daemon_rc -ne 0 ]; then
    echo "    SKIP (docker daemon unavailable)"
  elif docker run --rm -v "$PWD/prometheus:/etc/prometheus:ro" \
      --entrypoint promtool prom/prometheus:v2.53.0 \
      check config /etc/prometheus/prometheus.yml; then
    echo "    OK"
  else
    echo "    FAIL"; fail=1
  fi
fi

echo "==> python tests"
set +e
python3 -m pytest -q
rc=$?
set -e
if [ $rc -eq 0 ] || [ $rc -eq 5 ]; then
  echo "    OK"
else
  echo "    FAIL"; fail=1
fi

exit $fail
