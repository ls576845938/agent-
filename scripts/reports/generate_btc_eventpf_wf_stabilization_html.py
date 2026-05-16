#!/usr/bin/env python3
"""Generate a static BTC Event-PF/WF stabilization report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_eventpf_wf import BTC_EVENTPF_WF_RUN_ID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_EVENTPF_WF_RUN_ID)
    parser.add_argument("--artifact-root", default="artifacts/btc_canonical")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = Path(args.output) if args.output else Path("reports") / f"quantstation_vnext_btc_eventpf_wf_stabilization_{args.run_id}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    bridge = _read(run_dir / "event_pf_bridge_report.json")
    wf = _read(run_dir / "walk_forward_fold_attribution.json")
    exit_ablation = _read(run_dir / "exit_surgery_ablation_report.json")
    side_ablation = _read(run_dir / "side_regime_ablation_report.json")
    orderflow = _read(run_dir / "orderflow_keepout_confirmation.json")
    v4 = _read(run_dir / "btc_perp_dual_trend_v4_eventpf_wf_results.json")
    promotion = _read(run_dir / "promotion_decision.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    tests = _read_optional(run_dir / "test_results.json")
    decision = v4.get("gate_status", "unknown")
    final_line = (
        "v4 passed internal gate; paper_review_pending may be created; live remains FROZEN."
        if decision == "candidate_passed_internal_gate"
        else "v4 failed internal gate; paper queue remains LOCKED; live remains FROZEN."
    )
    if not bridge.get("event_PF") == bridge.get("fill_level_PF"):
        final_line = "Evidence inconsistent; research invalid; paper queue remains LOCKED; live remains FROZEN."
    body = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Event-PF Bridge and Walk-Forward Stabilization Report</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#52616b; --line:#d7dee6; --bg:#f7f9fb; --panel:#ffffff; --bad:#9b1c1c; --ok:#126b45; --warn:#8a5a00; }}
    body {{ margin:0; font-family: Arial, Helvetica, sans-serif; color:var(--ink); background:var(--bg); line-height:1.45; }}
    header {{ padding:24px 28px; background:#152238; color:white; }}
    main {{ max-width:1180px; margin:0 auto; padding:22px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; margin:0 0 18px; }}
    h1 {{ margin:0 0 8px; font-size:26px; }}
    h2 {{ margin:0 0 12px; font-size:20px; }}
    h3 {{ margin:16px 0 8px; font-size:16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:10px; }}
    .metric {{ border:1px solid var(--line); border-radius:6px; padding:10px; background:#fbfcfd; }}
    .metric strong {{ display:block; font-size:13px; color:var(--muted); }}
    .metric span {{ display:block; font-size:20px; margin-top:4px; }}
    .bad {{ color:var(--bad); font-weight:700; }}
    .ok {{ color:var(--ok); font-weight:700; }}
    .warn {{ color:var(--warn); font-weight:700; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }}
    th, td {{ border:1px solid var(--line); padding:7px 8px; text-align:left; vertical-align:top; }}
    th {{ background:#edf2f7; }}
    code {{ background:#eef2f6; padding:1px 4px; border-radius:4px; }}
    ul {{ padding-left:20px; }}
    .small {{ color:var(--muted); font-size:13px; }}
    .paths li {{ overflow-wrap:anywhere; }}
  </style>
</head>
<body>
<header>
  <h1>QuantStation VNEXT - BTC Event-PF Bridge and Walk-Forward Stabilization Report</h1>
  <div>Run ID: {esc(run_dir.name)}</div>
</header>
<main>
  <section>
    <h2>Safety Status</h2>
    <div class="grid">
      <div class="metric"><strong>candidate_passed_internal_gate count</strong><span>{esc(safety.get("candidate_passed_internal_gate_count", 0))}</span></div>
      <div class="metric"><strong>PAPER QUEUE</strong><span class="{'warn' if safety.get('paper_queue_status') == 'LOCKED' else 'ok'}">{esc(safety.get("paper_queue_status", "LOCKED"))}</span></div>
      <div class="metric"><strong>LIVE</strong><span class="bad">{esc(safety.get("live_status", "FROZEN"))}</span></div>
      <div class="metric"><strong>Final Decision</strong><span>{esc(decision)}</span></div>
    </div>
  </section>

  <section>
    <h2>Executive Summary</h2>
    <p>{esc(final_line)}</p>
    <ul>
      <li>Engineering evidence remains canonical/event-ledger based.</li>
      <li>Ordinary trade PF is diagnostic only; gate uses <code>event_PF</code>.</li>
      <li>Paper queue stays locked unless canonical gate passes with evidence consistency.</li>
      <li>Live remains frozen and no real broker API or order path was used.</li>
    </ul>
  </section>

  <section>
    <h2>Event-PF Bridge</h2>
    <div class="grid">
      <div class="metric"><strong>ordinary PF</strong><span>{fmt(bridge.get("ordinary_PF"))}</span></div>
      <div class="metric"><strong>event PF</strong><span>{fmt(bridge.get("event_PF"))}</span></div>
      <div class="metric"><strong>trade-level PF</strong><span>{fmt(bridge.get("trade_level_PF"))}</span></div>
      <div class="metric"><strong>cashflow-level PF</strong><span>{fmt(bridge.get("cashflow_level_PF"))}</span></div>
    </div>
    <h3>Root Causes</h3>
    {ul(bridge.get("root_cause_summary", []))}
    <h3>Metric Contract</h3>
    <p>{esc(bridge.get("recommended_metric_contract", {}).get("promotion_gate_metric", "event_PF"))} is the only promotion PF source. Ordinary PF remains diagnostic-only.</p>
  </section>

  <section>
    <h2>Walk-Forward Fold Attribution</h2>
    <p>Pass rate: {fmt(wf.get("pass_rate"))}; failed folds: {esc(wf.get("failed_folds", []))}</p>
    {table(wf.get("folds", []), ["fold_id", "event_PF", "PF", "Sharpe", "MDD", "turnover", "trade_count", "passed", "fail_reasons", "signal_flip_exit_count", "long_trades_PF", "short_trades_PF", "top_loss_exit_reason"])}
    <h3>Fold Findings</h3>
    {ul(_flatten_answers(wf.get("answers", {})))}
  </section>

  <section>
    <h2>Exit Surgery Ablation</h2>
    {table(exit_ablation.get("rows", []), ["mode", "event_PF", "PF", "Sharpe", "MDD", "turnover", "walk_forward_pass_rate", "regime_pass_rate", "signal_flip_exit_count", "signal_flip_exit_pnl", "gate_status", "fail_reasons", "note"])}
    <p class="small">Adopted rules: {esc(exit_ablation.get("adopted_rules", []))}</p>
  </section>

  <section>
    <h2>Side / Regime Ablation</h2>
    {table(side_ablation.get("rows", []), ["mode", "event_PF", "PF", "Sharpe", "MDD", "turnover", "walk_forward_pass_rate", "regime_pass_rate", "long_event_PF", "short_event_PF", "gate_status", "fail_reasons", "note"])}
    <p class="small">Adopted rules: {esc(side_ablation.get("adopted_rules", []))}</p>
  </section>

  <section>
    <h2>Order-flow Decision</h2>
    <p><strong>{esc(orderflow.get("source_conclusion", "unknown"))}</strong>. v4 order-flow mode: <code>{esc(orderflow.get("v4_orderflow_mode", "diagnostic_only"))}</code>.</p>
    {ul(orderflow.get("reasons", []))}
  </section>

  <section>
    <h2>v4 Final Decision</h2>
    {table(v4.get("comparison", []), ["strategy", "PF", "event_PF", "Sharpe", "MDD", "annual_turnover", "WF_pass", "regime_pass", "cost_stress", "PBO", "DSR", "trade_count", "fill_count", "gate_status", "fail_reasons"])}
    <p><strong>Gate status:</strong> {esc(v4.get("gate_status", "unknown"))}; <strong>Fail reasons:</strong> {esc(v4.get("fail_reasons", []))}</p>
  </section>

  <section>
    <h2>Runtime Boundary Audit</h2>
    <ul>
      <li>Active research entrypoints: <code>scripts/research/run_btc_eventpf_wf_stabilization.py</code>, <code>scripts/research/build_btc_event_pf_bridge.py</code>, <code>scripts/research/build_btc_wf_fold_attribution.py</code>.</li>
      <li>Review-only runtime boundaries: canonical promotion and paper queue artifacts.</li>
      <li>Inactive in this sprint: broker adapters, paper runtime, live runtime.</li>
      <li>Safety conclusion: paper queue {esc(safety.get("paper_queue_status", "LOCKED"))}; live {esc(safety.get("live_status", "FROZEN"))}.</li>
    </ul>
  </section>

  <section>
    <h2>Tests</h2>
    <p><strong>Command:</strong> <code>{esc(tests.get("command", "N/A - not recorded"))}</code></p>
    <p><strong>Result:</strong> {esc(tests.get("result", "N/A"))}</p>
    <p><strong>Skipped full suite reason:</strong> {esc(tests.get("skipped_full_suite_reason", "N/A"))}</p>
  </section>

  <section>
    <h2>Artifacts</h2>
    <ul class="paths">
      {''.join(f'<li><code>{esc(str(path))}</code></li>' for path in sorted(run_dir.iterdir()))}
    </ul>
  </section>

  <section>
    <h2>Next Sprint Recommendation</h2>
    <p>If v4 does not clear event_PF and WF together, continue event-ledger attribution and do not enter paper. Keep live frozen until a paper-review candidate survives a stable paper period.</p>
  </section>
</main>
</body>
</html>
"""
    return body


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


def _flatten_answers(answers: Mapping[str, Any]) -> list[str]:
    out = []
    for key, value in answers.items():
        out.append(f"{key}: {value}")
    return out


if __name__ == "__main__":
    main()
