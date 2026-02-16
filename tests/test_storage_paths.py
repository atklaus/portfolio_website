from datetime import datetime, timezone

from lib.storage import paths


def test_telemetry_keys_include_date_partition():
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    event_key = paths.telemetry_events_key("session123", ts=ts, rand="abc123")
    session_key = paths.telemetry_sessions_key("session123", ts=ts)

    assert "telemetry/events/date=2024-01-02/" in event_key
    assert event_key.endswith("events_session123_030405_abc123.jsonl.gz")
    assert session_key == "telemetry/sessions/date=2024-01-02/sessions_session123.parquet"


def test_project_prefixes():
    assert paths.datasets_prefix("proj", "data", "v1") == "datasets/proj/data/v1/"
    assert paths.models_prefix("proj", "model", "v2") == "models/proj/model/v2/"
