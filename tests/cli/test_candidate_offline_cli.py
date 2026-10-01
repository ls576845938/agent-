"""Local TCP CLI against the same actual HTTP app, never external endpoints."""
from contextlib import contextmanager
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def local_backend(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0)); sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=sock.getsockname()[1], log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(500):
            if server.started: break
            time.sleep(.01)
        assert server.started
        yield "http://127.0.0.1:" + str(sock.getsockname()[1])
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


def cli(url, credential, *args):
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "backend.app.cli.candidate_offline",
        "--url", url, "--key-stdin", *args], input=credential + "\n", text=True, capture_output=True, cwd=ROOT, timeout=60)
    assert credential not in result.stdout and credential not in result.stderr
    return result.returncode, json.loads(result.stdout)


def test_cli_uses_real_local_router_and_cannot_bypass_default_off(tmp_path):
    from tests.contracts.test_candidate_offline_access import empty_service
    from fastapi import FastAPI
    from backend.app.api.candidate_offline import build_candidate_offline_router
    _, service = empty_service(tmp_path)
    app = FastAPI(); app.include_router(build_candidate_offline_router(service), prefix="/api")
    with local_backend(app) as url:
        code, value = cli(url, "test-only", "list")
        assert code == 0 and value["jobs"] == []
        code, value = cli(url, "test-only", "publish", "unknown", "--expected-revision", "0", "--request-key", "same")
        assert code == 2 and value["http_status"] == 423
        assert cli(url, "wrong-test-only", "list")[0] == 2
    assert not service.store.path.exists()
