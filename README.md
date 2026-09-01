# home-network-monitor

A self-hosted monitoring stack for finding out *why* a home internet
connection feels slow — when a speed test says it shouldn't be.

Throughput is the metric everyone measures and usually the wrong one. Buffering,
stalled page loads, and bad video calls are almost always caused by latency,
jitter, packet loss, bufferbloat, DNS delay, or cable-plant errors. This stack
measures those continuously and puts them on four dashboards.

## What it collects

| Signal | Collector | Answers |
|---|---|---|
| Latency, jitter, loss per hop | smokeping_prober | Which hop is at fault — your LAN, your router, your ISP, or the path to a service |
| DNS resolve time | blackbox_exporter | Is your local resolver slower than upstream |
| HTTP/TLS handshake time | blackbox_exporter | Is reachability or negotiation the problem |
| Latency under load (bufferbloat) | cron job → Pushgateway | Why video buffers while throughput looks fine |
| Throughput | speedtest-tracker → bridge | Regression detection, not SLA proof (see below) |
| NIC errors and saturation | node_exporter | Bad cable or switch; and whether the monitoring host skewed its own measurements |
| DOCSIS plant health | custom exporter (Motorola MB8611) | SNR, power levels, uncorrectable codewords — the evidence a cable ISP acts on |
| Per-client DNS query rates | Pi-hole exporter | A device hammering DNS (counts, not bytes) |

## Two things worth understanding before you deploy

**A speed test cannot exceed your slowest link.** If the host running this stack
has a 1 GbE NIC, throughput measurements cap around 940 Mbps no matter what you
pay for. That is a measurement artifact, not a fault. Treat the throughput panel
as "did this get dramatically worse", not as proof of your contracted rate. To
validate a multi-gig plan you need a multi-gig path end to end — NIC, switches,
and router ports.

**Per-host bandwidth attribution is not possible here.** Wireless clients never
traverse a wired switch, and traffic past the router is NAT'd. Pi-hole query
counts are the only per-client signal available without a managed switch or a
router you control the routing plane on — and query counts are not bytes. A
device streaming 4K makes few queries; a chatty IoT poller makes thousands.

## Requirements

- A Linux host with Docker and Docker Compose
- A DNS resolver on your LAN worth monitoring (Pi-hole, AdGuard, or similar)
- Optional: a Motorola MB8611 cable modem, for the DOCSIS dashboard

## Setup

    cp .env.example .env
    # fill in every value in .env — see docs/DEPLOYMENT.md
    ./scripts/setup.sh
    docker compose up -d

`setup.sh` renders the config files that cannot read environment variables
directly. Re-run it whenever you change an address in `.env`.

**Read [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) before the first deploy.** It
covers the values you must supply, the credential rotation you should do, the
hardware-specific checks, and the phased bring-up order.

## Validate

    ./scripts/validate.sh

Checks Compose syntax, Prometheus config, the rendered target files, and the
Python test suite.

## Ports

All LAN-only. None of these should ever be port-forwarded — Prometheus in
particular ships with no authentication and will answer anyone who can reach it.
For remote access use a VPN or an overlay network such as Tailscale.

| Service | Port |
|---|---|
| Grafana | 3000 |
| Prometheus | 9090 |
| Pushgateway | 9091 |
| speedtest-tracker | 8080 |

## Layout

    docker-compose.yml          all services
    prometheus/                 scrape config; targets/ is rendered from .env
    blackbox/                   probe module definitions
    grafana/provisioning/       datasource and the four dashboards, as code
    exporters/mb8611/           DOCSIS exporter (custom)
    exporters/speedtest_bridge/ speedtest-tracker API → Prometheus (custom)
    jobs/bufferbloat/           latency-under-load measurement (custom)
    scripts/                    setup and validation

Dashboards are provisioned from files with `allowUiUpdates: false` — this repo
is the source of truth, not Grafana's database. Edit the JSON, don't click.
