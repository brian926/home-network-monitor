# Deployment

Work through this in order on the host that will run the stack. Several steps
cannot be skipped without the stack silently measuring nothing or, worse,
displaying confident wrong numbers.

## 1. Clone and configure

```bash
git clone <this-repo>
cd home-network-monitor
cp .env.example .env
```

Fill in every value in `.env`. Compose substitutes a **blank** value for an
empty variable rather than treating it as unset, so a blank line is not the same
as a missing one.

The values with no safe default:

| Variable | What it is | Find it with |
|---|---|---|
| `GATEWAY_IP` | Your router / default gateway | `ip route \| grep default` |
| `PIHOLE_HOST` | Your LAN DNS resolver | Pi-hole admin UI, or your DHCP settings |
| `NIC_DEVICE` | Interface on this host | `ip -br link` |
| `SMOKEPING_TARGETS` | Space-separated probe list | See step 2 |
| `GRAFANA_ADMIN_PASSWORD` | Grafana login | Choose one |

## 2. Choose your probe targets

`SMOKEPING_TARGETS` is the heart of the diagnosis. Each target isolates a
different suspect, so order them outward from you:

```
SMOKEPING_TARGETS=<gateway> <dns-resolver> [<modem>] 1.1.1.1 8.8.8.8 1.0.0.1
```

Include your modem only if it has a reachable management IP — many bridged and
ISP-supplied units do not. Include two or three public resolvers as a control:
if all of them degrade together it is your connection, if only one does it is
that path.

You read the resulting graph by **shape**, not by absolute numbers:

- Everything spikes together → your LAN, or this host's own traffic
- Flat locally, spikes beyond the gateway → your ISP
- Only the resolver line spikes → DNS
- Only one public target spikes → peering or congestion to that service

## 3. Rotate credentials

Generate a fresh Laravel key for speedtest-tracker:

```bash
echo "base64:$(openssl rand -base64 32)"
```

Put it in `SPEEDTEST_APP_KEY`. If you are migrating from an existing
speedtest-tracker deployment, do **not** reuse the old key — and check whether
it leaked into your shell history:

```bash
grep -n "APP_KEY" ~/.bash_history
```

For `PIHOLE_APP_PASSWORD`, create a scoped **app password** in Pi-hole rather
than using your admin password, so it can be revoked on its own. In Pi-hole v6
this is under Settings → Web interface / API.

`SPEEDTEST_API_TOKEN` does not exist yet — you create it in the speedtest-tracker
web UI after first login, in step 7.

## 4. Render config and validate

```bash
./scripts/setup.sh
./scripts/validate.sh
```

`setup.sh` fails loudly on missing required values and renders the Prometheus
target files, which cannot read environment variables themselves. Re-run it any
time you change an address in `.env`.

## 5. Migrating an existing speedtest-tracker

Skip if you do not already run one.

**Note on versions:** `speedtest-tracker` is the one image here that is
deliberately not pinned. Upstream persists its generated nginx and app configs
into `/config` and never downgrades them, so pinning an older version against a
`/config` written by a newer one fails at startup with
`nginx: [emerg] unknown directive "http3"` or similar. If you hit that, either
move `./data/speedtest/nginx` aside so it regenerates, or start with a clean
`./data/speedtest`.

If you want to keep an existing deployment's history:

```bash
docker stop speedtest-tracker
mkdir -p ./data/speedtest
sudo cp -a /path/to/its/config/dir/. ./data/speedtest/
sudo chown -R 1000:1000 ./data/speedtest
docker rm speedtest-tracker
```

Do not delete the original directory until step 7 confirms the history survived.

A common deployment mistake worth checking for: if the original container was
started with an unsubstituted `-v /path/to/data:/config` flag, Docker created a
directory *literally* named `/path/to/data`. Look there before concluding the
history is gone.

## 6. Bring the stack up in phases

Do not start everything at once — you want to know which target broke.

```bash
docker compose up -d prometheus grafana node-exporter
docker compose up -d smokeping
docker compose up -d blackbox
docker compose up -d pushgateway bufferbloat
docker compose up -d speedtest-tracker speedtest-bridge
docker compose up -d pihole-exporter
docker compose up -d mb8611-exporter   # only if MB8611_ENABLED=true
```

After each phase, confirm every target reads `up` at `http://<this-host>:9090/targets`.

**Phase 1 alone may answer your question.** Core plus smokeping plus blackbox
gives you real loss, jitter, and DNS timing. Look at a day of that before
assuming you need the rest.

## 7. First-run tasks

- Log in to speedtest-tracker at `http://<this-host>:8080`, confirm any migrated
  history is present, create an API token, put it in `SPEEDTEST_API_TOKEN`, and
  `docker compose up -d speedtest-bridge`.
- Log in to Grafana at `http://<this-host>:3000`. The four dashboards appear under
  the **Network** folder. Set the `NIC` variable at the top of D1 and D3 to this
  host's interface.
- Run the bufferbloat job once by hand rather than waiting for cron:

  ```bash
  docker compose exec bufferbloat python -m jobs.bufferbloat.run
  ```

  It deliberately saturates your connection for about 45 seconds. Expect the
  internet to be slow while it runs — that is the measurement working.

## 8. If you have a Motorola MB8611

The DOCSIS dashboard is the most valuable one in this stack — SNR, power levels,
and uncorrectable codewords are the evidence a cable ISP acts on, where a speed
test screenshot gets dismissed.

