"""Run the already-frozen five phases once and seal a readonly review object.

This CLI is offline-only. The transient venue/runtime stay outside the Git
worktree; the small committed JSON is the only item the backend may read.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import socket
import subprocess

from backend.app.services.donchian_offline_views import (
    build_donchian_summary, seal_summary, validate_donchian_summary,
)
from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
from quant_crypto.application.donchian_offline_replay import (
    DonchianOfflineReplay, DonchianOfflineReplayConfig, build_closeout_scenario,
)


def deny_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("donchian_closeout_network_denied")


def build(repo_root: Path, state_dir: Path) -> dict:
    # Git's canonical fixture blob is the publication input. Windows worktree
    # CRLF conversion must not change the evidence hash or the reader result.
    fixture_bytes = subprocess.check_output(
        ["git", "show", "HEAD:tests/fixtures/strategy_v1/offline_contract.json"],
        cwd=repo_root,
    )
    fixture = json.loads(fixture_bytes)
    if json.loads((repo_root / "tests/fixtures/strategy_v1/offline_contract.json").read_text(
        encoding="utf-8")) != fixture:
        raise ValueError("donchian_worktree_fixture_differs_from_commit")
    frame = build_closeout_scenario(
        start=datetime.fromisoformat(fixture["scenario"]["start_utc"])
    )
    offsets = fixture["scenario"]["checkpoint_offsets"]
    clock = datetime.fromisoformat(fixture["scenario"]["observation_time_utc"])

    def prefix(name: str):
        return frame.iloc[: int(offsets[name]) + 1].copy(deep=True)

    def new_runner() -> DonchianOfflineReplay:
        return DonchianOfflineReplay(DonchianOfflineReplayConfig(
            repo_root=repo_root, state_dir=state_dir, run_id="v3donchian01",
            decision_time_utc=clock, data_version="v1-closeout-continuous-ohlcv-v1"))

    def record(rows: list, runner: DonchianOfflineReplay, checkpoint: str, result: dict) -> None:
        rows.append((checkpoint, prefix(checkpoint).index[-1].isoformat(), result, runner))

    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    rows: list = []
    first = new_runner()
    opened = first.run_frame(prefix("open_long"))
    record(rows, first, "open_long", opened)
    duplicate = first.run_frame(prefix("open_long"))
    assert duplicate["evidence"]["decision_id"] == opened["evidence"]["decision_id"]
    assert duplicate["submit_count"] == duplicate["fill_count"] == 1
    first.close()

    second = new_runner()
    restored = second.run_frame(prefix("open_long"))
    assert restored["submit_count"] == restored["fill_count"] == 1
    assert restored["evidence"]["decision_id"] == opened["evidence"]["decision_id"]
    held = second.run_frame(prefix("hold_long"))
    record(rows, second, "hold_long", held)
    held_duplicate = second.run_frame(prefix("hold_long"))
    assert held_duplicate["submit_count"] == 1 and held_duplicate["fill_count"] == 1
    closed = second.run_frame(prefix("reverse_to_short"))
    record(rows, second, "reverse_to_short", closed)
    assert closed["phase"] == "reversal_close" and closed["position_contracts"] == "0.00"
    second.close()

    third = new_runner()
    reopened = third.run_frame(prefix("reverse_to_short"))
    record(rows, third, "reverse_to_short", reopened)
    reopened_duplicate = third.run_frame(prefix("reverse_to_short"))
    assert reopened_duplicate["submit_count"] == 3 and reopened_duplicate["fill_count"] == 3
    exited = third.run_frame(prefix("exit_short"))
    record(rows, third, "exit_short", exited)
    exited_duplicate = third.run_frame(prefix("exit_short"))
    assert exited_duplicate["submit_count"] == 4 and exited_duplicate["fill_count"] == 4
    third.close()

    final_runner = new_runner()
    final = final_runner.run_frame(prefix("exit_short"))
    assert final["submit_count"] == final["fill_count"] == 4
    assert final["decision_evidence_count"] == 5
    assert final["evidence"]["decision_id"] == exited["evidence"]["decision_id"]
    final_runner.close()

    summary = build_donchian_summary(runner=first, fixture=fixture,
                                     fixture_bytes=fixture_bytes, results=rows)
    envelope = seal_summary(summary)
    validate_donchian_summary(
        envelope,
        btc_strategy_registry.get("long_short_donchian_top5_okx_native").identity(),
        first.source_head, fixture_bytes)
    return envelope


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path,
                        help="new external directory for transient simulated runtime")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    state_dir = args.state_dir.resolve()
    if state_dir == repo_root or repo_root in state_dir.parents:
        parser.error("state_dir_must_be_outside_git")
    if state_dir.exists() and any(state_dir.iterdir()):
        parser.error("state_dir_must_be_new_or_empty")
    output = repo_root / ".agent/offline_evidence/donchian-v3-closeout-20260920.json"
    if output.exists():
        parser.error("sealed_output_already_exists")
    payload = build(repo_root, state_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                 indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.relative_to(repo_root)),
                      "summary_sha256": payload["sha256"],
                      "source_head": payload["summary"]["source_head"],
                      "counts": payload["summary"]["counts"]}, sort_keys=True))


if __name__ == "__main__":
    main()
