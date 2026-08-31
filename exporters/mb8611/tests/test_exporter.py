import pytest

from exporters.mb8611.exporter import (
    POWER,
    SNR,
    UNCORRECTABLE,
    _parse_interval_seconds,
    collect,
)

DOWNSTREAM_RAW = "1^Locked^QAM256^5^567.0^ 1.5^40.9^1234^5^"
UPSTREAM_RAW = "1^Locked^SC-QAM^1^5120^30.6^ 45.0^"

GOOD_STATUS = {
    "GetMotoStatusDownstreamChannelInfoResponse": {
        "MotoConnDownstreamChannel": DOWNSTREAM_RAW,
    },
    "GetMotoStatusUpstreamChannelInfoResponse": {
        "MotoConnUpstreamChannel": UPSTREAM_RAW,
    },
}


class FakeClient:
    def __init__(self, status):
        self._status = status

    def fetch_status(self):
        return self._status


def _clear_all():
    SNR.clear()
    POWER.clear()
    UNCORRECTABLE.clear()


def _sample_count(gauge):
    return len(gauge.collect()[0].samples)


# --- FIX 2: interval parsing must never crash, and must never go below 60 ---

def test_parse_interval_empty_string_yields_floor():
    assert _parse_interval_seconds("") == 60


def test_parse_interval_below_floor_is_clamped():
    assert _parse_interval_seconds("10") == 60


def test_parse_interval_valid_value_above_floor_is_respected():
    assert _parse_interval_seconds("120") == 120


def test_parse_interval_garbage_yields_floor():
    assert _parse_interval_seconds("not-a-number") == 60


# --- FIX 3: a failed collect must clear the labelled gauges, not hold stale values ---

def test_collect_success_then_failure_clears_gauges():
    _clear_all()
    try:
        collect(FakeClient(GOOD_STATUS))
        assert _sample_count(SNR) > 0
        assert _sample_count(POWER) > 0
        assert _sample_count(UNCORRECTABLE) > 0

        collect(FakeClient(None))

        assert _sample_count(SNR) == 0
        assert _sample_count(POWER) == 0
        assert _sample_count(UNCORRECTABLE) == 0
    finally:
        _clear_all()
