#!/usr/bin/env python3
"""Generate BTC liquidation-shock attribution and skeleton-decision HTML."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_liquidation_shock_attribution import (
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT,
    BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_ATTRIBUTION_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_LIQUIDATION_SHOCK_ATTRIBUTION_ROOT))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = (
        Path(args.output)
        if args.output
        else Path("reports") / f"quantstation_vnext_btc_liquidation_shock_eventreturn_attribution_{args.run_id}.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    attribution = _read(run_dir / "liquidation_shock_event_return_attribution.json")
    fold3 = _read(run_dir / "liquidation_shock_fold3_autopsy.json")
    chop = _read(run_dir / "liquidation_shock_mean_reverting_chop_report.json")
    lifecycle = _read(run_dir / "liquidation_shock_exit_lifecycle_ablation.json")
    confirmation = _read(run_dir / "liquidation_shock_recovery_confirmation_report.json")
    decision = _read(run_dir / "liquidation_shock_skeleton_decision.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    tests = _read_optional(run_dir / "test_results.json")
    previous = _read(Path("artifacts/btc_candidate_validation/20260516T234000Z_liquidation_shock_eventledger/canonical_backtest_report.json"))
    final_line = str(decision.get("final_decision", "liquidation-shock recovery archived; paper queue remains LOCKED; live remains FROZEN."))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Liquidation-Shock Event-Return Attribution and Skeleton Decision Report</title>
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
    .paths li {{ overflow-wrap:anywhere; }}
  </style>
</head>
<body>
<header>
  <h1>QuantStation VNEXT - BTC Liquidation-Shock Event-Return Attribution and Skeleton Decision Report</h1>
  <div class="meta">Run ID: {esc(run_dir.name)} | Source: 20260516T234000Z_liquidation_shock_eventledger</div>
</header>
<main>
  <section>
    <h2>1. Safety Status</h2>
    <div class="grid">
      <div class="metric"><strong>PAPER QUEUE</strong><span class="warn">{esc(safety.get("paper_queue", "LOCKED"))}</span></div>
      <div class="metric"><strong>LIVE</strong><span class="bad">{esc(safety.get("live", "FROZEN"))}</span></div>
      <div class="metric"><strong>candidate_passed_internal_gate</strong><span>{esc(safety.get("candidate_passed_internal_gate", 0))}</span></div>
      <div class="metric"><strong>Skeleton Decision</strong><span class="bad">{esc(decision.get("decision"))}</span></div>
    </div>
  </section>

  <section>
    <h2>2. Executive Summary</h2>
    <div class="decision"><strong>{esc(final_line)}</strong></div>
    <ul>
      <li>v1 event-ledger gate failed; this sprint did attribution instead of parameter chasing.</li>
      <li>No v2 config was generated because no ablation simultaneously improved event_PF, fold stability, and cost stress enough.</li>
      <li>Ordinary PF remains diagnostic-only; full ledger event_PF remains the gate metric.</li>
      <li>Paper queue remains locked and live remains frozen.</li>
    </ul>
  </section>

  <section>
    <h2>3. Previous Sprint Recap</h2>
    <div class="grid">
      <div class="metric"><strong>PF</strong><span>{fmt(previous["metrics"].get("profit_factor"))}</span></div>
      <div class="metric"><strong>event_PF</strong><span class="bad">{fmt(previous["metrics"].get("event_profit_factor"))}</span></div>
      <div class="metric"><strong>WF Pass</strong><span class="bad">{fmt(previous["metrics"].get("walk_forward_pass_rate"))}</span></div>
      <div class="metric"><strong>Regime Pass</strong><span class="ok">{fmt(previous["metrics"].get("regime_pass_rate"))}</span></div>
      <div class="metric"><strong>Cost Base</strong><span class="bad">{esc(previous["metrics"].get("cost_stress_base_pass"))}</span></div>
      <div class="metric"><strong>DSR</strong><span class="bad">{fmt(previous["metrics"].get("dsr"))}</span></div>
    </div>
    <p>Fail reasons: <code>{esc(", ".join(previous.get("fail_reasons", [])))}</code></p>
  </section>

  <section>
    <h2>4. Event-Return Attribution</h2>
    <div class="grid">
      <div class="metric"><strong>Full Ledger event_PF</strong><span class="bad">{fmt(attribution.get("event_PF_recomputed"))}</span></div>
      <div class="metric"><strong>Target-Active event_PF</strong><span>{fmt(attribution["active_exposure_event_distribution"].get("event_PF"))}</span></div>
      <div class="metric"><strong>Flat/Lifecycle event_PF</strong><span class="bad">{fmt(attribution["inactive_event_distribution"].get("event_PF"))}</span></div>
      <div class="metric"><strong>Active Event Count</strong><span>{esc(attribution["active_exposure_event_distribution"].get("event_count"))}</span></div>
    </div>
    <h3>Root Cause</h3>
    <ul>{''.join(f'<li>{esc(item)}</li>' for item in attribution.get("event_return_root_cause_summary", []))}</ul>
    <h3>By Fold</h3>
    {table(attribution.get("by_fold", []), ["fold_id", "event_count", "event_PF", "positive_sum", "negative_sum", "signed_pnl_sum"])}
    <h3>By Regime</h3>
    {table(attribution.get("by_regime", []), ["regime", "event_count", "event_PF", "positive_sum", "negative_sum", "signed_pnl_sum"])}
    <h3>By Recovery Age</h3>
    {table(attribution.get("by_recovery_age_bars_bucket", []), ["recovery_age_bucket", "event_count", "event_PF", "signed_pnl_sum"])}
    <h3>By Time-To-Exit</h3>
    {table(attribution.get("by_time_to_exit_bars_bucket", []), ["time_to_exit_bucket", "event_count", "event_PF", "signed_pnl_sum"])}
  </section>

  <section>
    <h2>5. Fold 3 Autopsy</h2>
    <div class="grid">
      <div class="metric"><strong>Fold 3 event_PF</strong><span class="bad">{fmt(fold3.get("event_PF"))}</span></div>
      <div class="metric"><strong>Total Return</strong><span class="bad">{fmt(fold3.get("total_return"))}</span></div>
      <div class="metric"><strong>Worst Regime</strong><span>{esc(fold3.get("worst_regime"))}</span></div>
      <div class="metric"><strong>Fixable?</strong><span class="bad">{esc(fold3.get("whether_failure_is_fixable"))}</span></div>
    </div>
    <ul>{''.join(f'<li>{esc(item)}</li>' for item in fold3.get("root_cause", []))}</ul>
  </section>

  <section>
    <h2>6. Mean-Reverting-Chop Failure</h2>
    <p>Trade-level mean_reverting_chop was a failure in the previous sprint, but bar-level active attribution does not support it as a standalone v2 rule.</p>
    <div class="grid">
      <div class="metric"><strong>Bar-Level event_PF</strong><span>{fmt(chop.get("mean_reverting_chop_event_PF"))}</span></div>
      <div class="metric"><strong>Keep-Out Suitable</strong><span class="bad">{esc(chop.get("keepout_assessment", {}).get("suitable_for_keepout"))}</span></div>
      <div class="metric"><strong>Sample-In Only Fix</strong><span class="bad">{esc(chop.get("keepout_assessment", {}).get("sample_in_only_fix"))}</span></div>
    </div>
    {table(chop.get("ablation_results", []), ["variant", "event_PF", "PF", "WF_pass", "regime_pass", "cost_stress_base_pass", "cost_stress_harsh_survives", "trade_count", "fail_reasons"])}
  </section>

  <section>
    <h2>7. Time Exit / Exposure Lifecycle</h2>
    <p>Best diagnostic variant by event_PF: <code>{esc(lifecycle.get("best_by_event_PF", {}).get("variant"))}</code>. It still failed hard event_PF and/or WF gate, so it was not promoted into v2.</p>
    {table(lifecycle.get("ablation_results", []), ["variant", "event_PF", "PF", "Sharpe", "MDD", "WF_pass", "regime_pass", "cost_stress_base_pass", "cost_stress_harsh_survives", "trade_count", "avg_holding_bars", "fail_reasons"])}
  </section>

  <section>
    <h2>8. Recovery Confirmation</h2>
    <p>Second confirmation required/adoptable: <strong>{esc(confirmation.get("needs_second_confirmation"))}</strong>. Best confirmation was diagnostic only and did not clear event_PF gate.</p>
    {table(confirmation.get("confirmation_results", []), ["variant", "event_PF", "PF", "WF_pass", "regime_pass", "cost_stress_base_pass", "cost_stress_harsh_survives", "trade_count", "fail_reasons"])}
  </section>

  <section>
    <h2>9. Skeleton Decision</h2>
    <div class="decision"><strong>{esc(decision.get("decision"))}</strong></div>
    <ul>{''.join(f'<li>{esc(reason)}</li>' for reason in decision.get("reasons", []))}</ul>
    <p>v2 generated: <strong>{esc(decision.get("v2_generated"))}</strong></p>
  </section>

  <section>
    <h2>10. Tests</h2>
    {_tests(tests)}
  </section>

  <section>
    <h2>11. Artifacts</h2>
    <ul class="paths">
      {''.join(f'<li><code>{esc(str(path))}</code></li>' for path in sorted(run_dir.iterdir()) if path.is_file())}
      <li><code>docs/research/BTC_LIQUIDATION_SHOCK_SKELETON_DECISION.md</code></li>
    </ul>
  </section>

  <section>
    <h2>12. Final Decision</h2>
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


def _tests(payload: Mapping[str, Any]) -> str:
    commands = payload.get("commands", [])
    if commands:
        return table(commands, ["command", "result"])
    return "<p>Tests not recorded yet.</p>"


if __name__ == "__main__":
    main()
