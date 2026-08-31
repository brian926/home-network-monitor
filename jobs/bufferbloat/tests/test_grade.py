import pytest

from jobs.bufferbloat.grade import (
    grade_from_delta_ms,
    grade_to_number,
    parse_ping_rtts,
    percentile,
)

PING_OUTPUT = """PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.3 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=11.8 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=14.1 ms

--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 11.800/12.733/14.100/0.982 ms
"""


def test_parse_ping_rtts_extracts_all_samples():
    assert parse_ping_rtts(PING_OUTPUT) == [12.3, 11.8, 14.1]


def test_parse_ping_rtts_ignores_summary_lines():
    # The summary line contains "ms" but no "time=" and must not be counted.
    assert len(parse_ping_rtts(PING_OUTPUT)) == 3


def test_parse_ping_rtts_handles_total_loss():
    assert parse_ping_rtts("3 packets transmitted, 0 received") == []


def test_percentile_returns_interpolated_value():
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 25.0


def test_percentile_of_single_value():
    assert percentile([42.0], 0.95) == 42.0


def test_percentile_of_empty_list_raises():
    with pytest.raises(ValueError):
        percentile([], 0.95)


@pytest.mark.parametrize("delta_ms,expected", [
    (0.0, "A+"),
    (4.9, "A+"),
    (5.0, "A"),
    (29.9, "A"),
    (30.0, "B"),
    (59.9, "B"),
    (60.0, "C"),
    (199.9, "C"),
    (200.0, "D"),
    (399.9, "D"),
    (400.0, "F"),
    (5000.0, "F"),
])
def test_grade_from_delta_ms(delta_ms, expected):
    assert grade_from_delta_ms(delta_ms) == expected


def test_grade_to_number_orders_best_to_worst():
    grades = ["A+", "A", "B", "C", "D", "F"]
    numbers = [grade_to_number(g) for g in grades]
    assert numbers == [0, 1, 2, 3, 4, 5]
