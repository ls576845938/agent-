import json
import sys
from pathlib import Path

import pytest

from scripts.research import build_market_state_diagnostic as builder


def test_builder_reads_the_pre_frozen_protocol_blob(monkeypatch):
    observed = []
    payload = {
        "schema_version": "market_state_conditional_policy_protocol_v1",
        "status": "frozen_before_diagnostic",
    }

    def git_bytes(_repo, spec):
        observed.append(spec)
        return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(builder, "_git_bytes", git_bytes)
    raw, protocol = builder._load_frozen_protocol(Path("repo"))

    assert observed == [f"{builder.PROTOCOL_COMMIT}:{builder.PROTOCOL}"]
    assert json.loads(raw) == protocol == payload


def test_builder_refuses_to_overwrite_sealed_output(tmp_path, monkeypatch):
    output = tmp_path / ".agent" / "market_state_evidence" / "sealed.json"
    output.parent.mkdir(parents=True)
    output.write_text("sealed", encoding="utf-8")

    def should_not_build(*_args, **_kwargs):
        raise AssertionError("build must not run before create-only output check")

    monkeypatch.setattr(builder, "build", should_not_build)
    monkeypatch.setattr(sys, "argv", [
        "build_market_state_diagnostic.py",
        "--repo-root", str(tmp_path),
        "--output", str(output),
    ])

    with pytest.raises(FileExistsError, match="market_state_output_already_exists"):
        builder.main()
    assert output.read_text(encoding="utf-8") == "sealed"
