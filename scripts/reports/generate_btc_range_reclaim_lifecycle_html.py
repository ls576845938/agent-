#!/usr/bin/env python3
"""Generate BTC range-reclaim lifecycle-aware HTML report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_range_reclaim_lifecycle import BTC_RANGE_RECLAIM_OUTPUT_ROOT, BTC_RANGE_RECLAIM_RUN_ID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_RANGE_RECLAIM_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_RANGE_RECLAIM_OUTPUT_ROOT))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = (
        Path(args.output)
        if args.output
        else Path("reports") / f"quantstation_vnext_btc_range_reclaim_lifecycle_report_{args.run_id}.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    registry = _read(Path("artifacts/btc_research_registry/research_registry.json"))
    report = _read(run_dir / "range_reclaim_lifecycle_report.json")
    decision = _read(run_dir / "range_reclaim_hypothesis_decision_v2.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    tests = _read_optional(run_dir / "test_results.json")
    final_line = str(decision.get("final_decision", "hypothesis rejected; no strategy generated; paper queue remains LOCKED; live remains FROZEN."))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Range-Reclaim Momentum Lifecycle Research Report</title>
  <style>
    :root {{ --bg:#f5f7fa; --panel:#fff; --ink:#17202a; --muted:#596775; --line:#d7dee8; --navy:#152238; --bad:#9b1c1c; --warn:#8a5a00; --ok:#126b45; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Arial, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; line-height:1.55; }}
    header {{ background:var(--navy); color:#fff; padding:24px 18px; }}
    main {{ max-width:1160px; margin:0 auto; padding:16px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:14px; }}
    h1 {{ margin:0 0 8px; font-size:22px; line-height:1.25; }}
    h2 {{ margin:0 0 12px; font-size:18px; }}
    h3 {{ margin:14px 0 8px; font-size:15px; }}
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
  <h1>QuantStation VNEXT - BTC Range-Reclaim Momentum Lifecycle Research Report</h1>
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
      <li>本轮没有复活 <code>perp_dual_trend</code> 或 <code>liquidation_shock_recovery</code>。</li>
      <li>新 hypothesis 为 <code>{esc(report.get("hypothesis_id"))}</code>，仅做 lifecycle-aware research gate。</li>
      <li>Skeleton 只有在 full-lifecycle event_PF、lifecycle WF、cost proxy、tail dependency 同时通过时才允许生成。</li>
    </ul>
  </section>

  <section>
    <h2>3. Registry Summary</h2>
    {table(_registry_rows(registry), ["alpha", "status", "last_run_id", "reason", "next_action"])}
  </section>

  <section>
    <h2>4. Lifecycle-Aware Result</h2>
    <div class="grid">
      <div class="metric"><strong>raw_event_PF_proxy</strong><span>{fmt(report.get("raw_event_PF_proxy"))}</span></div>
      <div class="metric"><strong>target_active_event_PF_proxy</strong><span>{fmt(report.get("target_active_event_PF_proxy"))}</span></div>
      <div class="metric"><strong>full_lifecycle_event_PF_proxy</strong><span>{fmt(report.get("full_lifecycle_event_PF_proxy"))}</span></div>
      <div class="metric"><strong>lifecycle_drag</strong><span>{fmt(report.get("lifecycle_drag"))}</span></div>
      <div class="metric"><strong>lifecycle_drag_pct</strong><span>{fmt(report.get("lifecycle_drag_pct"))}</span></div>
      <div class="metric"><strong>fold_pass_rate_lifecycle</strong><span>{fmt(report.get("fold_pass_rate_lifecycle"))}</span></div>
      <div class="metric"><strong>top5_positive_contribution</strong><span>{fmt(report.get("top5_positive_contribution"))}</span></div>
      <div class="metric"><strong>cost_stress_proxy_base</strong><span>{esc(report.get("cost_stress_proxy_base", {}).get("passed"))}</span></div>
    </div>
    <h3>Root Cause Summary</h3>
    <ul>{''.join(f'<li>{esc(item)}</li>' for item in report.get("root_cause_summary", []))}</ul>
  </section>

  <section>
    <h2>5. Fold Stability</h2>
    {table(report.get("fold_stability_lifecycle", {}).get("folds", []), ["fold_id", "passed", "event_PF_proxy", "active_event_count", "median_return", "downside_tail_5pct"])}
  </section>

  <section>
    <h2>6. Horizon Analysis</h2>
    {table(_horizon_rows(report), ["horizon", "active_event_count", "event_PF_proxy", "median_return", "positive_event_rate", "downside_tail_5pct"])}
  </section>

  <section>
    <h2>7. Tail Dependency</h2>
    <div class="grid">
      <div class="metric"><strong>top5_positive_contribution</strong><span>{fmt(report.get("tail_dependency", {}).get("top5_positive_contribution"))}</span></div>
      <div class="metric"><strong>top10_positive_contribution</strong><span>{fmt(report.get("tail_dependency", {}).get("top10_positive_contribution"))}</span></div>
      <div class="metric"><strong>top5_negative_contribution</strong><span>{fmt(report.get("tail_dependency", {}).get("top5_negative_contribution"))}</span></div>
      <div class="metric"><strong>edge_depends_on_extreme_events</strong><span>{esc(report.get("tail_dependency", {}).get("edge_depends_on_extreme_events"))}</span></div>
    </div>
  </section>

  <section>
    <h2>8. Skeleton Guard</h2>
    <p>Skeleton generated: <strong>{esc(decision.get("strategy_skeleton_generated"))}</strong></p>
    <p>Skeleton guard decision: <code>{esc(decision.get("skeleton_guard_decision"))}</code></p>
    <p>Reasons: <code>{esc(", ".join(decision.get("reasons", [])))}</code></p>
    <p>Skeleton reasons: <code>{esc(", ".join(decision.get("skeleton_reasons", [])))}</code></p>
  </section>

  <section>
    <h2>9. Tests</h2>
    {_tests(tests)}
  </section>

  <section>
    <h2>10. Final Decision</h2>
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


def _horizon_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, value in report.get("horizon_analysis", {}).items():
        row = {"horizon": key}
        row.update(dict(value))
        rows.append(row)
    return rows


def _tests(payload: Mapping[str, Any]) -> str:
    commands = payload.get("commands", [])
    return table(commands, ["command", "result"]) if commands else "<p>Tests not recorded yet.</p>"


if __name__ == "__main__":
    main()
