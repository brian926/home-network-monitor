#!/usr/bin/env python3
"""Find spikes and gaps in recent monitoring data.

Averages hide intermittent faults. A router dropping 40% of packets for half an
hour is invisible in a 24-hour mean and invisible in a 10-minute snapshot taken
at the wrong moment. This walks the whole window at a fine step and reports the
WORST value per target with a timestamp, so short events surface.

Usage:
    python scripts/analyze.py                          # localhost, last 24h
    python scripts/analyze.py --hours 48
    python scripts/analyze.py --url http://apollo:9090
    python scripts/analyze.py --from "2026-09-01 17:30" --to "2026-09-01 19:15"
    python scripts/analyze.py --tz -4                   # timestamps in your zone
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

LOSS = ('(1 - (rate(smokeping_response_duration_seconds_count[%(w)s]) / '
        'rate(smokeping_requests_total[%(w)s]))) * 100')
P95 = ('histogram_quantile(0.95, sum by (host,le) '
       '(rate(smokeping_response_duration_seconds_bucket[%(w)s]))) * 1000')


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:9090",
                   help="Prometheus base URL")
    p.add_argument("--hours", type=float, default=24.0)
    p.add_argument("--from", dest="start", help='"YYYY-MM-DD HH:MM" local')
    p.add_argument("--to", dest="end", help='"YYYY-MM-DD HH:MM" local')
    p.add_argument("--step", type=int, default=300, help="seconds (default 300)")
    p.add_argument("--tz", type=float, default=None,
                   help="UTC offset in hours for displayed times")
    return p.parse_args()


class Prom:
    def __init__(self, base, start, end, step, tzinfo):
        self.base = base.rstrip("/") + "/api/v1"
        self.start, self.end, self.step, self.tz = start, end, step, tzinfo

    def range(self, query, step=None):
        params = {"query": query, "start": self.start, "end": self.end,
                  "step": step or self.step}
        url = f"{self.base}/query_range?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=60) as fh:
                body = json.load(fh)
        except Exception as exc:
            print(f"  query failed: {exc}", file=sys.stderr)
            return []
        if body.get("status") != "success":
            print(f"  query error: {body.get('error')}", file=sys.stderr)
            return []
        return body["data"]["result"]

    def stamp(self, ts):
        return datetime.fromtimestamp(ts, self.tz).strftime("%m-%d %H:%M")


def points(series):
    out = []
    for ts, val in series["values"]:
        try:
            num = float(val)
        except ValueError:
            continue
        if num == num:  # drop NaN
            out.append((int(ts), num))
    return out


def report_worst(prom, query, label, unit, threshold, step=None):
    print(f"\n[{label}]  worst value per target, {unit}")
    rows = []
    for series in prom.range(query, step):
        pts = points(series)
        if not pts:
            continue
        name = series["metric"].get("host") or series["metric"].get("instance", "?")
        peak_ts, peak = max(pts, key=lambda p: p[1])
        median = sorted(v for _, v in pts)[len(pts) // 2]
        rows.append((peak, name, peak_ts, median, len(pts)))
    if not rows:
        print("    no data")
        return
    for peak, name, peak_ts, median, n in sorted(rows, reverse=True):
        flag = "  <-- LOOK" if threshold is not None and peak >= threshold else ""
        print(f"    {name:<22} worst={peak:9.2f} at {prom.stamp(peak_ts)}"
              f"   median={median:8.2f}  ({n} pts){flag}")


def report_zeros(prom, query, label, key):
    print(f"\n[{label}]")
    found = False
    for series in prom.range(query):
        bad = [ts for ts, val in points(series) if val == 0]
        if bad:
            found = True
            name = series["metric"].get(key, "?")
            print(f"    {name:<28} {len(bad)} zero samples, first "
                  f"{prom.stamp(bad[0])}, last {prom.stamp(bad[-1])}")
    if not found:
        print("    none")


def report_spread(prom, query, label, fmt="%.1f"):
    print(f"\n[{label}]")
    for series in prom.range(query, 900):
        vals = sorted({round(v, 1) for _, v in points(series)})
        if not vals:
            continue
        name = (series["metric"].get("direction")
                or series["metric"].get("host") or "value")
        print(f"    {name:<12} min={fmt % vals[0]}  max={fmt % vals[-1]}")
        if len(vals) <= 24:
            print(f"                 samples: {vals}")


def main():
    args = parse_args()
    tzinfo = timezone(timedelta(hours=args.tz)) if args.tz is not None else None

    if args.start and args.end:
        fmt = "%Y-%m-%d %H:%M"
        start = int(datetime.strptime(args.start, fmt).replace(tzinfo=tzinfo).timestamp())
        end = int(datetime.strptime(args.end, fmt).replace(tzinfo=tzinfo).timestamp())
    else:
        end = int(time.time())
        start = end - int(args.hours * 3600)

    prom = Prom(args.url, start, end, args.step, tzinfo)
    window = f"{max(2 * args.step, 120)}s"

    print(f"source : {args.url}")
    print(f"window : {prom.stamp(start)} -> {prom.stamp(end)}"
          f"  ({(end - start) / 3600:.1f}h, {args.step}s step)")

    # A target whose loss spikes while OTHERS STAY CLEAN localises the fault.
    # Compare paths: a LAN host reachable without the router vs the gateway vs
    # public targets. If everything through the router degrades and the
    # switch-only host does not, the router is the fault.
    report_worst(prom, LOSS % {"w": window}, "PACKET LOSS", "%", 5.0)
    report_worst(prom, P95 % {"w": window}, "p95 LATENCY", "ms", None)
    report_zeros(prom, "probe_success", "PROBE FAILURES", "instance")
    report_zeros(prom, "up", "SCRAPE GAPS (collector down)", "job")
    report_spread(prom, "bufferbloat_grade", "BUFFERBLOAT GRADE (0=A+ .. 5=F)")
    report_spread(prom,
                  "(bufferbloat_loaded_rtt_seconds - on(target) group_left "
                  "bufferbloat_idle_rtt_seconds) * 1000",
                  "BUFFERBLOAT DELTA ms")
    report_spread(prom, "speedtest_download_bits_per_second / 1e6", "DOWNLOAD Mbps")
    report_spread(prom, "speedtest_upload_bits_per_second / 1e6", "UPLOAD Mbps")

    print("\n[NIC COUNTERS over window]")
    for metric, label in [("receive_errs_total", "rx errors"),
                          ("transmit_errs_total", "tx errors"),
                          ("receive_drop_total", "rx drops")]:
        query = f"increase(node_network_{metric}[{int(end - start)}s])"
        vals = [v for s in prom.range(query, 3600) for _, v in points(s)]
        peak = max(vals) if vals else None
        note = ""
        if label == "rx drops" and peak:
            note = "  (drops with zero errors are usually frames with no listener)"
        print(f"    {label:<12} {peak if peak is not None else 'n/a'}{note}")

    print("\nReading this: a spike on ONE target with others clean isolates that "
          "path.\nA spike on everything EXCEPT a switch-only LAN host implicates "
          "the router.\nA spike on public targets only, with the gateway clean, "
          "implicates the ISP.")


if __name__ == "__main__":
    main()
