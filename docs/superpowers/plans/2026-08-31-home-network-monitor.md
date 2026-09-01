# home-network-monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Docker Compose observability stack on `apollo` that identifies why the home network buffers, by measuring latency, jitter, loss, bufferbloat, DOCSIS physical-layer health, and DNS timing.

**Architecture:** Prometheus scrapes latency/DNS/host collectors running on the host network (no CNI or bridge NAT in the measurement path) and two custom exporters on a bridge network. Slow saturating jobs push to a Pushgateway instead of being scraped. Grafana provisions four dashboards from JSON in the repo.

**Tech Stack:** Docker Compose, Prometheus, Grafana, smokeping_prober, blackbox_exporter, node_exporter, Pushgateway, Python 3.11 (`prometheus_client`, `requests`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-home-network-monitor-design.md`

## Global Constraints

- **Deploy host:** `apollo`, Debian 12, kernel 6.1, x86_64. Physical NIC is `enp7s0` at 1000 Mbps.
- **Repo host:** development happens in `C:\Users\fatim\Code\home-network-monitor` (Windows); apollo pulls from `git@github.com:brian926/home-network-monitor.git`. All Python tests are pure functions with no network or filesystem dependency, so they run identically on both.
- **Measurement ceiling:** ~940 Mbps. Never write a check, threshold, or dashboard that treats a sub-1.2 Gbps speedtest result as a fault.
- **MB8611 polling floor: 60 seconds. Never lower.** Aggressive polling wedges the modem's web server and takes the internet down.
- **Every image pinned to an explicit version tag.** Unmaintained community images pinned by digest.
- **`.env` is never committed.** `.env.example` carries empty values only.
- **No port forwarding, ever.** All services bind to the LAN. Prometheus has no authentication.
- **Metric names are fixed by spec §8** and must match exactly. Deviation breaks the dashboards.
- **Python:** 3.11+, type hints on all public functions, standard library preferred.
- **Commits:** conventional commits (`feat:`, `fix:`, `chore:`, `test:`, `docs:`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `docker-compose.yml` | Service definitions; grows one section per task |
| `.env.example` | Credential and tunable template, empty values |
| `.gitignore` | Excludes `.env`, `data/`, `.venv/`, `__pycache__/` |
| `prometheus/prometheus.yml` | Scrape jobs; targets by `file_sd` only |
| `prometheus/targets/dns.yml` | Blackbox DNS probe targets |
| `prometheus/targets/http.yml` | Blackbox HTTP probe targets |
| `blackbox/blackbox.yml` | Blackbox prober module definitions |
| `smokeping/targets.env` | ICMP target list, consumed as CLI args |
| `grafana/provisioning/datasources/prometheus.yml` | Datasource, provisioned |
| `grafana/provisioning/dashboards/provider.yml` | Dashboard provider config |
| `grafana/provisioning/dashboards/d1-triage.json` | D1 dashboard |
| `grafana/provisioning/dashboards/d2-docsis.json` | D2 dashboard |
| `grafana/provisioning/dashboards/d3-bufferbloat.json` | D3 dashboard |
| `grafana/provisioning/dashboards/d4-dns.json` | D4 dashboard |
| `exporters/mb8611/hnap.py` | HNAP auth primitives — pure functions |
| `exporters/mb8611/parser.py` | DOCSIS channel string parsing — pure functions |
| `exporters/mb8611/client.py` | HTTP client, single-flight, timeouts |
| `exporters/mb8611/exporter.py` | prometheus_client collector + main |
| `exporters/mb8611/tests/` | pytest suite |
| `exporters/speedtest_bridge/parser.py` | Tracker API response → metrics, pure |
| `exporters/speedtest_bridge/exporter.py` | HTTP client + collector |
| `jobs/bufferbloat/grade.py` | Grade calculation + ping parsing, pure |
| `jobs/bufferbloat/render.py` | Prometheus text exposition rendering, pure |
| `jobs/bufferbloat/run.py` | Saturation orchestration + push |
| `scripts/validate.sh` | Config validation entrypoint |

Split rationale: pure functions live in their own modules so they can be tested without network, containers, or a live modem. Every custom component follows the same three-file shape — pure logic, I/O client, exporter wiring.

---

## Task 1: Repo scaffolding and validation harness

**Files:**
- Create: `.gitignore`, `.env.example`, `scripts/validate.sh`, `README.md`, `pytest.ini`
- Test: `scripts/validate.sh` is its own verification

**Interfaces:**
- Consumes: nothing
- Produces: `scripts/validate.sh` — all later tasks add a check to it. `.env.example` — all later tasks add variables to it.

- [ ] **Step 1: Create `.gitignore`**

```gitignore
.env
data/
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 2: Create `.env.example`**

```bash
# Grafana
GRAFANA_ADMIN_PASSWORD=

# Motorola MB8611 modem
MB8611_ENABLED=true
MB8611_HOST=192.168.100.1
MB8611_USER=admin
MB8611_PASS=
MB8611_INTERVAL_SECONDS=60

# Pi-hole v6 — use a scoped app password, not the admin password
PIHOLE_HOST=
PIHOLE_APP_PASSWORD=

# speedtest-tracker
SPEEDTEST_APP_KEY=
SPEEDTEST_APP_URL=http://apollo.local:8080
SPEEDTEST_SCHEDULE=6 */1 * * *
SPEEDTEST_TZ=America/New_York
SPEEDTEST_API_TOKEN=

# bufferbloat job
BUFFERBLOAT_CRON=36 * * * *
BUFFERBLOAT_TARGET=1.1.1.1
PUSHGATEWAY_URL=http://pushgateway:9091
```

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
testpaths = exporters jobs
python_files = test_*.py
```

- [ ] **Step 4: Create `scripts/validate.sh`**

```bash
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
  if docker run --rm -v "$PWD/prometheus:/etc/prometheus:ro" \
      --entrypoint promtool prom/prometheus:v2.53.0 \
      check config /etc/prometheus/prometheus.yml; then
    echo "    OK"
  else
    echo "    FAIL"; fail=1
  fi
fi

echo "==> python tests"
if python3 -m pytest -q; then
  echo "    OK"
else
  echo "    FAIL"; fail=1
fi

exit $fail
```

- [ ] **Step 5: Make it executable and verify it runs**

Run:
```bash
chmod +x scripts/validate.sh
./scripts/validate.sh
```
Expected: compose check fails (no `docker-compose.yml` yet). That is the correct failing state — it proves the harness detects a missing config rather than silently passing.

- [ ] **Step 6: Write `README.md`**

```markdown
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
```

- [ ] **Step 7: Commit**

```bash
git add .gitignore .env.example pytest.ini scripts/validate.sh README.md
git commit -m "chore: scaffold repo, env template, and validation harness"
```

---

## Task 2: Phase 1 core — Prometheus, Grafana, node_exporter

**Files:**
- Create: `docker-compose.yml`, `prometheus/prometheus.yml`, `grafana/provisioning/datasources/prometheus.yml`
- Modify: `scripts/validate.sh` (no change needed — checks already cover this)

**Interfaces:**
- Consumes: `.env.example` variables from Task 1
- Produces: compose services `prometheus`, `grafana`, `node-exporter`. Prometheus reachable at `http://apollo:9090`, scrape config extended by later tasks. The `hostnet` pattern (`network_mode: host` + `host-gateway`) is reused by Tasks 3, 4, 6.

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
services:
  prometheus:
    image: prom/prometheus:v2.53.0
    restart: unless-stopped
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=30d
      - --storage.tsdb.retention.size=8GB
      - --web.enable-lifecycle
    volumes:
      - ./prometheus:/etc/prometheus:ro
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks: [monitoring]

  grafana:
    image: grafana/grafana:11.1.0
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana-data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on: [prometheus]
    networks: [monitoring]

  node-exporter:
    image: prom/node-exporter:v1.8.1
    restart: unless-stopped
    network_mode: host
    pid: host
    command:
      - --path.rootfs=/host
      - --collector.netdev
    volumes:
      - /:/host:ro,rslave

volumes:
  prometheus-data:
  grafana-data:

networks:
  monitoring:
```

- [ ] **Step 2: Create `prometheus/prometheus.yml`**

```yaml
global:
  scrape_interval: 30s
  scrape_timeout: 10s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: node
    scrape_interval: 30s
    static_configs:
      - targets: ["host.docker.internal:9100"]
```

- [ ] **Step 3: Create `grafana/provisioning/datasources/prometheus.yml`**

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

- [ ] **Step 4: Validate config before starting anything**

Run: `./scripts/validate.sh`
Expected: compose check OK, promtool check OK, pytest reports no tests collected (exit 5 — acceptable at this stage).

- [ ] **Step 5: Start the stack on apollo and verify targets are up**

Run:
```bash
cp .env.example .env   # fill GRAFANA_ADMIN_PASSWORD first
docker compose up -d prometheus grafana node-exporter
sleep 20
curl -s localhost:9090/api/v1/targets | grep -o '"health":"[a-z]*"' | sort | uniq -c
```
Expected: two targets, both `"health":"up"`.

- [ ] **Step 6: Verify the NIC error counters that ruled out the switch chain are now recorded**

Run:
```bash
curl -s 'localhost:9090/api/v1/query?query=node_network_receive_errs_total{device="enp7s0"}' \
  | grep -o '"value":\[[^]]*\]'
```
Expected: a result with value `0` — matching the `ip -s link` reading in spec §2.7.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml prometheus/prometheus.yml grafana/provisioning/datasources/prometheus.yml
git commit -m "feat: add prometheus, grafana, and node_exporter core stack"
```

---

## Task 3: smokeping_prober — continuous latency, jitter, loss

**Files:**
- Modify: `docker-compose.yml`, `prometheus/prometheus.yml`
- Create: `smokeping/targets.env`

**Interfaces:**
- Consumes: `monitoring` network and Prometheus scrape config from Task 2
- Produces: metrics `smokeping_requests_total{host}` and `smokeping_response_duration_seconds{host}` (histogram) on port 9374. D1 and D3 depend on these names.

- [ ] **Step 1: Create `smokeping/targets.env` documenting the six probe targets**

```bash
# Six probe targets, each isolating a different suspect (spec §7).
# Passed as CLI args to smokeping_prober in docker-compose.yml.
# Replace GATEWAY_IP and PIHOLE_IP with your actual addresses.
#
#   192.168.1.1      BE400 gateway   — is the router itself slow?
#   192.168.100.1    MB8611 modem    — is the modem reachable and responsive?
#   192.168.1.2      Pi-hole         — is DNS host healthy?
#   1.1.1.1          Cloudflare      — is the WAN path healthy?
#   8.8.8.8          Google          — second opinion on the WAN
#   1.0.0.1          Cloudflare alt  — distinguishes single-target flakiness
```

- [ ] **Step 2: Add the service to `docker-compose.yml`**

Insert after the `node-exporter` service:

```yaml
  smokeping:
    image: quay.io/superq/smokeping-prober:v0.8.1
    restart: unless-stopped
    network_mode: host
    cap_add:
      - NET_RAW
    command:
      - --privileged
      - 192.168.1.1
      - 192.168.100.1
      - 192.168.1.2
      - 1.1.1.1
      - 8.8.8.8
      - 1.0.0.1
```

Note: replace `192.168.1.1` and `192.168.1.2` with the real gateway and Pi-hole addresses before starting.

- [ ] **Step 3: Add the scrape job to `prometheus/prometheus.yml`**

Append under `scrape_configs`:

```yaml
  - job_name: smokeping
    scrape_interval: 15s
    static_configs:
      - targets: ["host.docker.internal:9374"]
```

- [ ] **Step 4: Validate and start**

Run:
```bash
./scripts/validate.sh
docker compose up -d smokeping
sleep 30
curl -s localhost:9374/metrics | grep -c '^smokeping_requests_total'
```
Expected: `6` — one series per target.

- [ ] **Step 5: Verify loss and jitter queries return data**

Run:
```bash
curl -sG localhost:9090/api/v1/query \
  --data-urlencode 'query=1 - (rate(smokeping_response_duration_seconds_count[5m]) / rate(smokeping_requests_total[5m]))' \
  | head -c 400
```
Expected: JSON with `"status":"success"` and six result entries. Values near `0` mean no loss.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml prometheus/prometheus.yml smokeping/targets.env
git commit -m "feat: add smokeping_prober for continuous latency, jitter, and loss"
```

---

## Task 4: blackbox_exporter — DNS and HTTP timing

**Files:**
- Modify: `docker-compose.yml`, `prometheus/prometheus.yml`
- Create: `blackbox/blackbox.yml`, `prometheus/targets/dns.yml`, `prometheus/targets/http.yml`

**Interfaces:**
- Consumes: Prometheus scrape config from Task 2
- Produces: `probe_success`, `probe_duration_seconds`, `probe_dns_lookup_time_seconds`, `probe_http_duration_seconds` on port 9115. D1 and D4 depend on these.

- [ ] **Step 1: Create `blackbox/blackbox.yml`**

```yaml
modules:
  dns_pihole:
    prober: dns
    timeout: 5s
    dns:
      query_name: "cloudflare.com"
      query_type: "A"
      transport_protocol: "udp"
      preferred_ip_protocol: "ip4"

  dns_upstream:
    prober: dns
    timeout: 5s
    dns:
      query_name: "cloudflare.com"
      query_type: "A"
      transport_protocol: "udp"
      preferred_ip_protocol: "ip4"

  http_2xx:
    prober: http
    timeout: 10s
    http:
      valid_status_codes: [200]
      method: GET
      preferred_ip_protocol: "ip4"
```

- [ ] **Step 2: Create `prometheus/targets/dns.yml`**

```yaml
- targets:
    - 192.168.1.2      # Pi-hole — replace with real address
  labels:
    module: dns_pihole
    role: local_dns

- targets:
    - 1.1.1.1
    - 8.8.8.8
  labels:
    module: dns_upstream
    role: upstream_dns
```

- [ ] **Step 3: Create `prometheus/targets/http.yml`**

```yaml
- targets:
    - https://www.cloudflare.com
    - https://www.google.com
  labels:
    module: http_2xx
    role: cdn_edge
```

- [ ] **Step 4: Add the service to `docker-compose.yml`**

Insert after the `smokeping` service:

```yaml
  blackbox:
    image: prom/blackbox-exporter:v0.25.0
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./blackbox:/config:ro
    command:
      - --config.file=/config/blackbox.yml
```

- [ ] **Step 5: Add both scrape jobs to `prometheus/prometheus.yml`**

Append under `scrape_configs`:

```yaml
  - job_name: blackbox_dns
    scrape_interval: 30s
    metrics_path: /probe
    file_sd_configs:
      - files: ["/etc/prometheus/targets/dns.yml"]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [module]
        target_label: __param_module
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: host.docker.internal:9115

  - job_name: blackbox_http
    scrape_interval: 60s
    metrics_path: /probe
    file_sd_configs:
      - files: ["/etc/prometheus/targets/http.yml"]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [module]
        target_label: __param_module
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: host.docker.internal:9115
```

- [ ] **Step 6: Validate and start**

Run:
```bash
./scripts/validate.sh
docker compose up -d blackbox
docker compose kill -s SIGHUP prometheus
sleep 40
curl -sG localhost:9090/api/v1/query \
  --data-urlencode 'query=probe_success' | grep -o '"role":"[a-z_]*"' | sort | uniq -c
```
Expected: entries for `local_dns`, `upstream_dns`, and `cdn_edge`.

- [ ] **Step 7: Verify the DNS comparison that tests suspect 4**

Run:
```bash
curl -sG localhost:9090/api/v1/query \
  --data-urlencode 'query=probe_dns_lookup_time_seconds' | head -c 400
```
Expected: values for Pi-hole and both upstreams. If Pi-hole's value is materially higher than upstream, that is spec §15 suspect 4 confirmed.

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml prometheus/prometheus.yml blackbox/ prometheus/targets/
git commit -m "feat: add blackbox exporter for DNS and HTTP probe timing"
```

---

## Task 5: MB8611 DOCSIS exporter

Highest value, highest risk (spec §10.1). The modem's web server can be wedged by aggressive polling, which takes the internet down. Discovery comes first, then pure-function TDD against a captured fixture.

**Files:**
- Create: `exporters/mb8611/hnap.py`, `exporters/mb8611/parser.py`, `exporters/mb8611/client.py`, `exporters/mb8611/exporter.py`, `exporters/mb8611/Dockerfile`, `exporters/mb8611/requirements.txt`, `exporters/mb8611/tests/test_hnap.py`, `exporters/mb8611/tests/test_parser.py`, `exporters/mb8611/tests/fixtures/downstream.txt`
- Modify: `docker-compose.yml`, `prometheus/prometheus.yml`, `.env.example`

**Interfaces:**
- Consumes: `MB8611_*` variables from Task 1's `.env.example`
- Produces:
  - `hnap.compute_private_key(public_key: str, password: str, challenge: str) -> str`
  - `hnap.compute_login_password(private_key: str, challenge: str) -> str`
  - `hnap.compute_auth_header(private_key: str, soap_action: str, now_ms: int) -> str`
  - `parser.parse_downstream(raw: str) -> list[dict]`
  - `parser.parse_upstream(raw: str) -> list[dict]`
  - Metrics per spec §8: `mb8611_channel_snr_db`, `mb8611_channel_power_dbmv`, `mb8611_uncorrectable_codewords_total`, `mb8611_t3_timeouts_total`, `mb8611_scrape_success`. D2 depends on these.

- [ ] **Step 1: Discovery — capture one real response before writing any parser**

The MB8611 returns channel data as caret-delimited rows joined by `|+|`. Field order must be confirmed against your firmware, not assumed. Run this once on apollo:

```bash
python3 - <<'PY'
import hashlib, hmac, json, time, urllib3, requests
urllib3.disable_warnings()

HOST, USER, PASS = "192.168.100.1", "admin", "YOUR_MODEM_PASSWORD"
URL = f"https://{HOST}/HNAP1/"
s = requests.Session(); s.verify = False

def md5(key, data):
    return hmac.new(key.encode(), data.encode(), hashlib.md5).hexdigest().upper()

r = s.post(URL, json={"Login": {"Action": "request", "Username": USER,
        "LoginPassword": "", "Captcha": "", "PrivateLogin": "LoginPassword"}},
    headers={"SOAPAction": '"http://purenetworks.com/HNAP1/Login"'}, timeout=10)
lr = r.json()["LoginResponse"]
challenge, pubkey, cookie = lr["Challenge"], lr["PublicKey"], lr["Cookie"]
privkey = md5(pubkey + PASS, challenge)
s.cookies.set("uid", cookie); s.cookies.set("PrivateKey", privkey)

ts = str(int(time.time() * 1000) % 2000000000000)
action = '"http://purenetworks.com/HNAP1/Login"'
s.post(URL, json={"Login": {"Action": "login", "Username": USER,
        "LoginPassword": md5(privkey, challenge), "Captcha": "",
        "PrivateLogin": "LoginPassword"}},
    headers={"SOAPAction": action,
             "HNAP_AUTH": f"{md5(privkey, ts + action)} {ts}"}, timeout=10)

ts = str(int(time.time() * 1000) % 2000000000000)
action = '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"'
r = s.post(URL, json={"GetMultipleHNAPs": {
        "GetMotoStatusDownstreamChannelInfo": "",
        "GetMotoStatusUpstreamChannelInfo": "",
        "GetMotoStatusConnectionInfo": ""}},
    headers={"SOAPAction": action,
             "HNAP_AUTH": f"{md5(privkey, ts + action)} {ts}"}, timeout=10)
print(json.dumps(r.json(), indent=2))
PY
```

Expected: JSON containing `MotoConnDownstreamChannel` and `MotoConnUpstreamChannel`, each a long caret-delimited string.

**If this fails or the modem becomes unresponsive: stop. Reboot the modem, set `MB8611_ENABLED=false`, and skip to Task 6.** The rest of the stack does not depend on this task.

- [ ] **Step 2: Save the real downstream string as a test fixture**

Copy the `MotoConnDownstreamChannel` value into `exporters/mb8611/tests/fixtures/downstream.txt`. If discovery could not run, use this representative sample so the parser can still be built and tested:

```
1^Locked^QAM256^5^567.0^ 1.5^40.9^1234^5^|+|2^Locked^QAM256^6^573.0^ 1.7^40.7^1100^0^|+|3^Locked^QAM256^7^579.0^ 1.4^41.1^980^12^
```

- [ ] **Step 3: Write the failing parser tests**

Create `exporters/mb8611/tests/test_parser.py`:

```python
from pathlib import Path

from exporters.mb8611.parser import parse_downstream, parse_upstream

FIXTURE = Path(__file__).parent / "fixtures" / "downstream.txt"


def test_parse_downstream_returns_one_dict_per_channel():
    channels = parse_downstream(FIXTURE.read_text())
    assert len(channels) == 3


def test_parse_downstream_extracts_typed_fields():
    first = parse_downstream(FIXTURE.read_text())[0]
    assert first["channel"] == "1"
    assert first["lock_status"] == "Locked"
    assert first["modulation"] == "QAM256"
    assert first["frequency_mhz"] == 567.0
    assert first["power_dbmv"] == 1.5
    assert first["snr_db"] == 40.9
    assert first["corrected"] == 1234
    assert first["uncorrected"] == 5


def test_parse_downstream_strips_padding_whitespace():
    # The modem pads the power field with a leading space.
    channels = parse_downstream("1^Locked^QAM256^5^567.0^ 1.5^40.9^1234^5^")
    assert channels[0]["power_dbmv"] == 1.5


def test_parse_downstream_ignores_malformed_rows():
    channels = parse_downstream("1^Locked^QAM256^5^567.0^ 1.5^40.9^1234^5^|+|garbage")
    assert len(channels) == 1


def test_parse_downstream_handles_empty_input():
    assert parse_downstream("") == []


def test_parse_upstream_extracts_typed_fields():
    raw = "1^Locked^SC-QAM^1^5120^35.6^45.5^"
    first = parse_upstream(raw)[0]
    assert first["channel"] == "1"
    assert first["lock_status"] == "Locked"
    assert first["frequency_mhz"] == 35.6
    assert first["power_dbmv"] == 45.5
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python3 -m pytest exporters/mb8611/tests/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exporters.mb8611.parser'`

- [ ] **Step 5: Implement the parser**

Create `exporters/mb8611/parser.py`:

```python
"""Parsing for MB8611 HNAP channel strings.

The modem returns channel tables as caret-delimited rows joined by "|+|",
with inconsistent padding whitespace around numeric fields.
"""

ROW_SEPARATOR = "|+|"
FIELD_SEPARATOR = "^"

DOWNSTREAM_MIN_FIELDS = 9
UPSTREAM_MIN_FIELDS = 7


def _rows(raw: str) -> list[list[str]]:
    rows = []
    for row in raw.split(ROW_SEPARATOR):
        row = row.strip()
        if not row:
            continue
        rows.append([field.strip() for field in row.split(FIELD_SEPARATOR)])
    return rows


def parse_downstream(raw: str) -> list[dict]:
    """Parse a downstream channel table.

    Field order: channel, lock status, modulation, channel id, frequency MHz,
    power dBmV, SNR dB, corrected codewords, uncorrected codewords.
    """
    channels = []
    for fields in _rows(raw):
        if len(fields) < DOWNSTREAM_MIN_FIELDS:
            continue
        try:
            channels.append({
                "channel": fields[0],
                "lock_status": fields[1],
                "modulation": fields[2],
                "channel_id": fields[3],
                "frequency_mhz": float(fields[4]),
                "power_dbmv": float(fields[5]),
                "snr_db": float(fields[6]),
                "corrected": int(fields[7]),
                "uncorrected": int(fields[8]),
            })
        except ValueError:
            continue
    return channels


def parse_upstream(raw: str) -> list[dict]:
    """Parse an upstream channel table.

    Field order: channel, lock status, type, channel id, symbol rate,
    frequency MHz, power dBmV.
    """
    channels = []
    for fields in _rows(raw):
        if len(fields) < UPSTREAM_MIN_FIELDS:
            continue
        try:
            channels.append({
                "channel": fields[0],
                "lock_status": fields[1],
                "channel_type": fields[2],
                "channel_id": fields[3],
                "symbol_rate": fields[4],
                "frequency_mhz": float(fields[5]),
                "power_dbmv": float(fields[6]),
            })
        except ValueError:
            continue
    return channels
```

Create empty `exporters/__init__.py` and `exporters/mb8611/__init__.py` so the test imports resolve.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest exporters/mb8611/tests/test_parser.py -v`
Expected: 6 passed.

**If the fixture came from your real modem and a test fails, the field order differs on your firmware.** Adjust the indices in `parser.py` to match the captured data, and update the test's expected values. The test encodes your modem's actual format — that is the point of capturing it first.

- [ ] **Step 7: Write the failing HNAP auth tests**

Create `exporters/mb8611/tests/test_hnap.py`:

```python
import re

from exporters.mb8611.hnap import (
    compute_auth_header,
    compute_login_password,
    compute_private_key,
)

HEX32 = re.compile(r"^[0-9A-F]{32}$")


def test_private_key_is_uppercase_hex_digest():
    key = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    assert HEX32.match(key)


def test_private_key_is_deterministic():
    a = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    b = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    assert a == b


def test_private_key_changes_with_password():
    a = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    b = compute_private_key("PUBKEY", "hunter3", "CHALLENGE")
    assert a != b


def test_private_key_changes_with_challenge():
    a = compute_private_key("PUBKEY", "hunter2", "CHALLENGE_A")
    b = compute_private_key("PUBKEY", "hunter2", "CHALLENGE_B")
    assert a != b


def test_login_password_is_uppercase_hex_digest():
    assert HEX32.match(compute_login_password("PRIVKEY", "CHALLENGE"))


def test_auth_header_is_digest_space_timestamp():
    header = compute_auth_header("PRIVKEY", "GetMultipleHNAPs", 1735689600000)
    digest, timestamp = header.split(" ")
    assert HEX32.match(digest)
    assert timestamp == "1735689600000"


def test_auth_header_timestamp_wraps_at_modulus():
    header = compute_auth_header("PRIVKEY", "GetMultipleHNAPs", 2000000000001)
    assert header.split(" ")[1] == "1"
```

Note on test design: these assert structural properties and invariants rather than hardcoded digests. A hardcoded MD5 expectation would only prove the test author ran the same code, and the modem is the real oracle for correctness here. The invariants that matter — right shape, deterministic, sensitive to each input, correct timestamp handling — are all covered.

- [ ] **Step 8: Run the tests to verify they fail**

Run: `python3 -m pytest exporters/mb8611/tests/test_hnap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exporters.mb8611.hnap'`

- [ ] **Step 9: Implement the HNAP primitives**

Create `exporters/mb8611/hnap.py`:

```python
"""HNAP1 authentication primitives for the Motorola MB8611.

The modem uses HMAC-MD5 challenge-response. MD5 is used here because the
device's firmware requires it; it is not a security choice we control, and
the credentials never leave the LAN.
"""

import hashlib
import hmac

TIMESTAMP_MODULUS = 2000000000000
SOAP_NAMESPACE = "http://purenetworks.com/HNAP1"


def _hmac_md5(key: str, data: str) -> str:
    return hmac.new(key.encode(), data.encode(), hashlib.md5).hexdigest().upper()


def compute_private_key(public_key: str, password: str, challenge: str) -> str:
    """Derive the session private key from the login challenge."""
    return _hmac_md5(public_key + password, challenge)


def compute_login_password(private_key: str, challenge: str) -> str:
    """Derive the hashed password sent in the login request."""
    return _hmac_md5(private_key, challenge)


def compute_auth_header(private_key: str, soap_action: str, now_ms: int) -> str:
    """Build the HNAP_AUTH header value: '<digest> <timestamp>'."""
    timestamp = str(now_ms % TIMESTAMP_MODULUS)
    quoted_action = f'"{SOAP_NAMESPACE}/{soap_action}"'
    return f"{_hmac_md5(private_key, timestamp + quoted_action)} {timestamp}"
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `python3 -m pytest exporters/mb8611/tests/ -v`
Expected: 13 passed.

- [ ] **Step 11: Commit the tested pure logic before touching the network**

```bash
git add exporters/__init__.py exporters/mb8611/
git commit -m "feat: add MB8611 HNAP auth and DOCSIS channel parsing"
```

- [ ] **Step 12: Implement the safety-constrained client**

Create `exporters/mb8611/client.py`:

```python
"""HTTP client for the MB8611.

Safety constraints from spec §10.1 are enforced here, not by the caller:
aggressive polling wedges the modem's web server and takes the internet
down. Single-flight, hard timeouts, and fail-soft are mandatory.
"""

import threading
import time

import requests
import urllib3

from . import hnap

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REQUEST_TIMEOUT_SECONDS = 10
MINIMUM_INTERVAL_SECONDS = 60


class MB8611Client:
    def __init__(self, host: str, username: str, password: str) -> None:
        self._url = f"https://{host}/HNAP1/"
        self._username = username
        self._password = password
        self._lock = threading.Lock()
        self._last_fetch = 0.0
        self._cached: dict | None = None

    def _login(self, session: requests.Session) -> str:
        action = '"http://purenetworks.com/HNAP1/Login"'
        response = session.post(
            self._url,
            json={"Login": {"Action": "request", "Username": self._username,
                            "LoginPassword": "", "Captcha": "",
                            "PrivateLogin": "LoginPassword"}},
            headers={"SOAPAction": action},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()["LoginResponse"]

        private_key = hnap.compute_private_key(
            payload["PublicKey"], self._password, payload["Challenge"])
        session.cookies.set("uid", payload["Cookie"])
        session.cookies.set("PrivateKey", private_key)

        session.post(
            self._url,
            json={"Login": {"Action": "login", "Username": self._username,
                            "LoginPassword": hnap.compute_login_password(
                                private_key, payload["Challenge"]),
                            "Captcha": "", "PrivateLogin": "LoginPassword"}},
            headers={
                "SOAPAction": action,
                "HNAP_AUTH": hnap.compute_auth_header(
                    private_key, "Login", int(time.time() * 1000)),
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).raise_for_status()
        return private_key

    def fetch_status(self) -> dict | None:
        """Fetch channel status, or None on any failure.

        Single-flight: concurrent callers get the cached result rather than
        issuing a second request. Rate-limited to MINIMUM_INTERVAL_SECONDS.
        """
        if not self._lock.acquire(blocking=False):
            return self._cached

        try:
            if time.time() - self._last_fetch < MINIMUM_INTERVAL_SECONDS:
                return self._cached

            session = requests.Session()
            session.verify = False
            try:
                private_key = self._login(session)
                response = session.post(
                    self._url,
                    json={"GetMultipleHNAPs": {
                        "GetMotoStatusDownstreamChannelInfo": "",
                        "GetMotoStatusUpstreamChannelInfo": "",
                        "GetMotoStatusConnectionInfo": ""}},
                    headers={
                        "SOAPAction":
                            '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"',
                        "HNAP_AUTH": hnap.compute_auth_header(
                            private_key, "GetMultipleHNAPs",
                            int(time.time() * 1000)),
                    },
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                self._cached = response.json()["GetMultipleHNAPsResponse"]
            except Exception:
                self._cached = None
            finally:
                session.close()
                self._last_fetch = time.time()

            return self._cached
        finally:
            self._lock.release()
```

- [ ] **Step 13: Implement the exporter**

Create `exporters/mb8611/exporter.py`:

```python
"""Prometheus exporter for MB8611 DOCSIS status."""

import os
import time

from prometheus_client import Gauge, start_http_server

from .client import MB8611Client
from .parser import parse_downstream, parse_upstream

SNR = Gauge("mb8611_channel_snr_db", "Downstream SNR in dB",
            ["channel", "direction"])
POWER = Gauge("mb8611_channel_power_dbmv", "Channel power in dBmV",
              ["channel", "direction"])
UNCORRECTABLE = Gauge("mb8611_uncorrectable_codewords_total",
                      "Uncorrectable codewords", ["channel"])
T3_TIMEOUTS = Gauge("mb8611_t3_timeouts_total", "T3 timeout count")
SCRAPE_SUCCESS = Gauge("mb8611_scrape_success",
                       "1 if the last modem scrape succeeded, else 0")


def collect(client: MB8611Client) -> None:
    status = client.fetch_status()
    if not status:
        SCRAPE_SUCCESS.set(0)
        return

    downstream_raw = status.get("GetMotoStatusDownstreamChannelInfoResponse", {})
    for channel in parse_downstream(
            downstream_raw.get("MotoConnDownstreamChannel", "")):
        SNR.labels(channel["channel"], "downstream").set(channel["snr_db"])
        POWER.labels(channel["channel"], "downstream").set(
            channel["power_dbmv"])
        UNCORRECTABLE.labels(channel["channel"]).set(channel["uncorrected"])

    upstream_raw = status.get("GetMotoStatusUpstreamChannelInfoResponse", {})
    for channel in parse_upstream(
            upstream_raw.get("MotoConnUpstreamChannel", "")):
        POWER.labels(channel["channel"], "upstream").set(channel["power_dbmv"])

    SCRAPE_SUCCESS.set(1)


def main() -> None:
    if os.environ.get("MB8611_ENABLED", "true").lower() != "true":
        print("MB8611_ENABLED is not true; exporter idling.", flush=True)
        SCRAPE_SUCCESS.set(0)
        start_http_server(9611)
        while True:
            time.sleep(3600)

    client = MB8611Client(
        host=os.environ["MB8611_HOST"],
        username=os.environ["MB8611_USER"],
        password=os.environ["MB8611_PASS"],
    )
    interval = max(60, int(os.environ.get("MB8611_INTERVAL_SECONDS", "60")))

    start_http_server(9611)
    while True:
        collect(client)
        time.sleep(interval)


if __name__ == "__main__":
    main()
```

Note the `max(60, ...)` — the polling floor is enforced in code, not left to configuration discipline.

- [ ] **Step 14: Create `exporters/mb8611/requirements.txt` and `Dockerfile`**

`requirements.txt`:
```
prometheus_client==0.20.0
requests==2.32.3
```

`Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY __init__.py hnap.py parser.py client.py exporter.py /app/exporters/mb8611/
RUN touch /app/exporters/__init__.py

EXPOSE 9611
CMD ["python", "-m", "exporters.mb8611.exporter"]
```

- [ ] **Step 15: Add the service and scrape job**

In `docker-compose.yml`, after `blackbox`:

```yaml
  mb8611-exporter:
    build: ./exporters/mb8611
    restart: unless-stopped
    environment:
      MB8611_ENABLED: ${MB8611_ENABLED}
      MB8611_HOST: ${MB8611_HOST}
      MB8611_USER: ${MB8611_USER}
      MB8611_PASS: ${MB8611_PASS}
      MB8611_INTERVAL_SECONDS: ${MB8611_INTERVAL_SECONDS}
    networks: [monitoring]
```

In `prometheus/prometheus.yml`:

```yaml
  - job_name: mb8611
    scrape_interval: 60s
    static_configs:
      - targets: ["mb8611-exporter:9611"]
```

- [ ] **Step 16: Start and verify — watch the modem closely**

Run:
```bash
docker compose up -d --build mb8611-exporter
sleep 90
docker compose logs --tail 20 mb8611-exporter
curl -s localhost:9090/api/v1/query?query=mb8611_scrape_success | grep -o '"value":\[[^]]*\]'
```
Expected: `mb8611_scrape_success` is `1`.

Then confirm the modem is still healthy:
```bash
curl -sk -o /dev/null -w '%{http_code}\n' https://192.168.100.1/
```
Expected: `200`. **If this hangs or the internet drops, set `MB8611_ENABLED=false`, `docker compose up -d mb8611-exporter`, and reboot the modem.**

- [ ] **Step 17: Commit**

```bash
git add exporters/mb8611/ docker-compose.yml prometheus/prometheus.yml
git commit -m "feat: add MB8611 DOCSIS exporter with polling safety limits"
```

---

## Task 6: Pushgateway and bufferbloat job

**Files:**
- Create: `jobs/bufferbloat/grade.py`, `jobs/bufferbloat/render.py`, `jobs/bufferbloat/run.py`, `jobs/bufferbloat/Dockerfile`, `jobs/bufferbloat/entrypoint.sh`, `jobs/bufferbloat/tests/test_grade.py`, `jobs/bufferbloat/tests/test_render.py`
- Modify: `docker-compose.yml`, `prometheus/prometheus.yml`

**Interfaces:**
- Consumes: `BUFFERBLOAT_CRON`, `BUFFERBLOAT_TARGET`, `PUSHGATEWAY_URL` from Task 1
- Produces:
  - `grade.parse_ping_rtts(output: str) -> list[float]`
  - `grade.percentile(values: list[float], p: float) -> float`
  - `grade.grade_from_delta_ms(delta_ms: float) -> str`
  - `grade.grade_to_number(grade: str) -> int`
  - `render.render_metrics(target: str, idle_ms: float, loaded_download_ms: float, loaded_upload_ms: float, timestamp: int) -> str`
  - Metrics per spec §8: `bufferbloat_idle_rtt_seconds`, `bufferbloat_loaded_rtt_seconds`, `bufferbloat_grade`, `bufferbloat_last_run_timestamp_seconds`. D3 depends on these.

- [ ] **Step 1: Write the failing grade tests**

Create `jobs/bufferbloat/tests/test_grade.py`:

```python
import pytest

from jobs.bufferbloat.grade import (
    grade_from_delta_ms,
    grade_to_number,
    parse_ping_rtts,
    percentile,
)

PING_OUTPUT = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=11.8 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=14.1 ms

--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 11.800/12.733/14.100/0.982 ms
"""


def test_parse_ping_rtts_extracts_all_samples():
    assert parse_ping_rtts(PING_OUTPUT) == [12.3, 11.8, 14.1]


def test_parse_ping_rtts_ignores_summary_lines():
    # The summary line contains "ms" but no "time=" and must not be counted.
    assert len(parse_ping_rtts(PING_OUTPUT)) == 3


def test_parse_ping_rtts_handles_total_loss():
    assert parse_ping_rtts("3 packets transmitted, 0 received") == []


def test_percentile_returns_interpolated_value():
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 25.0


def test_percentile_of_single_value():
    assert percentile([42.0], 0.95) == 42.0


def test_percentile_of_empty_list_raises():
    with pytest.raises(ValueError):
        percentile([], 0.95)


@pytest.mark.parametrize("delta_ms,expected", [
    (0.0, "A+"),
    (4.9, "A+"),
    (5.0, "A"),
    (29.9, "A"),
    (30.0, "B"),
    (59.9, "B"),
    (60.0, "C"),
    (199.9, "C"),
    (200.0, "D"),
    (399.9, "D"),
    (400.0, "F"),
    (5000.0, "F"),
])
def test_grade_from_delta_ms(delta_ms, expected):
    assert grade_from_delta_ms(delta_ms) == expected


def test_grade_to_number_orders_best_to_worst():
    grades = ["A+", "A", "B", "C", "D", "F"]
    numbers = [grade_to_number(g) for g in grades]
    assert numbers == [0, 1, 2, 3, 4, 5]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest jobs/bufferbloat/tests/test_grade.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobs.bufferbloat.grade'`

- [ ] **Step 3: Implement grade calculation**

Create `jobs/bufferbloat/grade.py`:

```python
"""Bufferbloat grading, following the Waveform scale.

Grade is based on the increase in round-trip time under load versus idle,
not on absolute latency: a connection with 80 ms idle RTT and no increase
under load is not bufferbloated.
"""

GRADE_THRESHOLDS_MS = [
    (5.0, "A+"),
    (30.0, "A"),
    (60.0, "B"),
    (200.0, "C"),
    (400.0, "D"),
]
WORST_GRADE = "F"
GRADE_NUMBERS = {"A+": 0, "A": 1, "B": 2, "C": 3, "D": 4, "F": 5}


def parse_ping_rtts(output: str) -> list[float]:
    """Extract per-packet RTTs in milliseconds from `ping` output."""
    rtts = []
    for line in output.splitlines():
        if "time=" not in line:
            continue
        try:
            rtts.append(float(line.split("time=")[1].split()[0]))
        except (IndexError, ValueError):
            continue
    return rtts


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile. `p` is a fraction between 0 and 1."""
    if not values:
        raise ValueError("percentile() requires at least one value")
    if len(values) == 1:
        return values[0]

    ordered = sorted(values)
    position = p * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def grade_from_delta_ms(delta_ms: float) -> str:
    """Map a latency increase under load to a Waveform-style letter grade."""
    for threshold, grade in GRADE_THRESHOLDS_MS:
        if delta_ms < threshold:
            return grade
    return WORST_GRADE


def grade_to_number(grade: str) -> int:
    """Map a letter grade to 0 (best) through 5 (worst) for graphing."""
    return GRADE_NUMBERS[grade]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest jobs/bufferbloat/tests/test_grade.py -v`
Expected: 19 passed.

- [ ] **Step 5: Write the failing render tests**

Create `jobs/bufferbloat/tests/test_render.py`:

```python
from jobs.bufferbloat.render import render_metrics


def test_render_emits_all_required_metric_names():
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    for name in [
        "bufferbloat_idle_rtt_seconds",
        "bufferbloat_loaded_rtt_seconds",
        "bufferbloat_grade",
        "bufferbloat_last_run_timestamp_seconds",
    ]:
        assert name in text


def test_render_converts_milliseconds_to_seconds():
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    assert 'bufferbloat_idle_rtt_seconds{target="1.1.1.1"} 0.012' in text


def test_render_labels_both_load_directions():
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    assert 'direction="download"' in text
    assert 'direction="upload"' in text


def test_render_grades_on_the_worse_direction():
    # Download delta 33 ms (grade B), upload delta 3 ms (grade A+).
    # The worse of the two must win.
    text = render_metrics("1.1.1.1", 12.0, 45.0, 15.0, 1735689600)
    assert "bufferbloat_grade 2" in text


def test_render_ends_with_trailing_newline():
    # The Prometheus text format requires the body to end in a newline.
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    assert text.endswith("\n")
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `python3 -m pytest jobs/bufferbloat/tests/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobs.bufferbloat.render'`

- [ ] **Step 7: Implement rendering**

Create `jobs/bufferbloat/render.py`:

```python
"""Prometheus text exposition format rendering for the bufferbloat job."""

from .grade import grade_from_delta_ms, grade_to_number


def render_metrics(
    target: str,
    idle_ms: float,
    loaded_download_ms: float,
    loaded_upload_ms: float,
    timestamp: int,
) -> str:
    """Render one bufferbloat result as Prometheus text exposition.

    The reported grade reflects the worse of the two load directions, since
    a connection that collapses only on upload is still bufferbloated.
    """
    download_delta = loaded_download_ms - idle_ms
    upload_delta = loaded_upload_ms - idle_ms
    worst_delta = max(download_delta, upload_delta)
    grade = grade_to_number(grade_from_delta_ms(worst_delta))

    lines = [
        "# HELP bufferbloat_idle_rtt_seconds Idle round-trip time",
        "# TYPE bufferbloat_idle_rtt_seconds gauge",
        f'bufferbloat_idle_rtt_seconds{{target="{target}"}} {idle_ms / 1000:.6g}',
        "# HELP bufferbloat_loaded_rtt_seconds Round-trip time under load",
        "# TYPE bufferbloat_loaded_rtt_seconds gauge",
        f'bufferbloat_loaded_rtt_seconds{{target="{target}",direction="download"}}'
        f" {loaded_download_ms / 1000:.6g}",
        f'bufferbloat_loaded_rtt_seconds{{target="{target}",direction="upload"}}'
        f" {loaded_upload_ms / 1000:.6g}",
        "# HELP bufferbloat_grade Waveform-style grade, 0 best to 5 worst",
        "# TYPE bufferbloat_grade gauge",
        f"bufferbloat_grade {grade}",
        "# HELP bufferbloat_last_run_timestamp_seconds Unix time of last run",
        "# TYPE bufferbloat_last_run_timestamp_seconds gauge",
        f"bufferbloat_last_run_timestamp_seconds {timestamp}",
    ]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python3 -m pytest jobs/bufferbloat/tests/ -v`
Expected: 24 passed.

- [ ] **Step 9: Commit the tested pure logic**

```bash
git add jobs/
git commit -m "feat: add bufferbloat grading and metric rendering"
```

- [ ] **Step 10: Implement the saturation runner**

Create `jobs/bufferbloat/run.py`:

```python
"""Measure latency under load and push the result to a Pushgateway.

Saturation uses Cloudflare's public speed endpoints rather than a bundled
speedtest binary: no extra dependency, stable URLs, and the same endpoints
browser-based bufferbloat tests use.
"""

import os
import subprocess
import sys
import threading
import time

import requests

from .grade import parse_ping_rtts, percentile
from .render import render_metrics

DOWNLOAD_URL = "https://speed.cloudflare.com/__down?bytes=200000000"
UPLOAD_URL = "https://speed.cloudflare.com/__up"
SATURATION_STREAMS = 8
LOAD_SECONDS = 15
PING_COUNT_IDLE = 10
PING_COUNT_LOADED = 15


def measure_rtt_ms(target: str, count: int) -> float:
    """Return the p95 RTT in milliseconds across `count` pings."""
    result = subprocess.run(
        ["ping", "-c", str(count), "-i", "0.2", target],
        capture_output=True, text=True, timeout=count * 2 + 15,
    )
    rtts = parse_ping_rtts(result.stdout)
    if not rtts:
        raise RuntimeError(f"no ping responses from {target}")
    return percentile(rtts, 0.95)


def _download_stream(stop: threading.Event) -> None:
    try:
        with requests.get(DOWNLOAD_URL, stream=True, timeout=60) as response:
            for _ in response.iter_content(chunk_size=65536):
                if stop.is_set():
                    return
    except Exception:
        return


def _upload_stream(stop: threading.Event) -> None:
    def chunks():
        block = b"0" * 65536
        while not stop.is_set():
            yield block

    try:
        requests.post(UPLOAD_URL, data=chunks(), timeout=60)
    except Exception:
        return


def measure_under_load(target: str, worker) -> float:
    """Run `worker` on N threads to saturate the link, pinging throughout."""
    stop = threading.Event()
    threads = [threading.Thread(target=worker, args=(stop,), daemon=True)
               for _ in range(SATURATION_STREAMS)]
    for thread in threads:
        thread.start()

    time.sleep(2)  # let the streams ramp before sampling
    try:
        return measure_rtt_ms(target, PING_COUNT_LOADED)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)


def main() -> int:
    target = os.environ.get("BUFFERBLOAT_TARGET", "1.1.1.1")
    pushgateway = os.environ.get("PUSHGATEWAY_URL", "http://pushgateway:9091")

    try:
        idle_ms = measure_rtt_ms(target, PING_COUNT_IDLE)
        download_ms = measure_under_load(target, _download_stream)
        time.sleep(5)  # let queues drain between directions
        upload_ms = measure_under_load(target, _upload_stream)
    except Exception as error:
        print(f"bufferbloat run failed: {error}", file=sys.stderr)
        return 1

    body = render_metrics(target, idle_ms, download_ms, upload_ms,
                          int(time.time()))
    response = requests.post(
        f"{pushgateway}/metrics/job/bufferbloat", data=body, timeout=15)
    response.raise_for_status()

    print(f"idle={idle_ms:.1f}ms down={download_ms:.1f}ms up={upload_ms:.1f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11: Create the cron container files**

`jobs/bufferbloat/requirements.txt`:
```
requests==2.32.3
```

`jobs/bufferbloat/entrypoint.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

echo "${BUFFERBLOAT_CRON} cd /app && /usr/local/bin/python -m jobs.bufferbloat.run >> /var/log/cron.log 2>&1" > /etc/cron.d/bufferbloat
echo "" >> /etc/cron.d/bufferbloat
chmod 0644 /etc/cron.d/bufferbloat
crontab /etc/cron.d/bufferbloat

touch /var/log/cron.log
cron
tail -f /var/log/cron.log
```

`jobs/bufferbloat/Dockerfile`:
```dockerfile
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY grade.py render.py run.py /app/jobs/bufferbloat/
RUN touch /app/jobs/__init__.py /app/jobs/bufferbloat/__init__.py

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
```

- [ ] **Step 12: Add Pushgateway and the job to `docker-compose.yml`**

```yaml
  pushgateway:
    image: prom/pushgateway:v1.9.0
    restart: unless-stopped
    ports:
      - "9091:9091"
    networks: [monitoring]

  bufferbloat:
    build: ./jobs/bufferbloat
    restart: unless-stopped
    network_mode: host
    cap_add:
      - NET_RAW
    environment:
      BUFFERBLOAT_CRON: ${BUFFERBLOAT_CRON}
      BUFFERBLOAT_TARGET: ${BUFFERBLOAT_TARGET}
      PUSHGATEWAY_URL: http://localhost:9091
```

- [ ] **Step 13: Add the scrape job to `prometheus/prometheus.yml`**

```yaml
  - job_name: pushgateway
    honor_labels: true
    scrape_interval: 30s
    static_configs:
      - targets: ["pushgateway:9091"]
```

`honor_labels: true` is required — without it Prometheus overwrites the job label on pushed metrics.

- [ ] **Step 14: Run the job once by hand before trusting the schedule**

Run:
```bash
docker compose up -d --build pushgateway bufferbloat
docker compose exec bufferbloat python -m jobs.bufferbloat.run
```
Expected: a line like `idle=12.4ms down=45.1ms up=38.7ms`, and the run takes roughly 45 seconds. Your internet will be slow during it — that is the measurement working.

- [ ] **Step 15: Verify the metrics landed and the grade is sane**

Run:
```bash
curl -sG localhost:9090/api/v1/query \
  --data-urlencode 'query=(bufferbloat_loaded_rtt_seconds - on(target) group_left bufferbloat_idle_rtt_seconds) * 1000' \
  | head -c 400
```
Expected: two results, one per direction, in milliseconds. Over 100 ms is spec §15 suspect 2 confirmed.

- [ ] **Step 16: Commit**

```bash
git add jobs/bufferbloat/ docker-compose.yml prometheus/prometheus.yml
git commit -m "feat: add pushgateway and hourly bufferbloat measurement job"
```

---

## Task 7: Fold in speedtest-tracker and bridge it to Prometheus

**Files:**
- Create: `exporters/speedtest_bridge/parser.py`, `exporters/speedtest_bridge/exporter.py`, `exporters/speedtest_bridge/Dockerfile`, `exporters/speedtest_bridge/requirements.txt`, `exporters/speedtest_bridge/tests/test_parser.py`
- Modify: `docker-compose.yml`, `prometheus/prometheus.yml`

**Interfaces:**
- Consumes: `SPEEDTEST_*` variables from Task 1
- Produces:
  - `parser.parse_latest_result(payload: dict) -> dict`
  - Metrics per spec §8: `speedtest_download_bits_per_second`, `speedtest_upload_bits_per_second`, `speedtest_ping_seconds`, `speedtest_last_run_timestamp_seconds`. D3 depends on these.

- [ ] **Step 1: Migrate the existing data out of the placeholder path**

The running container writes to `/path/to/data`, a literal directory created by the unsubstituted volume flag (spec §2.6). Preserve that history:

```bash
sudo du -sh /path/to/data
mkdir -p ~/home-network-monitor/data/speedtest
sudo cp -a /path/to/data/. ~/home-network-monitor/data/speedtest/
sudo chown -R 1000:1000 ~/home-network-monitor/data/speedtest
docker stop speedtest-tracker && docker rm speedtest-tracker
```

Do not delete `/path/to/data` until Step 8 confirms the history survived.

- [ ] **Step 2: Rotate the disclosed APP_KEY and record the new one**

The existing key was disclosed in plaintext and must not be reused (spec §11).

```bash
echo "base64:$(openssl rand -base64 32)"
```
Put the output in `.env` as `SPEEDTEST_APP_KEY`. Rotation invalidates existing sessions — you will log in to the UI again, and nothing else is affected.

Then check whether the old key is sitting in shell history:
```bash
grep -n "APP_KEY" ~/.bash_history || echo "not in history"
```
If it is, remove those lines and run `history -c` in any shell still holding them in memory.

- [ ] **Step 3: Add the service to `docker-compose.yml`**

```yaml
  speedtest-tracker:
    image: lscr.io/linuxserver/speedtest-tracker:0.21.2
    restart: unless-stopped
    environment:
      PUID: 1000
      PGID: 1000
      APP_KEY: ${SPEEDTEST_APP_KEY}
      APP_URL: ${SPEEDTEST_APP_URL}
      DB_CONNECTION: sqlite
      SPEEDTEST_SCHEDULE: ${SPEEDTEST_SCHEDULE}
      DISPLAY_TIMEZONE: ${SPEEDTEST_TZ}
    volumes:
      - ./data/speedtest:/config
    ports:
      - "8080:80"
    networks: [monitoring]
```

Note `APP_URL` now carries a scheme and port, fixing the second defect in spec §2.6. The `8443` publish and the SSL keys volume are dropped — both were unused.

- [ ] **Step 4: Start it and confirm the history survived the move**

Run:
```bash
docker compose up -d speedtest-tracker
sleep 30
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/
```
Expected: `200`. Open the UI and confirm your historical results are present. If they are, `/path/to/data` can be removed.

- [ ] **Step 5: Discovery — capture the API response shape**

The tracker's API differs between versions (spec §10.2). Create an API token in the UI, put it in `.env` as `SPEEDTEST_API_TOKEN`, then:

```bash
source .env
curl -s -H "Authorization: Bearer ${SPEEDTEST_API_TOKEN}" \
     -H "Accept: application/json" \
     http://localhost:8080/api/v1/results/latest | python3 -m json.tool
```
Expected: JSON with a `data` object containing `download`, `upload`, `ping`, and `created_at`. Note the units — recent versions report bytes per second, older ones bits.

- [ ] **Step 6: Write the failing parser tests**

Create `exporters/speedtest_bridge/tests/test_parser.py`, adjusting the sample to match what Step 5 actually returned:

```python
import pytest

from exporters.speedtest_bridge.parser import parse_latest_result

SAMPLE = {
    "data": {
        "id": 42,
        "ping": 12.345,
        "download": 115000000.0,   # bytes per second
        "upload": 4300000.0,
        "created_at": "2026-08-31T14:06:03.000000Z",
    }
}


def test_parse_converts_bytes_per_second_to_bits():
    result = parse_latest_result(SAMPLE)
    assert result["download_bits_per_second"] == 920000000.0


def test_parse_converts_upload_to_bits():
    result = parse_latest_result(SAMPLE)
    assert result["upload_bits_per_second"] == 34400000.0


def test_parse_converts_ping_milliseconds_to_seconds():
    result = parse_latest_result(SAMPLE)
    assert result["ping_seconds"] == pytest.approx(0.012345)


def test_parse_converts_timestamp_to_unix_epoch():
    result = parse_latest_result(SAMPLE)
    assert result["timestamp"] == 1788185163


def test_parse_raises_on_missing_data_key():
    with pytest.raises(ValueError):
        parse_latest_result({})


def test_parse_raises_on_null_measurement():
    with pytest.raises(ValueError):
        parse_latest_result({"data": {"ping": None, "download": None,
                                      "upload": None, "created_at": None}})
```

- [ ] **Step 7: Run the tests to verify they fail**

Run: `python3 -m pytest exporters/speedtest_bridge/tests/ -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 8: Implement the parser**

Create `exporters/speedtest_bridge/parser.py` (underscore throughout — a hyphenated directory is not a valid Python package name and the test imports would not resolve):

```python
"""Convert speedtest-tracker API responses into metric-ready values."""

from datetime import datetime, timezone

BITS_PER_BYTE = 8


def parse_latest_result(payload: dict) -> dict:
    """Normalise a /api/v1/results/latest response.

    speedtest-tracker reports throughput in bytes per second and ping in
    milliseconds; Prometheus convention is bits per second and seconds.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("response has no 'data' object")

    for field in ("download", "upload", "ping", "created_at"):
        if data.get(field) is None:
            raise ValueError(f"missing measurement field: {field}")

    created = datetime.fromisoformat(
        data["created_at"].replace("Z", "+00:00"))

    return {
        "download_bits_per_second": float(data["download"]) * BITS_PER_BYTE,
        "upload_bits_per_second": float(data["upload"]) * BITS_PER_BYTE,
        "ping_seconds": float(data["ping"]) / 1000.0,
        "timestamp": int(created.replace(tzinfo=timezone.utc).timestamp()),
    }
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python3 -m pytest exporters/speedtest_bridge/tests/ -v`
Expected: 6 passed.

If the unit assertions fail, Step 5's real response uses different units than the sample. Correct the conversion in `parser.py` and the expected values in the test to match your version — the captured response is the authority.

- [ ] **Step 10: Implement the exporter**

Create `exporters/speedtest_bridge/exporter.py`:

```python
"""Prometheus bridge for speedtest-tracker."""

import os
import time

import requests
from prometheus_client import Gauge, start_http_server

from .parser import parse_latest_result

DOWNLOAD = Gauge("speedtest_download_bits_per_second", "Download throughput")
UPLOAD = Gauge("speedtest_upload_bits_per_second", "Upload throughput")
PING = Gauge("speedtest_ping_seconds", "Idle latency reported by speedtest")
LAST_RUN = Gauge("speedtest_last_run_timestamp_seconds",
                 "Unix time of the most recent speedtest result")
SCRAPE_SUCCESS = Gauge("speedtest_bridge_scrape_success",
                       "1 if the last tracker API read succeeded, else 0")

POLL_INTERVAL_SECONDS = 300


def collect(base_url: str, token: str) -> None:
    try:
        response = requests.get(
            f"{base_url}/api/v1/results/latest",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        result = parse_latest_result(response.json())
    except Exception:
        SCRAPE_SUCCESS.set(0)
        return

    DOWNLOAD.set(result["download_bits_per_second"])
    UPLOAD.set(result["upload_bits_per_second"])
    PING.set(result["ping_seconds"])
    LAST_RUN.set(result["timestamp"])
    SCRAPE_SUCCESS.set(1)


def main() -> None:
    base_url = os.environ.get("SPEEDTEST_BASE_URL",
                              "http://speedtest-tracker:80")
    token = os.environ["SPEEDTEST_API_TOKEN"]

    start_http_server(9798)
    while True:
        collect(base_url, token)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
```

Polling every 5 minutes against an hourly-updating source is deliberate: it costs nothing, and it means a fresh result appears in Grafana within 5 minutes rather than up to an hour late.

- [ ] **Step 11: Create the container files**

`exporters/speedtest_bridge/requirements.txt`:
```
prometheus_client==0.20.0
requests==2.32.3
```

`exporters/speedtest_bridge/Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parser.py exporter.py /app/exporters/speedtest_bridge/
RUN touch /app/exporters/__init__.py /app/exporters/speedtest_bridge/__init__.py

EXPOSE 9798
CMD ["python", "-m", "exporters.speedtest_bridge.exporter"]
```

- [ ] **Step 12: Add the service and scrape job**

`docker-compose.yml`:
```yaml
  speedtest-bridge:
    build: ./exporters/speedtest_bridge
    restart: unless-stopped
    environment:
      SPEEDTEST_BASE_URL: http://speedtest-tracker:80
      SPEEDTEST_API_TOKEN: ${SPEEDTEST_API_TOKEN}
    depends_on: [speedtest-tracker]
    networks: [monitoring]
```

`prometheus/prometheus.yml`:
```yaml
  - job_name: speedtest
    scrape_interval: 60s
    static_configs:
      - targets: ["speedtest-bridge:9798"]
```

- [ ] **Step 13: Start and verify**

Run:
```bash
docker compose up -d --build speedtest-bridge
sleep 30
curl -sG localhost:9090/api/v1/query \
  --data-urlencode 'query=speedtest_download_bits_per_second / 1e6' \
  | grep -o '"value":\[[^]]*\]'
```
Expected: a value near 920 — matching the historical average, in Mbps, and confirming the unit conversion is right.

- [ ] **Step 14: Commit**

```bash
git add exporters/speedtest_bridge/ docker-compose.yml prometheus/prometheus.yml
git commit -m "feat: fold in speedtest-tracker and bridge results to prometheus"
```

---

## Task 8: Pi-hole v6 exporter and the four dashboards

**Files:**
- Create: `grafana/provisioning/dashboards/provider.yml`, `d1-triage.json`, `d2-docsis.json`, `d3-bufferbloat.json`, `d4-dns.json`
- Modify: `docker-compose.yml`, `prometheus/prometheus.yml`

**Interfaces:**
- Consumes: every metric produced by Tasks 3–7
- Produces: four provisioned Grafana dashboards

- [ ] **Step 1: Add the Pi-hole v6 exporter**

Pi-hole v6 replaced the v5 `admin/api.php` interface, and several community exporters still target v5 (spec §7). Verify before wiring it in:

```bash
docker run --rm -e PIHOLE_PROTOCOL=http -e PIHOLE_HOSTNAME=YOUR_PIHOLE_IP \
  -e PIHOLE_PASSWORD=YOUR_APP_PASSWORD -e PORT=9617 -p 9617:9617 \
  ekofr/pihole-exporter:v1.0.0
```
In another shell: `curl -s localhost:9617/metrics | grep -c '^pihole_'`
Expected: a nonzero count. If it errors with a v5 API path, stop and note it — D4 is the least valuable dashboard (spec §9) and the stack is fully useful without it.

Then add to `docker-compose.yml`:
```yaml
  pihole-exporter:
    image: ekofr/pihole-exporter:v1.0.0
    restart: unless-stopped
    environment:
      PIHOLE_PROTOCOL: http
      PIHOLE_HOSTNAME: ${PIHOLE_HOST}
      PIHOLE_PASSWORD: ${PIHOLE_APP_PASSWORD}
      PORT: 9617
    networks: [monitoring]
```

And to `prometheus/prometheus.yml`:
```yaml
  - job_name: pihole
    scrape_interval: 30s
    static_configs:
      - targets: ["pihole-exporter:9617"]
```

- [ ] **Step 2: Create the dashboard provider**

`grafana/provisioning/dashboards/provider.yml`:
```yaml
apiVersion: 1

providers:
  - name: home-network-monitor
    orgId: 1
    folder: Network
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: false
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: false
```

`allowUiUpdates: false` enforces spec §12 — the repo is the source of truth, not Grafana's sqlite DB.

- [ ] **Step 3: Create D1 — triage**

`grafana/provisioning/dashboards/d1-triage.json`:

```json
{
  "title": "D1 — Triage: is it the internet, or is it me?",
  "uid": "hnm-d1-triage",
  "timezone": "browser",
  "refresh": "30s",
  "time": { "from": "now-6h", "to": "now" },
  "panels": [
    {
      "type": "timeseries",
      "title": "Latency by hop — read the shape, not the number",
      "description": "All six spike together: LAN or apollo. Flat to the modem then spikes: Comcast. Only Pi-hole: DNS. Only CDN: peering.",
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
      "fieldConfig": {
        "defaults": { "unit": "s", "custom": { "fillOpacity": 0 } }
      },
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum by (host, le) (rate(smokeping_response_duration_seconds_bucket[5m])))",
          "legendFormat": "{{host}}"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Packet loss by hop",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 10 },
      "fieldConfig": { "defaults": { "unit": "percentunit", "min": 0 } },
      "targets": [
        {
          "expr": "1 - (rate(smokeping_response_duration_seconds_count[5m]) / rate(smokeping_requests_total[5m]))",
          "legendFormat": "{{host}}"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "NIC health on enp7s0 — errors and drops",
      "description": "Ruled out the switch chain in spec §2.7. Retained as regression detection: any sustained nonzero rate means a cable or switch has degraded since.",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 10 },
      "targets": [
        {
          "expr": "rate(node_network_receive_errs_total{device=\"enp7s0\"}[5m])",
          "legendFormat": "rx errors"
        },
        {
          "expr": "rate(node_network_transmit_errs_total{device=\"enp7s0\"}[5m])",
          "legendFormat": "tx errors"
        },
        {
          "expr": "rate(node_network_receive_drop_total{device=\"enp7s0\"}[5m])",
          "legendFormat": "rx drops"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Collector health — distinguishes 'no data' from 'zero'",
      "gridPos": { "h": 6, "w": 24, "x": 0, "y": 18 },
      "fieldConfig": { "defaults": { "min": 0, "max": 1 } },
      "targets": [
        { "expr": "up", "legendFormat": "{{job}}" },
        { "expr": "mb8611_scrape_success", "legendFormat": "mb8611 scrape" }
      ]
    }
  ]
}
```

- [ ] **Step 4: Create D2 — DOCSIS health**

`grafana/provisioning/dashboards/d2-docsis.json`:

```json
{
  "title": "D2 — Modem / DOCSIS health",
  "uid": "hnm-d2-docsis",
  "timezone": "browser",
  "refresh": "1m",
  "time": { "from": "now-24h", "to": "now" },
  "panels": [
    {
      "type": "timeseries",
      "title": "Uncorrectable codeword rate — the Comcast evidence panel",
      "description": "A rising rate is a plant fault: bad splitter, water in a connector, or an oversubscribed node. This is the panel to screenshot for support.",
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
      "targets": [
        {
          "expr": "rate(mb8611_uncorrectable_codewords_total[15m])",
          "legendFormat": "ch {{channel}}"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Downstream SNR — healthy above 35 dB for 256QAM",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 10 },
      "fieldConfig": {
        "defaults": {
          "unit": "dB",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "yellow", "value": 30 },
              { "color": "green", "value": 35 }
            ]
          }
        }
      },
      "targets": [
        {
          "expr": "mb8611_channel_snr_db{direction=\"downstream\"}",
          "legendFormat": "ch {{channel}}"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Downstream power — healthy between -7 and +7 dBmV",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 10 },
      "fieldConfig": { "defaults": { "unit": "dBm" } },
      "targets": [
        {
          "expr": "mb8611_channel_power_dbmv{direction=\"downstream\"}",
          "legendFormat": "ch {{channel}}"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Upstream power — healthy 35-49 dBmV, concerning above 52",
      "description": "High upstream power means the modem is shouting to be heard — a common signature of a failing line or too many splitters.",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 18 },
      "fieldConfig": {
        "defaults": {
          "unit": "dBm",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 49 },
              { "color": "red", "value": 52 }
            ]
          }
        }
      },
      "targets": [
        {
          "expr": "mb8611_channel_power_dbmv{direction=\"upstream\"}",
          "legendFormat": "ch {{channel}}"
        }
      ]
    },
    {
      "type": "stat",
      "title": "T3 timeouts — any nonzero value is worth investigating",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 18 },
      "targets": [{ "expr": "mb8611_t3_timeouts_total" }]
    }
  ]
}
```

- [ ] **Step 5: Create D3 — bufferbloat and throughput**

`grafana/provisioning/dashboards/d3-bufferbloat.json`:

```json
{
  "title": "D3 — Bufferbloat & throughput",
  "uid": "hnm-d3-bufferbloat",
  "timezone": "browser",
  "refresh": "1m",
  "time": { "from": "now-24h", "to": "now" },
  "panels": [
    {
      "type": "timeseries",
      "title": "Latency increase under load — under 30ms fine, over 100ms explains buffering",
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
      "fieldConfig": {
        "defaults": {
          "unit": "ms",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 30 },
              { "color": "red", "value": 100 }
            ]
          }
        }
      },
      "targets": [
        {
          "expr": "(bufferbloat_loaded_rtt_seconds - on(target) group_left bufferbloat_idle_rtt_seconds) * 1000",
          "legendFormat": "{{direction}}"
        }
      ]
    },
    {
      "type": "stat",
      "title": "Bufferbloat grade (0 = A+, 5 = F)",
      "gridPos": { "h": 6, "w": 8, "x": 0, "y": 10 },
      "fieldConfig": {
        "defaults": {
          "min": 0,
          "max": 5,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 2 },
              { "color": "red", "value": 3 }
            ]
          }
        }
      },
      "targets": [{ "expr": "bufferbloat_grade" }]
    },
    {
      "type": "stat",
      "title": "Minutes since last bufferbloat run",
      "description": "Pushed metrics persist after a job dies. A climbing value here means the job stopped and the grade above is stale.",
      "gridPos": { "h": 6, "w": 8, "x": 8, "y": 10 },
      "fieldConfig": {
        "defaults": {
          "unit": "m",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "red", "value": 90 }
            ]
          }
        }
      },
      "targets": [
        { "expr": "(time() - bufferbloat_last_run_timestamp_seconds) / 60" }
      ]
    },
    {
      "type": "stat",
      "title": "Minutes since last speedtest",
      "gridPos": { "h": 6, "w": 8, "x": 16, "y": 10 },
      "fieldConfig": { "defaults": { "unit": "m" } },
      "targets": [
        { "expr": "(time() - speedtest_last_run_timestamp_seconds) / 60" }
      ]
    },
    {
      "type": "timeseries",
      "title": "Speedtest throughput — capped at ~940 Mbps by apollo's 1GbE NIC",
      "description": "This is a regression detector, not an SLA measurement. A drop to 400 Mbps is a real signal; 920 is a perfect score, not a shortfall.",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 16 },
      "fieldConfig": { "defaults": { "unit": "bps" } },
      "targets": [
        { "expr": "speedtest_download_bits_per_second", "legendFormat": "download" },
        { "expr": "speedtest_upload_bits_per_second", "legendFormat": "upload" }
      ]
    },
    {
      "type": "timeseries",
      "title": "apollo NIC utilisation — discard measurements taken during these spikes",
      "description": "When apollo's own workloads saturate its 1GbE link, every measurement from this host is skewed.",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 16 },
      "fieldConfig": { "defaults": { "unit": "Bps" } },
      "targets": [
        {
          "expr": "rate(node_network_receive_bytes_total{device=\"enp7s0\"}[5m])",
          "legendFormat": "rx"
        },
        {
          "expr": "rate(node_network_transmit_bytes_total{device=\"enp7s0\"}[5m])",
          "legendFormat": "tx"
        }
      ]
    }
  ]
}
```

- [ ] **Step 6: Create D4 — DNS and clients**

`grafana/provisioning/dashboards/d4-dns.json`:

```json
{
  "title": "D4 — DNS & clients",
  "uid": "hnm-d4-dns",
  "timezone": "browser",
  "refresh": "1m",
  "time": { "from": "now-12h", "to": "now" },
  "panels": [
    {
      "type": "timeseries",
      "title": "DNS resolve time — Pi-hole vs upstream",
      "description": "If the Pi-hole line sits materially above the upstream lines, DNS is the cause of 'pages hang then load fine'.",
      "gridPos": { "h": 10, "w": 24, "x": 0, "y": 0 },
      "fieldConfig": { "defaults": { "unit": "s" } },
      "targets": [
        {
          "expr": "probe_dns_lookup_time_seconds",
          "legendFormat": "{{instance}} ({{role}})"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Queries per client — COUNTS, NOT BYTES",
      "description": "Finds an IoT device hammering DNS. Will NOT find a device streaming 4K — that is few queries and enormous traffic. Byte-level attribution needs flow data the current topology cannot provide (spec §2.5).",
      "gridPos": { "h": 10, "w": 12, "x": 0, "y": 10 },
      "targets": [
        {
          "expr": "topk(10, rate(pihole_client_queries[5m]))",
          "legendFormat": "{{client}}"
        }
      ]
    },
    {
      "type": "timeseries",
      "title": "Block rate",
      "gridPos": { "h": 10, "w": 12, "x": 12, "y": 10 },
      "fieldConfig": { "defaults": { "unit": "percent" } },
      "targets": [{ "expr": "pihole_ads_percentage_today" }]
    }
  ]
}
```

- [ ] **Step 7: Restart Grafana and verify all four dashboards load**

Run:
```bash
docker compose up -d pihole-exporter
docker compose restart grafana
sleep 20
docker compose logs grafana 2>&1 | grep -i "provisioning\|dashboard" | tail -20
```
Expected: no provisioning errors. Then open `http://apollo:3000`, folder **Network**, and confirm four dashboards appear.

- [ ] **Step 8: Verify every panel returns data rather than "No data"**

Walk each dashboard. Any panel showing "No data" means either its metric name does not match spec §8 or its collector is down — check D1's collector health panel first.

Known acceptable exception: `pihole_client_queries` may not exist under the v6 exporter. If D4's client panel is empty, note it and move on; it is the lowest-value panel in the stack.

- [ ] **Step 9: Commit**

```bash
git add grafana/provisioning/dashboards/ docker-compose.yml prometheus/prometheus.yml
git commit -m "feat: add pihole exporter and four provisioned dashboards"
```

---

## Task 9 (optional): Wireless probe

Only worth doing once wired data is clean. If D1 shows healthy wired latency while the house still buffers, Wi-Fi is the remaining suspect (spec §15 suspect 3) and this task isolates it.

**Files:**
- Modify: `docker-compose.yml`, `prometheus/prometheus.yml`, `smokeping/targets.env`

**Interfaces:**
- Consumes: the smokeping pattern from Task 3
- Produces: `smokeping_response_duration_seconds{host="<wireless-host>"}` — same metric name, so D1 needs no change

- [ ] **Step 1: Identify a wireless always-on device and give it a static lease**

Any spare Pi, phone, or laptop that stays on Wi-Fi and stays powered. Reserve its address in the BE400's DHCP settings so the probe target does not move.

- [ ] **Step 2: Add it as a smokeping target**

In `docker-compose.yml`, add the address to the `smokeping` command list. In `smokeping/targets.env`, document it:

```bash
#   192.168.1.50     wireless probe  — isolates Wi-Fi contention from WAN issues
```

- [ ] **Step 3: Restart and verify seven targets**

Run:
```bash
docker compose up -d smokeping
sleep 30
curl -s localhost:9374/metrics | grep -c '^smokeping_requests_total'
```
Expected: `7`.

- [ ] **Step 4: Interpret after 24 hours**

Compare the wireless host's latency against the wired gateway line on D1. Wireless latency spiking while wired stays flat confirms Wi-Fi contention — and given the BE400 has no 6 GHz band (spec §2.4), the fix is a band or hardware change, not a configuration tweak.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml smokeping/targets.env
git commit -m "feat: add wireless probe target to isolate wifi contention"
```

---

## Post-implementation: reading the results

After 24–48 hours of data, work through spec §15's suspect list in order:

| Check | Dashboard | Conclusion if positive |
|---|---|---|
| `rate(mb8611_uncorrectable_codewords_total[15m])` climbing | D2 | Plant fault. Call Comcast with the D2 screenshot. A faster tier will not fix it. |
| Bufferbloat delta > 100 ms | D3 | Queue management problem. Note the BE400 lacks fq_codel/cake, so the fix may require different hardware. |
| Wireless latency ≫ wired | D1 + Task 9 | Wi-Fi contention. No 6 GHz on this router means a hardware change. |
| Pi-hole resolve time ≫ upstream | D4 | DNS. Add a second resolver or upstream. |
| None of the above, sustained 940 Mbps saturation during real use | D3 | The only case where a faster tier is justified — and per spec §17, it needs ~$400 of hardware to be usable. |

Record the finding in the spec's §15 as resolved, the same way §2.7 recorded the eliminated switch-chain suspect.
