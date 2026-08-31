"""Bufferbloat grading, following the Waveform scale.

Grade is based on the increase in round-trip time under load versus idle,
not on absolute latency: a connection with 80 ms idle RTT and no increase
under load is not bufferbloated.
"""

GRADE_THRESHOLDS_MS = [
    (5.0, "A+"),
    (30.0, "A"),
    (60.0, "B"),
    (200.0, "C"),
    (400.0, "D"),
]
WORST_GRADE = "F"
GRADE_NUMBERS = {"A+": 0, "A": 1, "B": 2, "C": 3, "D": 4, "F": 5}


def parse_ping_rtts(output: str) -> list[float]:
    """Extract per-packet RTTs in milliseconds from `ping` output."""
    rtts = []
    for line in output.splitlines():
        if "time=" not in line:
            continue
        try:
            rtts.append(float(line.split("time=")[1].split()[0]))
        except (IndexError, ValueError):
            continue
    return rtts


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile. `p` is a fraction between 0 and 1."""
    if not values:
        raise ValueError("percentile() requires at least one value")
    if len(values) == 1:
        return values[0]

    ordered = sorted(values)
    position = p * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def grade_from_delta_ms(delta_ms: float) -> str:
    """Map a latency increase under load to a Waveform-style letter grade."""
    for threshold, grade in GRADE_THRESHOLDS_MS:
        if delta_ms < threshold:
            return grade
    return WORST_GRADE


def grade_to_number(grade: str) -> int:
    """Map a letter grade to 0 (best) through 5 (worst) for graphing."""
    return GRADE_NUMBERS[grade]
