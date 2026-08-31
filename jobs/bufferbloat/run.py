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
    pushgateway = os.environ.get("PUSHGATEWAY_URL", "http://localhost:9091")

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