**The parser's field order in `exporters/mb8611/parser.py` was derived from a
representative sample, not from a capture of your modem's firmware.** Until you
reconcile it, treat every number on that dashboard as unverified — a mis-mapped
field would put SNR in the power column and read as confident nonsense.

Run this against your modem once, and compare the output to the field order the
parser assumes:

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

`YOUR_MODEM_PASSWORD` is a placeholder — it is usually printed on the modem's
label. Never commit it.

**Do not run this in a loop.** The 60-second polling floor exists because
aggressive HNAP polling can wedge this modem's web server and take your internet
down until it is power-cycled. The same applies to manual runs.

That capture has two jobs:

1. Confirm the downstream and upstream channel field order matches
   `parse_downstream` / `parse_upstream`. Fix the indices if it does not.
2. Locate where T3 timeout counts live in the response. That metric is
   deliberately not emitted — an unlabeled gauge would export `0.0` and read as
   "no timeouts, modem healthy", which is a false negative on a key fault
   signal. D2's T3 panel stays empty until you implement it.

**If the modem becomes unresponsive at any point:** set `MB8611_ENABLED=false`,
run `docker compose up -d mb8611-exporter`, and power-cycle the modem.

## 9. Verify the speedtest-tracker API shape

`exporters/speedtest_bridge/parser.py` assumes throughput in bytes per second
and ping in milliseconds. The API is version-dependent. Confirm against yours:

```bash
curl -s -H "Authorization: Bearer $SPEEDTEST_API_TOKEN" \
     -H "Accept: application/json" \
     http://localhost:8080/api/v1/results/latest | python3 -m json.tool
```

If the units differ, fix the conversion in `parse_latest_result` and its tests.
A wrong conversion reports throughput 8× off in either direction.

## 10. Expected non-faults

These look broken but are not:

- **D2's T3 panel shows "No data"** until you complete step 8.
- **D4's per-client panel may be empty.** Its metric name is unverified against
  the Pi-hole v6 exporter. D4 is the least valuable dashboard here — per-client
  DNS *query counts* are not bandwidth.
- **Throughput never exceeds your slowest link.** On a 1 GbE host that is about
  940 Mbps regardless of your plan. Not a fault, and not proof of your
  contracted rate either.

## 11. Optional: test Wi-Fi

Wi-Fi contention is invisible to everything above, because every probe
originates from this wired host. If wired latency is clean but wireless clients
still stall, that gap is the answer.

Give a spare always-on wireless device a static DHCP lease and add its address
to `SMOKEPING_TARGETS`, then re-run `./scripts/setup.sh` and restart smokeping.
Wireless latency spiking while the wired gateway line stays flat confirms Wi-Fi.

## 12. Security

Prometheus has **no authentication** and binds all interfaces. Grafana has a
password but is still LAN-only by design.

Never port-forward any port in this stack. For access from outside your network,
use a VPN or an overlay network such as Tailscale.

### A metric that looks right and is not

`probe_dns_lookup_time_seconds` sounds like the DNS query time. It is not — it
measures resolving the *target's own hostname*, so when your probe targets are
IP addresses it reports `0` forever. Use `probe_duration_seconds` filtered to
the DNS roles instead:

```promql
probe_duration_seconds{role=~"local_dns|upstream_dns"} * 1000
```

D4 uses the correct one. Mentioned here because the wrong metric produces a
confident flat-zero line rather than an obvious error.

## 13. Reaching it from other devices

The stack ships a Caddy reverse proxy that puts every service under one
hostname on port 80:

| Path | Service |
|---|---|
| `/` | Landing page with links |
| `/grafana` | Grafana |
| `/prometheus` | Prometheus |
| `/speedtest` | Speedtest Tracker |
| `/pushgateway` | Pushgateway |

The published per-service ports (3000, 9090, 8080, 9091) still work and are a
useful fallback when the proxy misbehaves.

### Make the name resolve everywhere

Avoid `.local`. That suffix is reserved for mDNS, and support is uneven —
macOS and Windows handle it, Android is unreliable, and Linux needs
`nss-mdns` installed. Some clients also bypass DNS entirely for `.local`,
so a Pi-hole record for it may be ignored.

Instead, add a **Local DNS record in Pi-hole**, which every device on the
network already uses for DNS:

1. Pi-hole admin → Settings → Local DNS Records
2. Domain: `apollo.home` (or `monitor.lan`, or anything under `.home.arpa`)
3. IP: the address of the host running this stack

Then set `PROXY_HOSTNAME` in `.env` to that exact name and restart the proxy:

```bash
docker compose up -d caddy grafana prometheus pushgateway
```

`PROXY_HOSTNAME` matters because Grafana, Prometheus, and Pushgateway build
absolute redirect and asset URLs from it. Caddy itself listens for any
hostname, so the raw IP keeps working too.

### Port 80 conflicts

If a Kubernetes ingress controller or another web server already owns port 80
on this host, Caddy will fail to start. Check first:

```bash
sudo ss -tlnp | grep ':80 '
```

Set `PROXY_PORT=8081` (or anything free) in `.env` and use
`http://apollo.home:8081/` instead.

### Known limitation: the speedtest path

`/speedtest` proxies a Laravel application, and Laravel's subpath support is
imperfect — asset URLs are generated from the app root. If the page loads
without styling or the assets 404, set `SPEEDTEST_APP_URL` to the direct
port form (`http://apollo.home:8080`) and use that port for this one service.
Everything else is unaffected.
