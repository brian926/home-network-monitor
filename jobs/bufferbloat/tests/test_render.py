from jobs.bufferbloat.render import render_metrics


def test_render_emits_all_required_metric_names():
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    for name in [
        "bufferbloat_idle_rtt_seconds",
        "bufferbloat_loaded_rtt_seconds",
        "bufferbloat_grade",
        "bufferbloat_last_run_timestamp_seconds",
    ]:
        assert name in text


def test_render_converts_milliseconds_to_seconds():
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    assert 'bufferbloat_idle_rtt_seconds{target="1.1.1.1"} 0.012' in text


def test_render_labels_both_load_directions():
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    assert 'direction="download"' in text
    assert 'direction="upload"' in text


def test_render_grades_on_the_worse_direction():
    # Download delta 33 ms (grade B), upload delta 3 ms (grade A+).
    # The worse of the two must win.
    text = render_metrics("1.1.1.1", 12.0, 45.0, 15.0, 1735689600)
    assert "bufferbloat_grade 2" in text


def test_render_ends_with_trailing_newline():
    # The Prometheus text format requires the body to end in a newline.
    text = render_metrics("1.1.1.1", 12.0, 45.0, 38.0, 1735689600)
    assert text.endswith("\n")
