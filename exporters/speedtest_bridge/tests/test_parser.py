import pytest

from exporters.speedtest_bridge.parser import parse_latest_result

SAMPLE = {
    "data": {
        "id": 42,
        "ping": 12.345,
        "download": 115000000.0,   # bytes per second
        "upload": 4300000.0,
        "created_at": "2026-08-31T14:06:03.000000Z",
    }
}


def test_parse_converts_bytes_per_second_to_bits():
    result = parse_latest_result(SAMPLE)
    assert result["download_bits_per_second"] == 920000000.0


def test_parse_converts_upload_to_bits():
    result = parse_latest_result(SAMPLE)
    assert result["upload_bits_per_second"] == 34400000.0


def test_parse_converts_ping_milliseconds_to_seconds():
    result = parse_latest_result(SAMPLE)
    assert result["ping_seconds"] == pytest.approx(0.012345)


def test_parse_converts_timestamp_to_unix_epoch():
    result = parse_latest_result(SAMPLE)
    assert result["timestamp"] == 1788185163


def test_parse_raises_on_missing_data_key():
    with pytest.raises(ValueError):
        parse_latest_result({})


def test_parse_raises_on_null_measurement():
    with pytest.raises(ValueError):
        parse_latest_result({"data": {"ping": None, "download": None,
                                      "upload": None, "created_at": None}})
