#!/usr/bin/env python3
"""Generate BTC Event-Return Attribution and Alpha Renewal HTML report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_eventreturn_alpha import BTC_EVENTRETURN_RUN_ID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTRETURN_RUN_ID)
    parser.add_argument("--artifact-root", default="artifacts/btc_canonical")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = Path(args.output) if args.output else Path("reports") / f"quantstation_vnext_btc_event_return_alpha_renewal_{args.run_id}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    event_return = _read(run_dir / "event_return_attribution.json")
    terminal = _read(run_dir / "terminal_exposure_audit.json")
    autopsy = _read(run_dir / "failed_fold_autopsy.json")
    decision = _read(run_dir / "alpha_renewal_decision.json")
    promotion = _read(run_dir / "promotion_decision.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    tests = _read_optional(run_dir / "test_results.json")
    previous = decision.get("previous_v1_v4_metrics", [])
    final_line = "perp_dual_trend archived; paper queue remains LOCKED; live remains FROZEN."
    if decision.get("decision") == "research_invalid":
        final_line = "Evidence inconsistent; research invalid; paper queue remains LOCKED; live remains FROZEN."
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Event-Return Attribution and Alpha Renewal Report</title>
  <style>
    :root {{ --bg:#f6f8fb; --panel:#fff; --ink:#17202a; --muted:#596775; --line:#d7dee8; --navy:#14233b; --bad:#9b1c1c; --warn:#8a5a00; --ok:#126b45; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Arial, Helvetica, sans-serif; line-height:1.5; }}
    header {{ background:var(--navy); color:#fff; padding:24px 28px; }}
    main {{ max-width:1180px; margin:0 auto; padding:22px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; margin-bottom:18px; }}
    h1 {{ margin:0 0 8px; font-size:26px; }}
    h2 {{ margin:0 0 12px; font-size:20px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:10px; }}
    .metric {{ border:1px solid var(--line); border-radius:6px; padding:10px; background:#fbfcfe; }}
    .metric strong {{ display:block; color:var(--muted); font-size:13px; }}
    .metric span {{ display:block; margin-top:4px; font-size:20px; font-weight:700; }}
    .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }} .ok {{ color:var(--ok); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }}
    th, td {{ border:1px solid var(--line); padding:7px 8px; text-align:left; vertical-align:top; }}
    th {{ background:#edf2f7; }}
    code {{ background:#eef2f7; border-radius:4px; padding:1px 4px; }}
    li {{ margin:4px 0; }}
    .paths li {{ overflow-wrap:anywhere; }}
  </style>
</head>
<body>
<header>
  <h1>QuantStation VNEXT - BTC Event-Return Attribution and Alpha Renewal Report</h1>
  <div>Run ID: {esc(run_dir.name)}</div>
</header>
<main>
  <section>
    <h2>Safety Status</h2>
    <div class="grid">
      <div class="metric"><strong>candidate_passed_internal_gate count</strong><span>{esc(safety.get("candidate_passed_internal_gate_count", 0))}</span></div>
      <div class="metric"><strong>PAPER QUEUE</strong><span class="warn">{esc(safety.get("paper_queue_status", "LOCKED"))}</span></div>
      <div class="metric"><strong>LIVE</strong><span class="bad">{esc(safety.get("live_status", "FROZEN"))}</span></div>
      <div class="metric"><strong>Alpha Renewal Decision</strong><span>{esc(decision.get("decision", "unknown"))}</span></div>
    </div>
  </section>

  <section>
    <h2>Executive Summary</h2>
    <p><strong>{esc(final_line)}</strong></p>
    <ul>
      <li>event_PF was not solved; it remains near {fmt(event_return.get("event_PF"))} from hourly ledger returns.</li>
      <li>perp_dual_trend is archived as research_failed.</li>
      <li>No v5 was generated because no stable, rule-fixable event-return pattern was found.</li>
      <li>Paper remains locked and live remains frozen.</li>
    </ul>
  </section>

  <section>
    <h2>Previous Sprint Recap</h2>
    {table(previous, ["strategy", "PF", "event_PF", "Sharpe", "MDD", "annual_turnover", "WF_pass", "regime_pass", "gate_status", "fail_reasons"])}
  </section>

  <section>
    <h2>Event-Return Attribution</h2>
    <div class="grid">
      <div class="metric"><strong>event_PF recomputed</strong><span>{fmt(event_return.get("event_PF"))}</span></div>
      <div class="metric"><strong>source event_PF</strong><span>{fmt(event_return.get("source_event_PF"))}</span></div>
      <div class="metric"><strong>positive events</strong><span>{esc(event_return.get("overall_distribution", {}).get("positive_event_count"))}</span></div>
      <div class="metric"><strong>negative events</strong><span>{esc(event_return.get("overall_distribution", {}).get("negative_event_count"))}</span></div>
    </div>
    <h3>Root Cause Summary</h3>
    {ul(event_return.get("event_return_root_cause_summary", []))}
    <h3>By Fold</h3>
    {table(event_return.get("by_fold", []), ["fold_id", "event_count", "event_PF", "signed_event_pnl", "positive_event_sum", "negative_event_sum"])}
    <h3>By Regime</h3>
    {table(event_return.get("by_regime", [])[:8], ["regime", "event_count", "event_PF", "signed_event_pnl"])}
    <h3>By Side</h3>
    {table(event_return.get("by_side", []), ["position_side", "event_count", "event_PF", "signed_event_pnl"])}
    <h3>Top Negative Events</h3>
    {table(event_return.get("top_50_negative_events", [])[:10], ["timestamp", "event_return", "signed_event_pnl", "position_side", "exposure", "regime", "fold_id", "holding_age_bucket"])}
  </section>

  <section>
    <h2>Terminal Exposure Audit</h2>
    {table(terminal.get("policies", []), ["policy", "net_pnl", "event_PF", "PF", "Sharpe", "MDD", "total_return", "terminal_position_value", "open_pnl_included", "liquidation_or_flatten_cost_estimate", "gate_eligible"])}
    <p>Recommended terminal policy: <code>{esc(terminal.get("recommended_terminal_policy", {}).get("policy", "N/A"))}</code></p>
  </section>

  <section>
    <h2>Failed Fold Autopsy</h2>
    {table(autopsy.get("failed_folds", []), ["fold_id", "start_date", "end_date", "event_PF", "total_return", "max_drawdown", "event_count", "negative_event_count", "whether_failure_is_rule_fixable", "recommended_action"])}
    <h3>Root Causes</h3>
    {ul(autopsy.get("root_cause_summary", []))}
  </section>

  <section>
    <h2>Alpha Renewal Decision</h2>
    <p>Decision: <strong>{esc(decision.get("decision"))}</strong></p>
    <p>v5 generated: <strong>{esc(decision.get("v5_generated"))}</strong></p>
    {ul(decision.get("reasons", []))}
  </section>

  <section>
    <h2>Optional v5 Result</h2>
    <p>No v5 config or result was generated. Block reason: {esc(decision.get("v5_generation_blocked_reason", "N/A"))}</p>
  </section>

  <section>
    <h2>Alpha Hypothesis Backlog</h2>
    {table(decision.get("alpha_hypothesis_backlog", []), ["hypothesis", "rationale", "expected_event_level_edge", "first_experiment_plan", "stop_condition"])}
  </section>

  <section>
    <h2>Tests</h2>
    <p><strong>Command:</strong> <code>{esc(tests.get("command", "N/A"))}</code></p>
    <p><strong>Result:</strong> <code>{esc(tests.get("result", "N/A"))}</code></p>
    <p><strong>Skipped full suite reason:</strong> {esc(tests.get("skipped_full_suite_reason", "N/A"))}</p>
  </section>

  <section>
    <h2>Artifacts</h2>
    <ul class="paths">
      {''.join(f'<li><code>{esc(str(path))}</code></li>' for path in sorted(run_dir.iterdir()))}
    </ul>
  </section>

  <section>
    <h2>Final Decision</h2>
    <p><strong>{esc(final_line)}</strong></p>
  </section>
</main>
</body>
</html>"""
    return html_doc


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read(path)


def esc(value: Any) -> str:
    return html.escape(str(value))


def fmt(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return esc(value)


def ul(values: Sequence[Any]) -> str:
    if not values:
        return "<p>N/A</p>"
    return "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in values) + "</ul>"


def table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "<p>N/A</p>"
    head = "".join(f"<th>{esc(col)}</th>" for col in columns)
    body = []
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, Mapping):
                value = json.dumps(value, sort_keys=True)
            cells.append(f"<td>{esc(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


if __name__ == "__main__":
    main()
