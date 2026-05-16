"""Tests for the research audit HTTP API handler.

Since ``BaseHTTPRequestHandler`` is designed for a server, we test the
handler logic by constructing instances with dummy socket objects and
inspecting the buffered response via ``BytesIO``.
"""

import io
import json
import os
import tempfile
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.main import ResearchAuditHandler, os_environ
from backend.persistence import save_audit_result


# ---------------------------------------------------------------------------
# Helpers to simulate HTTP requests
# ---------------------------------------------------------------------------

class FakeSocket:
    """Minimal socket-like object for testing BaseHTTPRequestHandler."""

    def __init__(self, data: bytes = b"") -> None:
        self._data = data
        self._makefile_data = io.BytesIO(data)

    def makefile(self, mode: str, *args, **kwargs) -> io.BytesIO:
        if "r" in mode or "b" in mode:
            return io.BytesIO(self._data)
        return io.BytesIO()


class _FakeServer:
    """Minimal server stand-in to satisfy BaseHTTPRequestHandler internals."""

    def __init__(self):
        self.server_name = "test"
        self.server_port = 0


class FakeRequestHandler(ResearchAuditHandler):
    """Subclass that writes to a BytesIO buffer instead of a real socket."""

    def __init__(self, method: str, path: str, body: str = "", data_dir: str = ""):
        self._data_dir = data_dir
        self.client_address = ("127.0.0.1", 0)
        self.server = _FakeServer()
        raw_request = f"{method} {path} HTTP/1.1\r\nHost: test\r\n"
        if body:
            raw_request += f"Content-Length: {len(body.encode('utf-8'))}\r\n"
        raw_request += "\r\n"
        raw_request += body

        self.rfile = io.BytesIO(raw_request.encode("utf-8"))
        self.wfile = io.BytesIO()
        self.raw_requestline = self.rfile.readline()
        self.parse_request()

    def address_string(self) -> str:
        return "127.0.0.1"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _parse_response(handler: FakeRequestHandler) -> tuple[int, dict, str]:
    """Return ``(status_code, headers_dict, body_string)`` from handler."""
    wfile = handler.wfile
    wfile.seek(0)
    raw = wfile.read().decode("utf-8")
    # split on first blank line
    header_part, _, body = raw.partition("\r\n\r\n")
    # first line: e.g. "HTTP/1.1 200 OK"
    lines = header_part.split("\r\n")
    status_line = lines[0]
    status_code = int(status_line.split(" ")[1])
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return status_code, headers, body


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_data_dir():
    """Create a temporary directory with a couple of seeded audit results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        save_audit_result(
            {
                "audit_id": "existing-1",
                "target_type": "signal",
                "target_id": "sig_abc",
                "audit_score": 90.0,
                "audit_status": "HIGH_CONVICTION",
                "report_markdown": "# Good",
            },
            data_dir=tmpdir,
        )
        yield tmpdir


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

class TestCors:
    def test_options_returns_204_with_cors(self):
        handler = FakeRequestHandler("OPTIONS", "/api/research-audit/run")
        handler.do_OPTIONS()
        status, headers, body = _parse_response(handler)
        assert status == 204
        assert headers.get("access-control-allow-origin") == "*"
        assert headers.get("access-control-allow-methods") == "GET, POST, OPTIONS"


# ---------------------------------------------------------------------------
# GET /api/research-audit/result/{audit_id}
# ---------------------------------------------------------------------------

class TestGetResult:
    def test_returns_existing_result(self, seeded_data_dir):
        handler = FakeRequestHandler("GET", "/api/research-audit/result/existing-1")
        import backend.main as main_mod

        def patched_load(audit_id, data_dir=None):
            from backend.persistence import load_audit_result as real_load
            return real_load(audit_id, data_dir=seeded_data_dir)

        with patch.object(main_mod, "load_audit_result", side_effect=patched_load):
            handler._handle_get_result("existing-1")
            status, headers, body = _parse_response(handler)
            assert status == 200
            data = json.loads(body)
            assert data["audit_id"] == "existing-1"
            assert data["audit_score"] == 90.0

    def test_missing_result_returns_404(self):
        handler = FakeRequestHandler("GET", "/api/research-audit/result/nonexistent")
        handler._handle_get_result("nonexistent")
        status, headers, body = _parse_response(handler)
        assert status == 404
        data = json.loads(body)
        assert "not found" in data.get("error", "").lower()

    def test_empty_audit_id_returns_400(self):
        handler = FakeRequestHandler("GET", "/api/research-audit/result/")
        handler._handle_get_result("")
        status, headers, body = _parse_response(handler)
        assert status == 400
        data = json.loads(body)
        assert "audit_id" in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# GET /api/research-audit/target/{target_type}/{target_id}
# ---------------------------------------------------------------------------

class TestGetByTarget:
    def test_returns_matching_results(self, seeded_data_dir):
        handler = FakeRequestHandler("GET", "/api/research-audit/target/signal/sig_abc")
        import backend.main as main_mod

        with patch.object(main_mod, "find_audit_results_by_target") as mock_find:
            mock_find.return_value = [{"audit_id": "existing-1"}]
            handler._handle_find_by_target("signal", "sig_abc")
            status, headers, body = _parse_response(handler)
            assert status == 200
            data = json.loads(body)
            assert isinstance(data, list)
            assert len(data) == 1

    def test_returns_empty_list_when_no_match(self):
        handler = FakeRequestHandler("GET", "/api/research-audit/target/signal/no_match")
        handler._handle_find_by_target("signal", "no_match")
        status, headers, body = _parse_response(handler)
        assert status == 200
        data = json.loads(body)
        assert data == []

    def test_missing_params_returns_400(self):
        handler = FakeRequestHandler("GET", "/api/research-audit/target/")
        handler._handle_find_by_target("", "")
        status, headers, body = _parse_response(handler)
        assert status == 400


# ---------------------------------------------------------------------------
# POST /api/research-audit/run
# ---------------------------------------------------------------------------

class TestPostRun:
    """Post-run tests need a stub runner since ``run_research_audit``
    is not yet wired by the research_audit agent."""

    @staticmethod
    def _stub_runner(target):
        from backend.research_audit.schemas import ResearchAuditResult
        return ResearchAuditResult(
            audit_id="stub-id",
            target_type=target.target_type,
            target_id=target.target_id,
        )

    def _make_handler(self, body: str = "") -> FakeRequestHandler:
        return FakeRequestHandler("POST", "/api/research-audit/run", body=body)

    def test_empty_body_returns_400(self):
        import backend.main as main_mod
        with patch.object(main_mod, "_get_audit_runner", return_value=self._stub_runner):
            handler = self._make_handler()
            handler._handle_run_audit()
            status, headers, body = _parse_response(handler)
            assert status == 400
            data = json.loads(body)
            assert "empty" in data.get("error", "").lower()

    def test_invalid_json_returns_400(self):
        import backend.main as main_mod
        with patch.object(main_mod, "_get_audit_runner", return_value=self._stub_runner):
            handler = self._make_handler(body="not json")
            handler._handle_run_audit()
            status, headers, body = _parse_response(handler)
            assert status == 400
            data = json.loads(body)
            assert "json" in data.get("error", "").lower()

    def test_missing_target_type_returns_validation_error(self):
        import backend.main as main_mod
        body_data = json.dumps({"target_id": "x", "target_type": "invalid"})
        with patch.object(main_mod, "_get_audit_runner", return_value=self._stub_runner):
            handler = self._make_handler(body=body_data)
            handler._handle_run_audit()
            status, headers, body = _parse_response(handler)
            assert status == 400
            data = json.loads(body)
            assert "validation" in data.get("error", "").lower()

    def test_missing_signal_keys_returns_validation_error(self):
        import backend.main as main_mod
        body_data = json.dumps({
            "target_type": "signal",
            "target_id": "sig_1",
            "signals": [{"not_name": "x"}],
        })
        with patch.object(main_mod, "_get_audit_runner", return_value=self._stub_runner):
            handler = self._make_handler(body=body_data)
            handler._handle_run_audit()
            status, headers, body = _parse_response(handler)
            assert status == 400
            data = json.loads(body)
            assert "validation" in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# os_environ helper
# ---------------------------------------------------------------------------

class TestOsEnviron:
    def test_returns_default_when_missing(self):
        val = os_environ("ALPHA_RADAR_SOME_UNSET_VAR", "fallback")
        assert val == "fallback"

    def test_returns_env_value(self):
        os.environ["ALPHA_RADAR_TEST_VAR"] = "hello"
        try:
            val = os_environ("ALPHA_RADAR_TEST_VAR", "fallback")
            assert val == "hello"
        finally:
            del os.environ["ALPHA_RADAR_TEST_VAR"]
