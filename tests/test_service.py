"""HTTP service smoke tests."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from label_printer.service import app  # noqa: E402
from label_printer.status import build_mock_status, parse_status  # noqa: E402
from label_printer.transport.base import StatusUnavailable  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "printer_configured" in r.json()


def test_templates(client):
    r = client.get("/templates")
    assert r.status_code == 200
    names = {t["qualified"] for t in r.json()}
    assert "kitchen/pantry_jar" in names
    assert "three_d_printing/filament_spool" in names


def test_render_returns_png(client):
    r = client.post("/render", json={
        "template": "kitchen/pantry_jar",
        "tape_mm": 12,
        "fields": {"name": "FLOUR", "purchased": "2026-04-19"},
    })
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_print_dryrun_returns_raster(client):
    r = client.post("/print", json={
        "template": "kitchen/spice",
        "tape_mm": 12,
        "fields": {"name": "Paprika"},
    })
    assert r.status_code == 200
    assert r.headers["x-dry-run"] == "true"
    assert int(r.headers["x-bytes"]) == len(r.content)
    assert r.content.endswith(b"\x1a")


def test_print_send_without_host_returns_503(client, monkeypatch):
    monkeypatch.delenv("LABEL_PRINTER_HOST", raising=False)
    monkeypatch.setattr(
        "label_printer.service.state_mod.resolve_printer_host",
        lambda: None,
    )
    r = client.post("/print", json={
        "template": "kitchen/spice",
        "tape_mm": 12,
        "fields": {"name": "Paprika"},
        "send": True,
    })
    assert r.status_code == 503
    assert "no printer host" in r.json()["detail"]


def test_health_survives_corrupt_state_file(client, monkeypatch, tmp_path):
    """A corrupt state.toml must not take down the liveness probe."""
    monkeypatch.delenv("LABEL_PRINTER_HOST", raising=False)
    monkeypatch.setenv("LABEL_PRINTER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "state.toml").write_text("printer_host = [not, valid, toml\n")
    import importlib

    from label_printer import state as state_mod
    importlib.reload(state_mod)
    try:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "printer_configured": False}
    finally:
        importlib.reload(state_mod)


def test_resolve_printer_host_env_wins_over_state(monkeypatch, tmp_path):
    monkeypatch.setenv("LABEL_PRINTER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LABEL_PRINTER_HOST", "192.0.2.9")
    (tmp_path / "state.toml").write_text("printer_host = '10.0.0.1'\n")
    import importlib

    from label_printer import state as state_mod
    importlib.reload(state_mod)
    try:
        assert state_mod.resolve_printer_host() == "192.0.2.9"
    finally:
        importlib.reload(state_mod)


def test_print_send_happy_path(client, monkeypatch):
    """send=true drives NetworkTransport; mock it to capture the payload."""
    sent: list[bytes] = []

    class FakeTransport:
        def __init__(self, host):
            self.host = host
        def query_status(self):
            return parse_status(build_mock_status(media_width_mm=12))
        def send(self, data: bytes):
            sent.append(data)

    monkeypatch.setenv("LABEL_PRINTER_HOST", "192.0.2.1")
    monkeypatch.setattr("label_printer.service.NetworkTransport", FakeTransport)

    r = client.post("/print", json={
        "template": "kitchen/spice",
        "tape_mm": 12,
        "fields": {"name": "Paprika"},
        "send": True,
    })
    assert r.status_code == 200
    assert r.headers["x-dry-run"] == "false"
    body = r.json()
    assert body["sent"] is True
    assert body["host"] == "192.0.2.1"
    assert body["bytes"] == len(sent[0])
    assert "warning" not in body


def test_print_send_snmp_unavailable_warns_but_sends(client, monkeypatch):
    """If SNMP is disabled on the printer, we warn but still send."""
    sent: list[bytes] = []

    class FakeTransport:
        def __init__(self, host):
            self.host = host
        def query_status(self):
            raise StatusUnavailable("SNMP disabled")
        def send(self, data: bytes):
            sent.append(data)

    monkeypatch.setenv("LABEL_PRINTER_HOST", "192.0.2.1")
    monkeypatch.setattr("label_printer.service.NetworkTransport", FakeTransport)

    r = client.post("/print", json={
        "template": "kitchen/spice",
        "tape_mm": 12,
        "fields": {"name": "Paprika"},
        "send": True,
    })
    assert r.status_code == 200
    assert len(sent) == 1
    assert "warning" in r.json()


def test_print_send_tape_mismatch_returns_409(client, monkeypatch):
    class FakeTransport:
        def __init__(self, host):
            self.host = host
        def query_status(self):
            return parse_status(build_mock_status(media_width_mm=24))
        def send(self, data: bytes):
            raise AssertionError("should not send on tape mismatch")

    monkeypatch.setenv("LABEL_PRINTER_HOST", "192.0.2.1")
    monkeypatch.setattr("label_printer.service.NetworkTransport", FakeTransport)

    r = client.post("/print", json={
        "template": "kitchen/spice",
        "tape_mm": 12,
        "fields": {"name": "Paprika"},
        "send": True,
    })
    assert r.status_code == 409


def test_print_send_unreachable_returns_502(client, monkeypatch):
    class FakeTransport:
        def __init__(self, host):
            self.host = host
        def query_status(self):
            raise StatusUnavailable("no SNMP in test")
        def send(self, data: bytes):
            raise OSError("connection refused")

    monkeypatch.setenv("LABEL_PRINTER_HOST", "192.0.2.1")
    monkeypatch.setattr("label_printer.service.NetworkTransport", FakeTransport)

    r = client.post("/print", json={
        "template": "kitchen/spice",
        "tape_mm": 12,
        "fields": {"name": "Paprika"},
        "send": True,
    })
    assert r.status_code == 502
    assert "could not reach printer" in r.json()["detail"]


def test_auth_when_token_set(client, monkeypatch):
    monkeypatch.setenv("LABEL_PRINTER_TOKEN", "s3cret")
    r = client.get("/templates")
    assert r.status_code == 401
    r = client.get("/templates", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403
    r = client.get("/templates", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_missing_template_404(client):
    r = client.post("/render", json={"template": "nope/nope", "tape_mm": 12, "fields": {}})
    assert r.status_code == 404
