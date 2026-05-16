#!/usr/bin/env python3
"""Start Alpha Radar API server.

Usage
-----
    python run_server.py            # from alpha-radar/
    python run_server.py --port 8100

Without any arguments the server listens on ``0.0.0.0:8100``.
"""

import sys
from pathlib import Path

# Ensure the project root (alpha-radar/) is on sys.path so that
# ``backend.main`` and ``backend.persistence`` can be imported.
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.main import run, DEFAULT_PORT

if __name__ == "__main__":
    # Minimal CLI override for port
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:]):
            if arg == "--port" and i + 2 < len(sys.argv):
                port = int(sys.argv[i + 2])

    run(port=port)
