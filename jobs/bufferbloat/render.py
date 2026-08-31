"""Prometheus text exposition format rendering for the bufferbloat job."""

from .grade import grade_from_delta_ms, grade_to_number


def render_metrics(
    target: str,
    idle_ms: float,
    loaded_download_ms: float,
    loaded_upload_ms: float,
    timestamp: int,
) -> str:
    """Render one bufferbloat result as Prometheus text exposition.

    The reported grade reflects the worse of the two load directions, since
    a connection that collapses only on upload is still bufferbloated.
    """
    download_delta = loaded_download_ms - idle_ms
    upload_delta = loaded_upload_ms - idle_ms
    worst_delta = max(download_delta, upload_delta)
    grade = grade_to_number(grade_from_delta_ms(worst_delta))

    lines = [
        "# HELP bufferbloat_idle_rtt_seconds Idle round-trip time",
        "# TYPE bufferbloat_idle_rtt_seconds gauge",
        f'bufferbloat_idle_rtt_seconds{{target="{target}"}} {idle_ms / 1000:.6g}',
        "# HELP bufferbloat_loaded_rtt_seconds Round-trip time under load",
        "# TYPE bufferbloat_loaded_rtt_seconds gauge",
        f'bufferbloat_loaded_rtt_seconds{{target="{target}",direction="download"}}'
        f" {loaded_download_ms / 1000:.6g}",
        f'bufferbloat_loaded_rtt_seconds{{target="{target}",direction="upload"}}'
        f" {loaded_upload_ms / 1000:.6g}",
        "# HELP bufferbloat_grade Waveform-style grade, 0 best to 5 worst",
        "# TYPE bufferbloat_grade gauge",
        f"bufferbloat_grade {grade}",
        "# HELP bufferbloat_last_run_timestamp_seconds Unix time of last run",
        "# TYPE bufferbloat_last_run_timestamp_seconds gauge",
        f"bufferbloat_last_run_timestamp_seconds {timestamp}",
    ]
    return "\n".join(lines) + "\n"
