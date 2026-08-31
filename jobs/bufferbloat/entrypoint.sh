#!/usr/bin/env bash
set -euo pipefail

echo "${BUFFERBLOAT_CRON} cd /app && /usr/local/bin/python -m jobs.bufferbloat.run >> /var/log/cron.log 2>&1" > /etc/cron.d/bufferbloat
echo "" >> /etc/cron.d/bufferbloat
chmod 0644 /etc/cron.d/bufferbloat
crontab /etc/cron.d/bufferbloat

touch /var/log/cron.log
cron
tail -f /var/log/cron.log
