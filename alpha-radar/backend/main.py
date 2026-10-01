"""
Alpha Radar Backend API Server.

Provides a lightweight HTTP JSON API for the research audit subsystem using
only Python stdlib (no external dependencies).

Endpoints
---------
POST /api/research-audit/run
    Accept a ResearchAuditTarget JSON body, run the audit, persist the
    result, and return ``{audit_id, audit_status, audit_score}``.

GET  /api/research-audit/result/<audit_id>
    Return the full ResearchAuditResult JSON.  404 if not found.

GET  /api/research-audit/target/<target_type>/<target_id>
    Return a JSON list of all audit results for the given target.

Run
---
    python run_server.py              # from alpha-radar/
    python -m backend.main           # from alpha-radar/
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Import persistence (our own module, always available)
# ---------------------------------------------------------------------------
from backend.persistence import (
    save_audit_result,
    load_audit_result,
    find_audit_results_by_target,
)

# ---------------------------------------------------------------------------
# Import schemas (exists now — created by the research_audit agent)
# ---------------------------------------------------------------------------
from backend.research_audit.schemas import (
    ResearchAuditTarget,
    validate_target,
)

# ---------------------------------------------------------------------------
# Lazy import: run_research_audit is created by another agent and may not
# exist at module-load time.  We defer the import so GET endpoints work
# even when the runner is not yet wired.
# ---------------------------------------------------------------------------

_audit_runner = None  # cached reference

def _get_audit_runner():
    global _audit_runner
    if _audit_runner is not None:
        return _audit_runner
    try:
        from backend.research_audit import run_research_audit as _fn
        _audit_runner = _fn
    except (ImportError, AttributeError):
        _audit_runner = False  # sentinel for "not available"
    return _audit_runner


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_PREFIX = "/api/research-audit"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8100


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class ResearchAuditHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Alpha Radar research audit API."""

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(
        self,
        status_code: int,
        data: Any,
    ) -> None:
        body = json.dumps(data, ensure_ascii=False, sort_keys=False).encode("utf-8")
        self.send_response(status_code)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status_code: int, message: str) -> None:
        self._send_json(status_code, {"error": message})

    # ------------------------------------------------------------------
    # OPTIONS (CORS preflight)
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == f"{API_PREFIX}/run":
            self._handle_run_audit()
        else:
            self._send_error_json(404, f"Not found: {self.path}")

    def _handle_run_audit(self) -> None:
        # --- ensure the audit runner is wired ----------------------------
        runner = _get_audit_runner()
        if runner is False:
            self._send_error_json(
                500,
                "research_audit runner is not yet available; "
                "ensure backend.research_audit defines run_research_audit",
            )
            return

        # --- parse body --------------------------------------------------
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            content_length = 0

        if content_length == 0:
            self._send_error_json(400, "Request body is empty")
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload: Dict[str, Any] = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            self._send_error_json(400, f"Invalid JSON: {exc}")
            return

        # --- build target ------------------------------------------------
        try:
            target = ResearchAuditTarget.from_dict(payload)
        except Exception as exc:
            self._send_error_json(400, f"Failed to build target: {exc}")
            return

        # --- validate target ---------------------------------------------
        errors: List[str] = validate_target(target)
        if errors:
            self._send_error_json(400, f"Validation error(s): {'; '.join(errors)}")
            return

        # --- run audit ---------------------------------------------------
        try:
            result = runner(target)
        except Exception as exc:
            tb = traceback.format_exc()
            self._send_error_json(
                500,
                f"Audit runner failed: {exc}\n{tb}" if self._is_debug() else str(exc),
            )
            return

        # --- persist -----------------------------------------------------
        result_dict = result.to_dict()
        try:
            save_audit_result(result_dict)
        except OSError as exc:
            self._send_error_json(500, f"Failed to persist result: {exc}")
            return

        # --- respond with summary ----------------------------------------
        self._send_json(201, {
            "audit_id": result_dict["audit_id"],
            "audit_status": result_dict["audit_status"],
            "audit_score": result_dict["audit_score"],
        })

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith(f"{API_PREFIX}/result/"):
            audit_id = path[len(f"{API_PREFIX}/result/"):]
            self._handle_get_result(audit_id)

        elif path.startswith(f"{API_PREFIX}/target/"):
            remaining = path[len(f"{API_PREFIX}/target/"):]
            parts = remaining.split("/", 1)
            if len(parts) == 2:
                target_type, target_id = parts
                self._handle_find_by_target(target_type, target_id)
            else:
                self._send_error_json(400, "Expected path: /api/research-audit/target/{target_type}/{target_id}")

        else:
            self._send_error_json(404, f"Not found: {self.path}")

    def _handle_get_result(self, audit_id: str) -> None:
        if not audit_id:
            self._send_error_json(400, "audit_id is required")
            return
        result = load_audit_result(audit_id)
        if result is None:
            self._send_error_json(404, f"Audit result not found: {audit_id}")
            return
        self._send_json(200, result)

    def _handle_find_by_target(self, target_type: str, target_id: str) -> None:
        if not target_type or not target_id:
            self._send_error_json(400, "target_type and target_id are required")
            return
        results = find_audit_results_by_target(target_type, target_id)
        self._send_json(200, results)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_debug(self) -> bool:
        return os_environ("ALPHA_RADAR_DEBUG", "").lower() in ("1", "true", "yes")

    def log_message(self, format: str, *args: Any) -> None:
        """Override to avoid printing full request paths (optional)."""
        super().log_message(format, *args)


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------

def run(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Start the Alpha Radar API server (blocking)."""
    server = HTTPServer((host, port), ResearchAuditHandler)
    print(f"Alpha Radar API server listening on http://{host}:{port}")
    print(f"  POST {API_PREFIX}/run")
    print(f"  GET  {API_PREFIX}/result/<audit_id>")
    print(f"  GET  {API_PREFIX}/target/<target_type>/<target_id>")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


# ---------------------------------------------------------------------------
# Provide os.environ accessor for the debug flag mockable in tests
# ---------------------------------------------------------------------------

def os_environ(key: str, default: str = "") -> str:
    """Thin wrapper around ``os.environ.get``, overridable in tests."""
    import os
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
