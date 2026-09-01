# home-network-monitor — Design

**Date:** 2026-08-31
**Status:** Draft, pending review
**Host:** `apollo` (Debian 12, kernel 6.1, x86_64)

---

## 1. Problem

Slow page loads and noticeable buffering on the home network. Existing measurement is a
`speedtest-tracker` container running hourly, reporting ~920 Mbps average against a
1.2 Gbps Comcast contract. That number was assumed to indicate an ISP shortfall.

It does not. See Findings.

The real question — *why does traffic feel slow* — is not answerable with the data
currently collected, because throughput is not the failing dimension.

## 2. Findings that shaped this design

These were measured or verified during design, not assumed.

**2.1 The 920 Mbps figure is a measurement artifact, not an ISP problem.**
`apollo`'s only physical NIC is `enp7s0` at **1000 Mbps**. Theoretical TCP max on 1 GbE
after protocol overhead is ~941 Mbps. 920 / 941 = **97.8% of wire speed** — an excellent
result. The hourly speedtest has been reporting "my NIC is full," and is structurally
incapable of validating a 1.2 Gbps contract. All other interfaces listed by
`/sys/class/net/*/speed` (docker0, veth, tap, mpqemubr0) are virtual and their reported
speeds are meaningless.

**2.2 Buffering is a latency symptom, not a bandwidth symptom.**
Buffering and slow page loads are produced by latency, jitter, packet loss, bufferbloat,
or DNS delay. An hourly throughput sample measures none of these. This reframing is the
basis of the entire collector selection.

**2.3 Physical path is 1 GbE end to end.**

```
modem (MB8611, 2.5G port)
  --2.5G-- BE400 WAN
           BE400 LAN: 1x 2.5G (unused), 3x 1G
  --1G--   unmanaged switch 1
  --1G--   unmanaged switch 2
  --1G--   apollo (enp7s0)
```

Consequence: `apollo` cannot measure above ~940 Mbps under any configuration that keeps
the current cabling. A 2.5GbE NIC alone would not help — both switches are 1G.

**2.4 Router is the wireless ceiling.**
TP-Link Archer BE400 is **dual-band Wi-Fi 7 (2.4 + 5 GHz), no 6 GHz**. No 6 GHz means no
320 MHz channels; max is 160 MHz on 5 GHz, and in practice often 80 MHz due to DFS radar
avoidance and neighbour congestion. Realistic single-client throughput: ~900 Mbps–1.3 Gbps
best case, ~500–800 Mbps typical, ~200–500 Mbps through walls. No wireless client will
reliably reach 1.2 Gbps.

Also relevant: TP-Link consumer firmware offers basic QoS, not fq_codel/cake. If
bufferbloat is confirmed, the standard SQM fix may not be available on this router.

**2.5 Per-host traffic attribution is structurally impossible without hardware change.**
Wi-Fi clients never traverse the switches — they go client → BE400 → modem. The only
vantage point that sees all hosts pre-NAT is inside the router. A mirror on the
modem↔router link would show only NAT'd traffic, where every host appears as one IP.
Pi-hole DNS logs are therefore the only available per-client signal, and they measure
**query counts, not bytes**.

**2.6 Existing speedtest-tracker deployment has three issues.**
Deployed with unsubstituted placeholder volume paths (`/path/to/data`,
`/path/to-custom-ssl-keys`), so data persists to literally-named host directories.
`APP_URL=apollo.local` lacks scheme and port, which breaks Laravel-generated asset and
redirect URLs. Its `APP_KEY` was disclosed in plaintext during design and must be rotated.

**2.7 The switch chain and cabling are healthy — suspect eliminated.**
`ip -s link show enp7s0` after 332 GB / 261M packets received: RX errors 0, TX errors 0,
carrier 0, collisions 0, missed 0. RX dropped 28 (1 in 9.3 million — noise floor,
typically unsupported protocol frames). A failing switch or marginal cable produces CRC
errors and carrier transitions; there are none. The two unmanaged switches and the cabling
between router and apollo are not the cause.

