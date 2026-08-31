from exporters.speedtest_bridge.exporter import SpeedtestCollector

RESULT = {
    "download_bits_per_second": 920000000.0,
    "upload_bits_per_second": 34400000.0,
    "ping_seconds": 0.012345,
    "timestamp": 1788185163,
}

EXPECTED_METRIC_NAMES = {
    "speedtest_download_bits_per_second",
    "speedtest_upload_bits_per_second",
    "speedtest_ping_seconds",
    "speedtest_last_run_timestamp_seconds",
}


def test_fresh_collector_yields_no_series():
    collector = SpeedtestCollector()
    assert list(collector.collect()) == []


def test_collector_yields_all_four_metrics_after_update():
    collector = SpeedtestCollector()
    collector.update(RESULT)

    families = list(collector.collect())
    names = {family.name for family in families}
    assert names == EXPECTED_METRIC_NAMES

    values = {family.name: family.samples[0].value for family in families}
    assert values["speedtest_download_bits_per_second"] == 920000000.0
    assert values["speedtest_upload_bits_per_second"] == 34400000.0
    assert values["speedtest_ping_seconds"] == 0.012345
    assert values["speedtest_last_run_timestamp_seconds"] == 1788185163


def test_update_with_none_does_not_wipe_previous_result():
    collector = SpeedtestCollector()
    collector.update(RESULT)

    collector.update(None)

    families = list(collector.collect())
    names = {family.name for family in families}
    assert names == EXPECTED_METRIC_NAMES
    values = {family.name: family.samples[0].value for family in families}
    assert values["speedtest_download_bits_per_second"] == 920000000.0
