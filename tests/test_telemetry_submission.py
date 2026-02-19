import gzip
import json
import re

from shared.telemetry import session as session_mod
from shared.telemetry import submission as submission_mod
from shared.telemetry import telemetry as telemetry_mod
from shared.telemetry.sinks import LocalSink


def _read_single_event(log_dir):
    files = sorted(log_dir.glob("events/date=*/events_*.jsonl.gz"))
    assert len(files) == 1
    payload = gzip.decompress(files[0].read_bytes()).decode("utf-8")
    lines = [line for line in payload.splitlines() if line.strip()]
    assert len(lines) == 1
    return files[0], json.loads(lines[0])


def test_wnba_submission_event_shape_and_partition(monkeypatch, tmp_path):
    state = {}
    monkeypatch.setattr(telemetry_mod, "_state", lambda: state)
    monkeypatch.setattr(session_mod, "_state", lambda: state)
    monkeypatch.setattr(submission_mod, "_state", lambda: state)
    monkeypatch.setattr(
        telemetry_mod,
        "_get_sinks",
        lambda config: [LocalSink(base_dir=str(tmp_path))],
    )
    monkeypatch.setenv("LOGGING_ENABLED", "true")
    monkeypatch.setenv("LOG_SINK", "local")
    monkeypatch.setenv("LOG_FLUSH_EVENTS", "1")
    monkeypatch.setenv("LOG_FLUSH_SECONDS", "3600")
    monkeypatch.setenv("LOG_MAX_BUFFER", "100")

    inputs = {
        "season": 2025,
        "college": "UConn",
        "player": "Paige Bueckers",
        "offline_mode": False,
        "data_source": "live",
        "email": "should-not-log@example.com",
    }
    telemetry_mod.track_submission(
        page_id="wnba_success",
        form_id="predict",
        inputs=inputs,
        tags={"feature": "predict"},
    )
    # Duplicate immediate rerun should be ignored by idempotency guard.
    telemetry_mod.track_submission(
        page_id="wnba_success",
        form_id="predict",
        inputs=inputs,
        tags={"feature": "predict"},
    )

    event_file, event = _read_single_event(tmp_path)

    assert event["session_id"]
    assert event["visitor_id"]
    assert event["page"] == "wnba_success"
    assert event["event_type"] == "submission"
    assert event["event_name"] == "submission"
    assert event["ts_utc"]

    payload = event["payload"]
    assert payload["submitted_at"]
    assert payload["page_slug"] == "wnba_success"
    assert payload["form_id"] == "predict"
    assert payload["submission_id"]
    assert payload["tags"] == {"feature": "predict"}
    assert payload["fields"]["season"] == 2025
    assert payload["fields"]["college"] == "UConn"
    assert payload["fields"]["player"] == "Paige Bueckers"
    assert "email" not in payload["fields"]

    rel = str(event_file.relative_to(tmp_path))
    assert re.match(r"events/date=\d{4}-\d{2}-\d{2}/events_.+\.jsonl\.gz$", rel)
