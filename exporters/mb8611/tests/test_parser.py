from pathlib import Path

from exporters.mb8611.parser import parse_downstream, parse_upstream

FIXTURE = Path(__file__).parent / "fixtures" / "downstream.txt"


def test_parse_downstream_returns_one_dict_per_channel():
    channels = parse_downstream(FIXTURE.read_text())
    assert len(channels) == 3


def test_parse_downstream_extracts_typed_fields():
    first = parse_downstream(FIXTURE.read_text())[0]
    assert first["channel"] == "1"
    assert first["lock_status"] == "Locked"
    assert first["modulation"] == "QAM256"
    assert first["frequency_mhz"] == 567.0
    assert first["power_dbmv"] == 1.5
    assert first["snr_db"] == 40.9
    assert first["corrected"] == 1234
    assert first["uncorrected"] == 5


def test_parse_downstream_strips_padding_whitespace():
    # The modem pads the power field with a leading space.
    channels = parse_downstream("1^Locked^QAM256^5^567.0^ 1.5^40.9^1234^5^")
    assert channels[0]["power_dbmv"] == 1.5


def test_parse_downstream_ignores_malformed_rows():
    channels = parse_downstream("1^Locked^QAM256^5^567.0^ 1.5^40.9^1234^5^|+|garbage")
    assert len(channels) == 1


def test_parse_downstream_handles_empty_input():
    assert parse_downstream("") == []


def test_parse_upstream_extracts_typed_fields():
    raw = "1^Locked^SC-QAM^1^5120^35.6^45.5^"
    first = parse_upstream(raw)[0]
    assert first["channel"] == "1"
    assert first["lock_status"] == "Locked"
    assert first["frequency_mhz"] == 35.6
    assert first["power_dbmv"] == 45.5
