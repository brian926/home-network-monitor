"""Prometheus bridge for speedtest-tracker."""

import os
import time

import requests
from prometheus_client import Gauge, start_http_server
from prometheus_client.core import GaugeMetricFamily, REGISTRY

from .parser import parse_latest_result

SCRAPE_SUCCESS = Gauge("speedtest_bridge_scrape_success",
                       "1 if the last tracker API read succeeded, else 0")

POLL_INTERVAL_SECONDS = 300


class SpeedtestCollector:
    """Yields no series until a successful API read has occurred.

    An unlabeled prometheus_client Gauge exports 0.0 before it is ever set,
    which would publish a fabricated "0 bits/sec download, 0s ping"
    measurement during startup (and on every restart, since depends_on only
    orders container start, not the tracker's readiness) — spec §10.4:
    absence must not render as a real value. This custom collector emits no
    series at all until self._result is populated by a successful poll, and
    update(None) (a failed poll) never clears a previously-good result.
    """

    def __init__(self) -> None:
        self._result: dict | None = None

    def update(self, result: dict | None) -> None:
        if result is not None:
            self._result = result

    def collect(self):
        if self._result is None:
            return
        yield GaugeMetricFamily(
            "speedtest_download_bits_per_second",
            "Download throughput",
            value=self._result["download_bits_per_second"],
        )
        yield GaugeMetricFamily(
            "speedtest_upload_bits_per_second",
            "Upload throughput",
            value=self._result["upload_bits_per_second"],
        )
        yield GaugeMetricFamily(
            "speedtest_ping_seconds",
            "Idle latency reported by speedtest",
            value=self._result["ping_seconds"],
        )
        yield GaugeMetricFamily(
            "speedtest_last_run_timestamp_seconds",
            "Unix time of the most recent speedtest result",
            value=self._result["timestamp"],
        )


COLLECTOR = SpeedtestCollector()


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

    COLLECTOR.update(result)
    SCRAPE_SUCCESS.set(1)


def main() -> None:
    base_url = os.environ.get("SPEEDTEST_BASE_URL",
                              "http://speedtest-tracker:80")
    token = os.environ["SPEEDTEST_API_TOKEN"]

    REGISTRY.register(COLLECTOR)
    start_http_server(9798)
    while True:
        collect(base_url, token)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
