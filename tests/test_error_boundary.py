from __future__ import annotations

from lib.errors import boundary


class _DummyPlaceholder:
    def __init__(self) -> None:
        self.cleared = False

    def container(self):
        return self

    def empty(self):
        self.cleared = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyStreamlit:
    def empty(self):
        return _DummyPlaceholder()

    def expander(self, label: str):
        return _DummyPlaceholder()

    def exception(self, exc: Exception) -> None:
        return None


def test_boundary_generates_trace_id(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setattr(boundary, "st", _DummyStreamlit())

    captured: dict[str, str] = {}

    def _fake_log_exception(exc: Exception, trace_id: str, page_id: str, extra: dict | None):
        captured["trace_id"] = trace_id

    monkeypatch.setattr(boundary, "log_exception", _fake_log_exception)
    monkeypatch.setattr(boundary, "render_error_banner", lambda trace_id: None)

    def _boom():
        raise ValueError("boom")

    boundary.run_with_error_boundary(_boom, page_id="test", context={})

    assert "trace_id" in captured
    assert len(captured["trace_id"]) == 10


def test_boundary_calls_log_exception(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setattr(boundary, "st", _DummyStreamlit())

    calls = {"count": 0}

    def _fake_log_exception(exc: Exception, trace_id: str, page_id: str, extra: dict | None):
        calls["count"] += 1

    monkeypatch.setattr(boundary, "log_exception", _fake_log_exception)
    monkeypatch.setattr(boundary, "render_error_banner", lambda trace_id: None)

    def _boom():
        raise RuntimeError("boom")

    boundary.run_with_error_boundary(_boom, page_id="test", context={})

    assert calls["count"] == 1


def test_boundary_prod_renders_banner_without_details(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setattr(boundary, "st", _DummyStreamlit())

    calls = {"banner": 0, "details": 0}

    monkeypatch.setattr(boundary, "log_exception", lambda *args, **kwargs: None)
    monkeypatch.setattr(boundary, "render_error_banner", lambda trace_id: calls.__setitem__("banner", calls["banner"] + 1))

    def _fake_details(exc: Exception) -> None:
        calls["details"] += 1

    monkeypatch.setattr(boundary, "_render_exception_details", _fake_details)

    def _boom():
        raise RuntimeError("boom")

    boundary.run_with_error_boundary(_boom, page_id="test", context={})

    assert calls["banner"] == 1
    assert calls["details"] == 0