Side note: `enp7s0` runs `qdisc fq_codel`, so apollo's own egress is already
bufferbloat-managed. This does not address WAN bufferbloat — that queue lives on the
router's uplink — but it confirms apollo is not contributing.

## 3. Goals

1. Determine why the network feels slow — identify which hop is at fault
2. Continuously measure latency, jitter, loss, and bufferbloat
3. Surface DOCSIS physical-layer health as evidence usable in a Comcast support call
4. Keep 30 days of history
5. Repo is the source of truth; stack is reproducible from a clone plus `.env`
6. Inform the pending 2 Gbps upgrade decision with data rather than assumption

## 4. Non-goals

- Alerting (deliberately deferred; dashboards only for now)
- IDS / "strange traffic" detection — without flow data this produces mostly false
  positives on a home network
- Per-host byte-level attribution — requires hardware change, declined
- Long-term storage / downsampling beyond 30 days
- High availability — single host by definition
- TLS, ingress, or any internet-facing exposure

## 5. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Runtime | **Docker Compose**, not Kubernetes | Single node. CNI overlay in the measurement path corrupts latency and throughput data (extra hop, MTU 1450, conntrack). `network_mode: host` is correct-by-default in compose. kube-prometheus-stack costs ~1.5–2.5 GB RAM to monitor a cluster nobody asked about. Same failure domain either way on one node. |
| Visibility approach | Active probing, software only | No managed switch, no topology change. Hardware path deliberately deferred. |
| Alerting | None initially | User choice. Alertmanager is an easy later addition. |
| Retention | 30 days | User choice. ~2–5 GB. |
| Speedtest | Reuse existing `speedtest-tracker`, bridge to Prometheus | Preserves existing history and UI. Avoids two independent jobs saturating a 1 GbE link on separate schedules and corrupting each other. |
| Metrics backend | Prometheus | PromQL, file_sd, exporter ecosystem. Alternative (Telegraf/InfluxDB) adds a second storage system for no gain here. |

## 6. Architecture

Two network modes, split deliberately.

```
        +--------- host network (measurement plane) ----------+
        |  smokeping_prober   blackbox_exporter               |
        |  node_exporter      bufferbloat job                 |
        +---------------+---------------------+---------------+
                        | scraped             | pushed
        +---------------v---------------------v---------------+
  bridge|  prometheus  <---- pushgateway                       |
   net  |      ^                                              |
        |      | scrapes                                      |
        |  mb8611-exporter   pihole-exporter                   |
        |  speedtest-tracker + speedtest-bridge                |
        |      ^                                              |
        |   grafana ---> prometheus (provisioned datasource)   |
        +-----------------------------------------------------+
```

**Host network** for anything measuring latency or throughput: no bridge NAT, no MTU
reduction, no conntrack in the path, and `NET_RAW` available for ICMP.
**Bridge network** for everything else: isolation and service DNS.
Prometheus reaches host-network exporters via `host-gateway`.

**Two collection patterns:**
- *Pull* — cheap fast probes (blackbox, smokeping, node, mb8611, pihole) as normal targets
- *Push* — slow expensive jobs (bufferbloat) via Pushgateway. These take 30–120s and
  saturate the link; running them as scrape targets means scrape timeouts and an interval
  fighting job duration.

### Scrape cadence

| Target | Interval | Rationale |
|---|---|---|
| smokeping ICMP | continuous | loss and jitter need real sample density |
| blackbox DNS | 30s | Pi-hole vs upstream resolve time |
| blackbox HTTP | 60s | reachability, TLS handshake |
| node_exporter | 30s | apollo's own NIC saturation and error counters |
| mb8611 | 60s (hard floor) | modem HNAP login per scrape; see Risk 10.1 |
| pihole v6 | 30s | cheap API |
| speedtest-tracker | `6 */1 * * *` (existing) | throughput regression detector |
| bufferbloat | `36 * * * *` | offset from speedtest to avoid collision |

