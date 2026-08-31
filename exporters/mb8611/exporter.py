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

# mb8611_t3_timeouts_total is deliberately NOT declared.
# An unlabeled prometheus_client Gauge exports 0.0 even when never set, which
# would render as "no T3 timeouts, modem healthy" — a false negative on one of
# the most diagnostic DOCSIS signals (spec §10.4: no-data must not look like a
# healthy zero). The GetMotoStatusConnectionInfo response is already fetched by
# client.py, but the field carrying T3 counts is unknown until the Step 1
# discovery capture is run against the real modem on apollo. Declare and
# populate this metric only once that capture identifies the field.
SCRAPE_SUCCESS = Gauge("mb8611_scrape_success",
                       "1 if the last modem scrape succeeded, else 0")


def collect(client: MB8611Client) -> None:
    status = client.fetch_status()
    if not status:
        # spec §10.4: absence must not render as a healthy value. Without
        # this, prometheus_client keeps re-exporting the last good SNR/power
        # readings forever, so a dead modem draws flat, confident, healthy
        # lines on D2 even though mb8611_scrape_success has flipped to 0.
        SNR.clear()
        POWER.clear()
        UNCORRECTABLE.clear()
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


def _parse_interval_seconds(raw: str) -> int:
    """Parse MB8611_INTERVAL_SECONDS, treating empty/garbage as the 60s floor.

    Docker Compose substitutes an EMPTY STRING (not "unset") for a ${VAR}
    missing from .env, and int("") raises ValueError before
    start_http_server runs — a crash loop with no metrics and no signal.
    The 60s floor is a modem-safety requirement (spec §10.1: aggressive
    polling can wedge the modem's web server) and must hold no matter what
    garbage arrives here.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 60
    return max(60, value)


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
    interval = _parse_interval_seconds(os.environ.get("MB8611_INTERVAL_SECONDS", "60"))

    start_http_server(9611)
    while True:
        try:
            collect(client)
        except Exception:
            # spec §10.4: absence must not render as a healthy value — clear
            # the labelled gauges here too, since collect() can raise after
            # a partial update (e.g. mid-loop parse failure).
            SNR.clear()
            POWER.clear()
            UNCORRECTABLE.clear()
            SCRAPE_SUCCESS.set(0)
        time.sleep(interval)


if __name__ == "__main__":
    main()
