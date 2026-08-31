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
