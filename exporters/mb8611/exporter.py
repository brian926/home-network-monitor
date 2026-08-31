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
