#!/usr/bin/env bash
set -euo pipefail

# Debian cron does not inherit the container's environment — a cron job only
# gets HOME/LOGNAME/PATH/SHELL. Write the variables the job needs as
# crontab assignment lines so cron exports them into the job's environment.
{ echo "BUFFERBLOAT_TARGET=${BUFFERBLOAT_TARGET}"
  echo "PUSHGATEWAY_URL=${PUSHGATEWAY_URL}"
  echo "${BUFFERBLOAT_CRON} cd /app && /usr/local/bin/python -m jobs.bufferbloat.run >> /var/log/cron.log 2>&1"
  echo ""; } | crontab -

touch /var/log/cron.log
cron
tail -f /var/log/cron.log
