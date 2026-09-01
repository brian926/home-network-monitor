"""Convert speedtest-tracker API responses into metric-ready values.

CAVEAT — UNVERIFIED API RESPONSE SHAPE:
The field names and units encoded below (bytes-per-second for download and
upload, milliseconds for ping, and a `data.{download,upload,ping,created_at}`
envelope) were taken from a REPRESENTATIVE SAMPLE documented in the Task 7
brief, NOT from a live capture of this deployment's actual speedtest-tracker
instance. Task 7 Step 5 (a discovery script that queries the running
container's /api/v1/results/latest endpoint with a bearer token) could not
be run from this environment, because the container is reachable only from
the deploy host (the monitoring host).

The speedtest-tracker API shape is version-dependent — older versions have
been observed reporting bits per second where newer versions report bytes
per second, and field names can shift between releases (spec §10.2).

Before trusting any dashboard or alert built on these metrics, the repo
owner MUST:
  1. Run the Step 5 discovery command on the monitoring host against the real,
     running speedtest-tracker instance:
       source .env
       curl -s -H "Authorization: Bearer ${SPEEDTEST_API_TOKEN}" \
            -H "Accept: application/json" \
            http://localhost:8080/api/v1/results/latest | python3 -m json.tool
  2. Compare the captured field names and units to the ones assumed here
     (download/upload in bytes per second, ping in milliseconds,
     created_at as an ISO-8601 UTC timestamp).
  3. Update this parser and its tests (tests/test_parser.py) to match the
     real response if the shape or units differ.

A units mismatch here would silently misreport throughput by a factor of
8 (bits vs. bytes) and produce confident, wrong bandwidth dashboards —
this is not a cosmetic caveat.
"""

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

    # fromisoformat already parses an explicit UTC offset; .replace() would
    # OVERWRITE that offset instead of converting through it, silently
    # reinterpreting e.g. "...-04:00" as UTC and shifting the timestamp by
    # the offset's magnitude (up to several hours). Only a naive timestamp
    # (no offset) should be assumed to already be UTC.
    if created.tzinfo is not None:
        created_utc = created.astimezone(timezone.utc)
    else:
        created_utc = created.replace(tzinfo=timezone.utc)

    return {
        "download_bits_per_second": float(data["download"]) * BITS_PER_BYTE,
        "upload_bits_per_second": float(data["upload"]) * BITS_PER_BYTE,
        "ping_seconds": float(data["ping"]) / 1000.0,
        "timestamp": int(created_utc.timestamp()),
    }