Bufferbloat at 60-minute cadence, minute 36. Each run degrades the link ~30s. Cadence is
configurable via `BUFFERBLOAT_CRON`.

## 7. Collectors

| Component | Image | Network | Provides |
|---|---|---|---|
| smokeping_prober | `quay.io/superq/smokeping-prober` | host | Continuous ICMP histograms — real loss %, real jitter. Primary latency source. |
| blackbox_exporter | `prom/blackbox-exporter` | host | DNS resolve time, HTTP/TLS handshake, reachability |
| node_exporter | `prom/node-exporter` | host | apollo NIC throughput **and error/drop counters** |
| mb8611-exporter | custom (`exporters/mb8611/`) | bridge | DOCSIS per-channel SNR, power, uncorrectable codewords, T3/T4 timeouts |
| pihole-exporter | v6-compatible, pinned | bridge | per-client query rate, block rate, upstream resolve latency |
| speedtest-tracker | `lscr.io/linuxserver/speedtest-tracker` | bridge | existing hourly Ookla run + UI |
| speedtest-bridge | custom (`exporters/speedtest-bridge/`) | bridge | reads tracker API, exposes Prometheus metrics |
| bufferbloat job | custom (`jobs/bufferbloat/`) | host | idle vs loaded RTT delta |

**Why smokeping_prober rather than blackbox ICMP alone:** blackbox sends one ping per
scrape. At 15s intervals that is 4 samples/minute — far too coarse to measure loss or
jitter honestly. smokeping_prober pings continuously and exports latency histograms.

**Probe targets** (six, each isolating a different suspect):
BE400 gateway, modem `192.168.100.1`, Pi-hole, `1.1.1.1`, `8.8.8.8`, one CDN edge.

## 8. Metrics

Pushed and custom metrics have no upstream convention, so names are fixed here:

```
bufferbloat_idle_rtt_seconds{target}
bufferbloat_loaded_rtt_seconds{target,direction}
bufferbloat_grade                              # 0-4, waveform-style
bufferbloat_last_run_timestamp_seconds
speedtest_download_bits_per_second
speedtest_upload_bits_per_second
speedtest_ping_seconds
speedtest_last_run_timestamp_seconds
mb8611_channel_snr_db{channel,direction}
mb8611_channel_power_dbmv{channel,direction}
mb8611_uncorrectable_codewords_total{channel}
mb8611_t3_timeouts_total
mb8611_scrape_success
```

Representative queries:

```promql
# real loss, from continuous pings
1 - (rate(smokeping_response_duration_seconds_count[5m])
     / rate(smokeping_requests_total[5m]))

# bufferbloat delta, milliseconds
(bufferbloat_loaded_rtt_seconds - bufferbloat_idle_rtt_seconds) * 1000

# the Comcast evidence panel
rate(mb8611_uncorrectable_codewords_total[15m])

# switch/cable fault detection
rate(node_network_receive_errs_total{device="enp7s0"}[5m])
```

## 9. Dashboards

### D1 — Triage: "is it the internet, or is it me?"

Stat tiles: WAN loss %, loaded-latency delta, uncorrectable rate, last speedtest, Pi-hole up.

Primary panel: **all six probe targets on one latency graph**. Read by shape:
- All six spike together → LAN or apollo itself
- Flat to the modem, spikes beyond → Comcast
- Only Pi-hole spikes → DNS
- Only CDN spikes → peering/congestion to that service

Secondary panel: **NIC health** — `node_network_receive_errs_total`,
`_transmit_errs_total`, `_receive_drop_total` on `enp7s0`, as rates. This is the only
visibility into the two unmanaged switches, which are L2 and cannot be probed directly.
Nonzero and climbing CRC or error counters indicate a bad cable or failing switch.

### D2 — Modem / DOCSIS health

Per-channel SNR heatmap, downstream/upstream power, uncorrectable codeword rate,
T3/T4 timeout counters. Threshold bands drawn on panels:

