"""Parsing for MB8611 HNAP channel strings.

The modem returns channel tables as caret-delimited rows joined by "|+|",
with inconsistent padding whitespace around numeric fields.

CAVEAT — UNVERIFIED FIELD ORDER:
The field order encoded below (and the fixture in
tests/fixtures/downstream.txt) was derived from a REPRESENTATIVE SAMPLE
documented in the Task 5 brief, NOT from a live capture of this household's
actual MB8611 firmware. Task 5 Step 1 (a discovery script that logs into the
real modem at 192.168.100.1 and dumps its raw HNAP response) could not be
run from this environment, because the modem is unreachable except from the
deploy host (apollo).

Before trusting any dashboard or alert built on these metrics, the repo
owner MUST:
  1. Run the Step 1 discovery script on apollo against the real modem.
  2. Compare the captured field order to the indices used in
     parse_downstream()/parse_upstream() below.
  3. Update this parser and its tests (test_parser.py, fixtures/downstream.txt)
     to match the real response if the order differs.

A firmware mismatch here would silently mis-map fields (e.g. SNR onto the
power column) and produce confident, wrong DOCSIS dashboards — this is not
a cosmetic caveat.
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
