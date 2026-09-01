#!/usr/bin/env bash
# Renders config files that cannot read environment variables themselves.
# Run after editing .env, and again whenever an address in .env changes.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Start with: cp .env.example .env" >&2
  exit 1
fi

# Parse .env without sourcing it. Values like `6 */1 * * *` are valid cron
# expressions but would be glob-expanded and executed by `.` / `source`.
# This reads keys and values literally, and strips optional surrounding quotes
# so both `VAR=value` and `VAR="value"` work — Compose accepts both too.
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|'#'*) continue ;;
    *=*) ;;
    *) continue ;;
  esac
  key=${line%%=*}
  val=${line#*=}
  case "$key" in
    [A-Za-z_][A-Za-z0-9_]*) ;;
    *) continue ;;
  esac
  val=${val%\"} ; val=${val#\"}
  val=${val%\'} ; val=${val#\'}
  printf -v "$key" '%s' "$val"
done < .env

fail=0

require() {
  local name=$1
  if [ -z "${!name:-}" ]; then
    echo "ERROR: $name is empty in .env" >&2
    fail=1
  fi
}

# Values with no safe default — the stack silently measures nothing without them.
require GATEWAY_IP
require PIHOLE_HOST
require NIC_DEVICE
require SMOKEPING_TARGETS
require GRAFANA_ADMIN_PASSWORD

# The modem exporter is optional, but if enabled it needs somewhere to connect.
if [ "${MB8611_ENABLED:-false}" = "true" ]; then
  require MB8611_HOST
  require MB8611_PASS
  if [ "${MB8611_INTERVAL_SECONDS:-60}" -lt 60 ] 2>/dev/null; then
    echo "ERROR: MB8611_INTERVAL_SECONDS below 60 risks wedging the modem" >&2
    fail=1
  fi
fi

if [ "$fail" -ne 0 ]; then
  echo >&2
  echo "Fix the values above, then re-run $0" >&2
  exit 1
fi

# Warn rather than fail: the stack still runs, these features just stay empty.
if [ -z "${SPEEDTEST_API_TOKEN:-}" ]; then
  echo "NOTE: SPEEDTEST_API_TOKEN is empty — throughput panels stay empty until"
  echo "      you create a token in the speedtest-tracker UI and re-run this."
fi
if [ -z "${PIHOLE_APP_PASSWORD:-}" ]; then
  echo "NOTE: PIHOLE_APP_PASSWORD is empty — the DNS client dashboard stays empty."
fi

render() {
  local template=$1 output=$2
  # envsubst would be cleaner but is not installed everywhere; keep it portable.
  sed -e "s|\${PIHOLE_HOST}|${PIHOLE_HOST}|g" \
      -e "s|\${NIC_DEVICE}|${NIC_DEVICE}|g" \
      "$template" > "$output"
  echo "rendered $output"
}

render prometheus/targets/dns.yml.template prometheus/targets/dns.yml

echo
echo "Setup complete. Next:"
echo "  ./scripts/validate.sh"
echo "  docker compose up -d"
