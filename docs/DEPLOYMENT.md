# Deployment checklist

This stack was built and tested without access to the deploy host (`apollo`)
or the modem. The steps below were deferred for that reason and are not yet
verified against real hardware. Follow them in order the first time the
stack goes up on `apollo`; check each one off as you go.

1. **Replace the placeholder IPs.** `docker-compose.yml`'s `smokeping`
   `command:` block has `192.168.1.1` (gateway) and `192.168.1.2` (Pi-hole)
   marked `# PLACEHOLDER`; `prometheus/targets/dns.yml` has the same
   Pi-hole placeholder. Nothing works correctly until these are the real
   addresses on your LAN.

2. **Create `.env` from `.env.example`** and fill in every value.
   A blank value is substituted by Docker Compose as an **empty string**,
   not as "unset" — leaving a variable blank is not the same as omitting
   it, and several services (notably `mb8611-exporter`) will misbehave or
   crash-loop on an empty string rather than falling back to a default.

3. **Rotate the speedtest-tracker `APP_KEY`.** The previous key was
   disclosed in plaintext and must not be reused. Generate a new one with:

       openssl rand -base64 32

   and prefix the result with `base64:` before putting it in `.env` as
   `SPEEDTEST_APP_KEY`. Rotating it invalidates existing sessions — you'll
   need to log in again, nothing else. Also check shell history for the
   old key so it isn't left lying around:

       grep -n "APP_KEY" ~/.bash_history

4. **Use a Pi-hole v6 app password, not the admin password**, for
   `PIHOLE_APP_PASSWORD` in `.env`, so it can be revoked independently of
   the admin login.

5. **Migrate the existing speedtest history.** The previously running
   container wrote its data to a literal `/path/to/data` directory, created
   by an unsubstituted volume flag. Before bringing up `speedtest-tracker`
   on the current compose file (which mounts `./data/speedtest:/config`):
   - Copy the old data: `/path/to/data` → `./data/speedtest`
   - `chown -R 1000:1000 ./data/speedtest`
   - Remove the old container
   - Do **not** delete `/path/to/data` until the speedtest-tracker UI
     confirms the history survived the move.

6. **Run the MB8611 HNAP discovery capture.** `exporters/mb8611/parser.py`'s
   field order comes from a representative sample, **not** from this
   modem's actual firmware. Until it's reconciled against a real capture,
   D2's numbers are unverified — a mis-mapped field would put SNR in the
   power column and read as confident nonsense. It must also identify
   where T3 timeout counts live in the response, which is what re-enables
   D2's currently-disabled T3 panel. Run the capture script below on
   `apollo` against the real modem:

   `YOUR_MODEM_PASSWORD` below is a placeholder — fill it in at run time
   and never commit it. Do not run this script in a loop or on a timer:
   the 60-second poll floor applies to manual runs too, not just the
   exporter.

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

7. **Run the speedtest-tracker API discovery.**
   `exporters/speedtest_bridge/parser.py`'s field names and units come from
   a representative sample; the API is version-dependent. Capture the real
   shape with:

       curl -s -H "Authorization: Bearer $TOKEN" \
            -H "Accept: application/json" \
            http://localhost:8080/api/v1/results/latest

   and compare against `exporters/speedtest_bridge/parser.py` before
   trusting D3's throughput numbers.

8. **Confirm the NIC name.** Dashboards and Prometheus queries hardcode
   `enp7s0`. Verify it matches the deploy host with:

       ip -br link

9. **Bring the stack up in phases**, not all at once, verifying each
   phase's targets show `up` at `http://apollo:9090/targets` before moving
   to the next:

   1. core: `prometheus`, `grafana`, `node-exporter`
   2. `smokeping`
   3. `blackbox`
   4. `mb8611`
   5. `pushgateway` + `bufferbloat`
   6. `speedtest` (`speedtest-tracker` + `speedtest-bridge`)
   7. `pihole`

10. **MB8611 safety.** Never poll the modem faster than 60 seconds —
    aggressive polling can wedge its web server and take the whole
    connection down. If the modem becomes unresponsive:
    - Set `MB8611_ENABLED=false` in `.env`
    - `docker compose up -d mb8611-exporter`
    - Reboot the modem

11. **Run the bufferbloat job once by hand** before trusting the schedule:

        docker compose exec bufferbloat python -m jobs.bufferbloat.run

    It saturates the link for roughly 45 seconds — expect the internet to
    be slow during the run. Confirm the metrics reach the Pushgateway
    (`http://apollo:9091`) afterward.

12. **Expected non-faults** — these are known, not bugs:
    - D2's T3 panel shows "No data" until step 6 above is done.
    - D4's Pi-hole client panel may be empty — its metric name is
      unverified against the v6 exporter, and D4 is the lowest-value
      dashboard in the stack.

13. **Optional — wireless probe.** Wi-Fi contention is an untested
    suspect (the router is dual-band with no 6 GHz). To test it:
    - Give a spare always-on wireless device a static DHCP lease.
    - Add its IP to the smokeping `command:` list in `docker-compose.yml`.
    - Document it in `smokeping/targets.env`.

    Wireless latency spiking while wired stays flat confirms Wi-Fi as the
    cause.

14. **Security.** Prometheus has no authentication and binds `0.0.0.0`.
    Never port-forward it to the internet. For remote access, use
    Tailscale or a VPN.

15. **Expected log noise.** None from cron after this release — the
    malformed 5-field `/etc/cron.d/bufferbloat` copy (which would have
    logged a spurious "bad user" error) was removed.
