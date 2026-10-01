from pathlib import Path


def test_runtime_boundary_audit_exists() -> None:
    path = Path("docs/research/RUNTIME_BOUNDARY_AUDIT.md")

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "PAPER QUEUE: LOCKED" in text
    assert "LIVE: FROZEN" in text
