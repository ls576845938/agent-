#!/usr/bin/env python3
"""Generate BTC Hypothesis Lab v2 lifecycle-aware HTML report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_hypothesis_lab_v2 import BTC_HYPOTHESIS_LAB_V2_ROOT, BTC_HYPOTHESIS_LAB_V2_RUN_ID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_HYPOTHESIS_LAB_V2_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_HYPOTHESIS_LAB_V2_ROOT))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = (
        Path(args.output)
        if args.output
        else Path("reports") / f"quantstation_vnext_btc_hypothesis_lab_v2_lifecycle_report_{args.run_id}.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    registry = _read(Path("artifacts/btc_research_registry/research_registry.json"))
    lifecycle = _read(run_dir / "lifecycle_aware_distribution_report.json")
    decision = _read(run_dir / "hypothesis_decision_v2.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    tests = _read_optional(run_dir / "test_results.json")
    final_line = str(decision.get("final_decision", "registry/lifecycle audit completed; paper queue remains LOCKED; live remains FROZEN."))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Hypothesis Lab v2 Lifecycle-Aware Research Report</title>
  <style>
    :root {{ --bg:#f6f8fb; --panel:#fff; --ink:#17202a; --muted:#596775; --line:#d7dee8; --navy:#14233b; --bad:#9b1c1c; --warn:#8a5a00; --ok:#126b45; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Arial, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; line-height:1.55; }}
    header {{ background:var(--navy); color:#fff; padding:24px 20px; }}
    main {{ max-width:1180px; margin:0 auto; padding:16px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:14px; }}
    h1 {{ margin:0 0 8px; font-size:23px; line-height:1.25; }}
    h2 {{ margin:0 0 12px; font-size:19px; }}
    h3 {{ margin:14px 0 8px; font-size:16px; }}
    .meta {{ color:#d8e2ef; font-size:14px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:10px; }}
    .metric {{ border:1px solid var(--line); border-radius:6px; padding:10px; background:#fbfcfe; min-height:74px; }}
    .metric strong {{ display:block; color:var(--muted); font-size:13px; }}
    .metric span {{ display:block; margin-top:5px; font-size:18px; font-weight:700; overflow-wrap:anywhere; }}
    .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }} .ok {{ color:var(--ok); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; display:block; overflow-x:auto; white-space:nowrap; margin-top:8px; }}
    th, td {{ border:1px solid var(--line); padding:7px 8px; text-align:left; vertical-align:top; }}
    th {{ background:#edf2f7; }}
    code {{ background:#eef2f7; border-radius:4px; padding:1px 4px; overflow-wrap:anywhere; }}
    li {{ margin:5px 0; }}
    .decision {{ border-left:4px solid var(--bad); background:#fff8f8; padding:10px 12px; border-radius:6px; }}
  </style>
</head>
<body>
<header>
  <h1>QuantStation VNEXT - BTC Hypothesis Lab v2 Lifecycle-Aware Research Report</h1>
  <div class="meta">Run ID: {esc(run_dir.name)}</div>
</header>
<main>
  <section>
    <h2>1. Safety Status</h2>
    <div class="grid">
      <div class="metric"><strong>PAPER QUEUE</strong><span class="warn">{esc(safety.get("paper_queue", "LOCKED"))}</span></div>
      <div class="metric"><strong>LIVE</strong><span class="bad">{esc(safety.get("live", "FROZEN"))}</span></div>
      <div class="metric"><strong>candidate_passed_internal_gate</strong><span>{esc(safety.get("candidate_passed_internal_gate", 0))}</span></div>
      <div class="metric"><strong>Decision</strong><span class="bad">{esc(decision.get("decision"))}</span></div>
    </div>
  </section>

  <section>
    <h2>2. Executive Summary</h2>
    <div class="decision"><strong>{esc(final_line)}</strong></div>
    <ul>
      <li>本轮完成 registry 和 Hypothesis Lab v2 lifecycle-aware gate。</li>
      <li>compression-expansion 旧 hypothesis 层曾通过，但 lifecycle-aware gate 拒绝。</li>
      <li>没有生成新的 strategy skeleton；paper/live 继续锁定。</li>
    </ul>
  </section>

  <section>
    <h2>3. Registry Summary</h2>
    {table(_registry_rows(registry), ["alpha", "status", "last_run_id", "reason", "next_action"])}
  </section>

  <section>
    <h2>4. Why v2</h2>
    <ul>
      <li>target-active edge can be misleading.</li>
      <li>full-lifecycle event_PF is required.</li>
      <li>liquidation-shock lesson: target-active event_PF was above threshold, but full-ledger event_PF was below 1.</li>
      <li>raw event-return, target-active, full-lifecycle, lifecycle drag, cost proxy, fold stability, and tail dependency must all be visible before skeleton decisions.</li>
    </ul>
  </section>

  <section>
    <h2>5. Hypothesis Lab v2 Contract</h2>
    <div class="grid">
      <div class="metric"><strong>raw event-return</strong><span>required</span></div>
      <div class="metric"><strong>target-active</strong><span>required</span></div>
      <div class="metric"><strong>full-lifecycle</strong><span>required</span></div>
      <div class="metric"><strong>lifecycle_drag</strong><span>required</span></div>
      <div class="metric"><strong>cost stress proxy</strong><span>required</span></div>
      <div class="metric"><strong>fold stability</strong><span>required</span></div>
    </div>
  </section>

  <section>
    <h2>6. Compression-to-Expansion Result</h2>
    <div class="grid">
      <div class="metric"><strong>raw_event_PF_proxy</strong><span class="ok">{fmt(lifecycle.get("raw_event_PF_proxy"))}</span></div>
      <div class="metric"><strong>target_active_event_PF_proxy</strong><span class="ok">{fmt(lifecycle.get("target_active_event_PF_proxy"))}</span></div>
      <div class="metric"><strong>full_lifecycle_event_PF_proxy</strong><span class="bad">{fmt(lifecycle.get("full_lifecycle_event_PF_proxy"))}</span></div>
      <div class="metric"><strong>lifecycle_drag</strong><span>{fmt(lifecycle.get("lifecycle_drag"))}</span></div>
      <div class="metric"><strong>lifecycle_drag_pct</strong><span>{fmt(lifecycle.get("lifecycle_drag_pct"))}</span></div>
      <div class="metric"><strong>fold_pass_rate_lifecycle</strong><span class="bad">{fmt(lifecycle.get("fold_pass_rate_lifecycle"))}</span></div>
      <div class="metric"><strong>top5_positive_contribution</strong><span>{fmt(lifecycle.get("top5_positive_contribution"))}</span></div>
      <div class="metric"><strong>cost_stress_proxy_base</strong><span class="ok">{esc(lifecycle.get("cost_stress_proxy_base", {}).get("passed"))}</span></div>
    </div>
    <h3>Lifecycle Folds</h3>
    {table(lifecycle.get("fold_stability_lifecycle", {}).get("folds", []), ["fold_id", "passed", "event_PF_proxy", "total_return_pct", "MDD", "trade_count"])}
  </section>

  <section>
    <h2>7. Skeleton Guard</h2>
    <p>Skeleton generated: <strong>{esc(decision.get("strategy_skeleton_generated"))}</strong></p>
    <p>Skeleton guard decision: <code>{esc(decision.get("skeleton_guard_decision"))}</code></p>
    <p>Reasons: <code>{esc(", ".join(decision.get("reasons", [])))}</code></p>
    <p>Skeleton reasons: <code>{esc(", ".join(decision.get("skeleton_reasons", [])))}</code></p>
  </section>

  <section>
    <h2>8. Tests</h2>
    {_tests(tests)}
  </section>

  <section>
    <h2>9. Final Decision</h2>
    <div class="decision"><strong>{esc(final_line)}</strong></div>
  </section>
</main>
</body>
</html>"""


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional(path: Path) -> dict[str, Any]:
    return _read(path) if path.exists() else {}


def esc(value: Any) -> str:
    return html.escape(str(value))


def fmt(value: Any) -> str:
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return esc(value)


def table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "<p>N/A</p>"
    head = "".join(f"<th>{esc(col)}</th>" for col in columns)
    body = []
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            cells.append(f"<td>{esc(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _registry_rows(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, value in registry.get("items", {}).items():
        row = {"alpha": key}
        row.update(dict(value))
        rows.append(row)
    return sorted(rows, key=lambda row: row["alpha"])


def _tests(payload: Mapping[str, Any]) -> str:
    commands = payload.get("commands", [])
    return table(commands, ["command", "result"]) if commands else "<p>Tests not recorded yet.</p>"


if __name__ == "__main__":
    main()