| Metric | Healthy | Marginal | Bad |
|---|---|---|---|
| DS power | −7 to +7 dBmV | ±7–10 | beyond ±10 |
| DS SNR (256QAM) | > 35 dB | 30–35 | < 30 |
| US power | 35–49 dBmV | 49–52 | > 52 |
| Uncorrectables | flat | slow climb | rate rising with buffering |
| T3/T4 timeouts | 0 | any | repeated |

This is the dashboard that justifies a service call. Comcast dismisses "my speedtest is
slow"; they do not dismiss their own modem's error counters.

### D3 — Bufferbloat & throughput

Idle vs loaded RTT, delta as a trend, speedtest series, and **node_exporter NIC
utilization overlaid** so measurements taken while apollo's own workloads saturated the
1 GbE link can be discarded.

Interpretation: delta < 30ms fine; 30–100ms noticeable on calls; > 100ms explains video
buffering.

### D4 — DNS & clients

Pi-hole per-client query rate, top talkers, block rate, upstream resolve p50/p95.

Panel titles state explicitly that this is **query counts, not bytes** — it finds a
misbehaving IoT device polling DNS; it will not find a device streaming 4K.

## 10. Risks

**10.1 MB8611 exporter — highest value, highest risk.**
The modem speaks HNAP1: a SOAP-style API with HMAC challenge-response auth, returning
channel data as delimited strings requiring parsing. Known hazard: aggressive polling can
wedge the MB8611's web server, requiring a modem reboot — i.e. monitoring causes an outage.

Mandatory mitigations:
- 60s minimum interval, never lower
- single-flight; never overlapping requests
- hard timeout, fail-soft (export `mb8611_scrape_success 0`, do not crash-loop)
- `MB8611_ENABLED=false` kill switch in `.env`

Build approach: standalone script run by hand for an hour before entering compose. If a
community exporter works, pin it by digest — they are unmaintained and firmware updates
break them.

**10.2 speedtest-tracker API shape is version-dependent.** Confirm the endpoint by hand
against the running instance before writing the bridge around it.

**10.3 Pushgateway staleness.** Pushed metrics persist indefinitely after a job stops, so
a dead bufferbloat job renders as permanently good results. Every push includes
`*_last_run_timestamp_seconds`; D3 displays its age.

**10.4 "No data" rendering as zero.** An exporter being down must not look like a healthy
0. Every dashboard row carries a companion `up{}` indicator.

**10.5 Disk exhaustion.** `--storage.tsdb.retention.time=30d` plus
`--storage.tsdb.retention.size=8GB`, whichever hits first.

## 11. Security

- `.env` gitignored; `.env.example` committed with empty values
- Rotate the disclosed `speedtest-tracker` `APP_KEY`. Generate a fresh one with
  `openssl rand -base64 32` and prefix the result with `base64:`. Rotation invalidates
  existing sessions; for this app that means logging in again.
- Check shell history for the leaked key: `grep -n "APP_KEY" ~/.bash_history`
- Pi-hole v6: use a scoped **app password**, not the admin password, so it can be revoked
  independently
- **Nothing in this stack is port-forwarded.** Prometheus ships with no authentication and
  will answer anyone who can reach it. All services bind to LAN only. Remote access, if
  wanted later, is Tailscale or a VPN — never a port forward.

## 12. Repo layout

```
home-network-monitor/
├── docker-compose.yml
├── .env.example
├── .gitignore                    # .env, data/
├── prometheus/
│   ├── prometheus.yml            # scrape jobs, file_sd only
│   └── targets/{dns,http}.yml   # ICMP targets live in smokeping/targets.yml
├── blackbox/blackbox.yml
├── smokeping/targets.yml
├── grafana/provisioning/
│   ├── datasources/prometheus.yml
│   └── dashboards/{d1,d2,d3,d4}.json
├── exporters/mb8611/
├── exporters/speedtest-bridge/
├── jobs/bufferbloat/
└── scripts/validate.sh
```

Probe targets use Prometheus `file_sd`, not inline config — adding a target is a one-line
edit that hot-reloads without a restart.

