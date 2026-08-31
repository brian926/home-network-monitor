# home-network-monitor

Monitoring stack for diagnosing home network latency, bufferbloat, DOCSIS
plant health, and DNS timing.

Design: `docs/superpowers/specs/2026-08-31-home-network-monitor-design.md`
Plan: `docs/superpowers/plans/2026-08-31-home-network-monitor.md`

## Setup

    cp .env.example .env
    # fill in .env
    docker compose up -d

## Validate

    ./scripts/validate.sh

## Ports (LAN only — never port-forward these)

| Service | Port |
|---|---|
| Grafana | 3000 |
| Prometheus | 9090 |
| Pushgateway | 9091 |
| speedtest-tracker | 8080 |