Grafana dashboards live in `provisioning/` as JSON so the repo, not Grafana's sqlite DB,
is the source of truth.

## 13. Bring-up phases

| Phase | Scope | Verification | Est. |
|---|---|---|---|
| 1 | prometheus, grafana, node_exporter, smokeping, blackbox | all targets `up`; latency graph populated; NIC error counters visible | ~1h |
| 2 | mb8611 exporter | SNR + uncorrectables populate; no modem instability | risky |
| 3 | pushgateway + bufferbloat job | pushed metrics appear after first run | ~1h |
| 4 | fold in speedtest-tracker, migrate `/path/to/data`, API bridge | history preserved; throughput in Prometheus | ~1h |
| 5 | provision D1–D4 dashboards | panels render against real data | ~2h |
| 6 | *(optional)* wireless probe on a spare device | wired vs wireless latency on one graph | needs hardware |

**Phase 1 may end the project.** It covers the switch/cable suspect (NIC errors) and the
DNS suspect, and yields real loss and jitter. Phases 2–5 should not begin until Phase 1
data has been reviewed for at least a day.

## 14. Testing

- `docker compose config` validates compose syntax
- `promtool check config` validates Prometheus config
- Per-exporter smoke test: curl `/metrics`, assert expected metric names present
- Dashboard JSON validated by successful Grafana provisioning load
- `scripts/validate.sh` runs all of the above

## 15. Suspect ranking (hypotheses this stack tests)

1. DOCSIS plant errors — D2
2. Bufferbloat / upstream saturation — D3
3. Wi-Fi contention (dual-band, no 6 GHz escape) — Phase 6
4. DNS via single Pi-hole — D1/D4
5. Actual bandwidth shortage — least likely; currently at 97.8% of wire

**Eliminated:** switch chain / cabling fault — ruled out by clean NIC counters, see §2.7.
The D1 NIC health panel is retained anyway, since it costs nothing (node_exporter already
collects the counters) and turns a one-time check into ongoing regression detection.

## 16. Open questions

These are deferred with stated defaults, not blockers.

1. **Bufferbloat cadence** — defaulted to 60 min at minute 36. Confirm or change.
2. **Wireless probe** — Phase 6 requires a spare always-on wireless device. Not yet identified.
3. **Cable-bypass test — deprioritized.** Originally proposed to test the switch chain.
   §2.7 ruled that out with counter data, so this is no longer a diagnostic. It remains
   relevant only as the physical-feasibility check for question 5.
4. ~~**NIC error counters not yet read**~~ — **RESOLVED 2026-08-31.** Counters clean;
   see §2.7. `ethtool` is not installed on apollo (`apt install ethtool`) but `ip -s link`
   already answered the question.
5. **BE400 2.5G LAN port** — is a direct run from apollo physically feasible? Determines
   whether the measurement ceiling can ever be lifted above 940 Mbps.

## 17. Hardware decisions this data will inform

**2 Gbps upgrade — not recommended before data exists.** On current hardware the number of
devices able to exceed 1 Gbps is zero. The BE400 has one 2.5G LAN port; both switches are
1G; no wireless client can reach 2 Gbps; apollo's NIC is 1G. Realistic cost to actually use
a 2 Gbps tier: ~$25 NIC, $125–185 in 2.5G switches or a direct run, $150–250 for a router
with multiple 2.5G ports, ~$200–400 for tri-band Wi-Fi 7 with 6 GHz, plus possible
DOCSIS 4.0 modem or Comcast gateway requirements — which are market-specific and must be
confirmed with Comcast for this service address, since the MB8611 is DOCSIS 3.1.

Additionally: cable upstream is heavily asymmetric. If buffering is caused by upstream
saturation, doubling downstream changes nothing.

## 18. Success criteria

1. Within two weeks, the data identifies which of the six suspects is responsible — or
   rules out all six
2. The 2 Gbps decision is made on measured evidence, not assumption
3. If DOCSIS errors are present, D2 produces a screenshot usable in a Comcast support call
4. Stack reproduces from a clone plus `.env` on a fresh host
