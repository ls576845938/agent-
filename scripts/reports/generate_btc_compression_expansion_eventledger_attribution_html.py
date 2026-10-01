#!/usr/bin/env python3
"""Generate static HTML report for BTC compression-expansion event-ledger attribution."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_compression_expansion_diagnostics import (
    BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT,
    BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID)
    parser.add_argument("--artifact-root", default=str(BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = (
        Path(args.output)
        if args.output
        else Path("reports") / f"quantstation_vnext_btc_compression_expansion_eventledger_attribution_{args.run_id}.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    canonical = _read(run_dir / "canonical_backtest_report.json")
    candidate = _read(run_dir / "candidate_validation_result.json")
    attribution = _read(run_dir / "event_ledger_attribution_report.json")
    failure = _read(run_dir / "compression_expansion_failure_mode_report.json")
    fold_regime = _read(run_dir / "fold_regime_contract_audit.json")
    data_status = _read(run_dir / "btc_data_fold_regime_status_report.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    tests = _read_optional(run_dir / "test_results.json")
    final_line = "compression-expansion failed event-ledger gate; paper queue remains LOCKED; live remains FROZEN."
    metrics = canonical["metrics"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Compression-Expansion Event-Ledger Attribution Report</title>
  <style>
    :root {{ --bg:#f5f7fa; --panel:#ffffff; --ink:#17202a; --muted:#5b6775; --line:#d8e0ea; --nav:#16253f; --bad:#a12622; --warn:#8b5a00; --ok:#146c43; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Arial, Helvetica, sans-serif; line-height:1.48; }}
    header {{ background:var(--nav); color:#fff; padding:24px 28px; }}
    main {{ max-width:1220px; margin:0 auto; padding:20px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:17px; margin-bottom:16px; }}
    h1 {{ margin:0 0 8px; font-size:25px; }}
    h2 {{ margin:0 0 12px; font-size:19px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; }}
    .metric {{ background:#fbfcfe; border:1px solid var(--line); border-radius:6px; padding:10px; }}
    .metric strong {{ display:block; color:var(--muted); font-size:12px; }}
    .metric span {{ display:block; margin-top:3px; font-size:19px; font-weight:700; }}
    .bad {{ color:var(--bad); }} .warn {{ color:var(--warn); }} .ok {{ color:var(--ok); }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }}
    th,td {{ border:1px solid var(--line); padding:7px 8px; text-align:left; vertical-align:top; }}
    th {{ background:#edf2f7; }}
    code {{ background:#eef2f7; border-radius:4px; padding:1px 4px; }}
    ul {{ margin-top:6px; }}
    li {{ margin:4px 0; }}
  </style>
</head>
<body>
<header>
  <h1>QuantStation VNEXT - BTC Compression-Expansion Event-Ledger Attribution Report</h1>
  <div>Run ID: {esc(run_dir.name)}</div>
</header>
<main>
  <section>
    <h2>Safety Status</h2>
    <div class="grid">
      <div class="metric"><strong>PAPER QUEUE</strong><span class="warn">{esc(safety.get("paper_queue", "LOCKED"))}</span></div>
      <div class="metric"><strong>LIVE</strong><span class="bad">{esc(safety.get("live", "FROZEN"))}</span></div>
      <div class="metric"><strong>candidate_passed_internal_gate</strong><span>{esc(safety.get("candidate_passed_internal_gate", 0))}</span></div>
      <div class="metric"><strong>Gate Status</strong><span class="bad">{esc(candidate.get("status"))}</span></div>
    </div>
  </section>

  <section>
    <h2>Executive Summary</h2>
    <p><strong>{esc(final_line)}</strong></p>
    <ul>
      <li>Hypothesis layer passed, but canonical event-ledger candidate validation failed.</li>
      <li>ordinary PF is diagnostic; promotion still uses event_PF, WF, and regime gates.</li>
      <li>No parameter tuning, no paper review pending, no live state change.</li>
    </ul>
  </section>

  <section>
    <h2>Canonical Candidate Metrics</h2>
    <div class="grid">
      <div class="metric"><strong>ordinary PF</strong><span>{fmt(metrics.get("profit_factor"))}</span></div>
      <div class="metric"><strong>event_PF</strong><span class="bad">{fmt(metrics.get("event_profit_factor"))}</span></div>
      <div class="metric"><strong>Sharpe</strong><span>{fmt(metrics.get("sharpe"))}</span></div>
      <div class="metric"><strong>MDD %</strong><span>{fmt(metrics.get("max_drawdown"))}</span></div>
      <div class="metric"><strong>Annual Turnover</strong><span>{fmt(metrics.get("annual_turnover"))}</span></div>
      <div class="metric"><strong>WF Pass</strong><span class="bad">{fmt(metrics.get("walk_forward_pass_rate"))}</span></div>
      <div class="metric"><strong>Regime Pass</strong><span class="bad">{fmt(metrics.get("regime_pass_rate"))}</span></div>
      <div class="metric"><strong>Fail Reasons</strong><span>{esc(", ".join(candidate.get("gate_fail_reasons", [])))}</span></div>
    </div>
  </section>

  <section>
    <h2>Full Ledger vs Active Exposure</h2>
    {table([
        {"scope": "full_ledger", **failure["full_vs_active_exposure"]["full_ledger"]},
        {"scope": "active_exposure", **failure["full_vs_active_exposure"]["active_exposure"]},
        {"scope": "inactive_or_unmapped", **failure["full_vs_active_exposure"]["inactive_or_unmapped"]},
    ], ["scope", "event_count", "event_pf", "positive_sum", "negative_sum", "positive_event_rate", "mean_return", "median_return"])}
    <p>{esc(failure["full_vs_active_exposure"]["diagnostic_note"])}</p>
  </section>

  <section>
    <h2>Failed Fold 3/4 Autopsy</h2>
    {table(_fold_rows(failure.get("failed_fold_autopsy", [])), ["fold_id", "full_event_pf", "active_event_pf", "inactive_event_pf", "worst_regimes", "worst_age_buckets"])}
  </section>

  <section>
    <h2>Regime Drag</h2>
    <p>Gate dragging regimes: <code>{esc(", ".join(failure["regime_drag"].get("gate_dragging_regimes", [])))}</code></p>
    {table(failure["regime_drag"].get("active_bar_level_regime_stats", []), ["regime", "event_count", "event_pf", "positive_sum", "negative_sum", "median_return"])}
  </section>

  <section>
    <h2>Entry / Exit Timing Diagnostics</h2>
    <p>{esc(failure["entry_exit_timing"].get("timing_note", ""))}</p>
    <h3>Worst entry hours</h3>
    {table(failure["entry_exit_timing"].get("by_entry_hour", [])[:8], ["entry_hour_utc", "trade_count", "net_pnl", "profit_factor", "win_rate"])}
    <h3>Holding bars</h3>
    {table(failure["entry_exit_timing"].get("by_holding_bars", []), ["holding_bars", "trade_count", "net_pnl", "profit_factor", "win_rate"])}
  </section>

  <section>
    <h2>Fold / Regime Contract Audit</h2>
    <div class="grid">
      <div class="metric"><strong>Fold Contract</strong><span>{esc(fold_regime["fold_contract"].get("status"))}</span></div>
      <div class="metric"><strong>Regime Contract</strong><span class="bad">{esc(fold_regime["regime_contract"].get("status"))}</span></div>
      <div class="metric"><strong>Label Trimmed Rows</strong><span>{esc(fold_regime["fold_contract"].get("label_trimmed_rows_due_to_forward_horizon"))}</span></div>
      <div class="metric"><strong>Paper Review Rule</strong><span>{esc(fold_regime["promotion_contract"].get("paper_review_pending_requires_all_three"))}</span></div>
    </div>
    {table(fold_regime["fold_contract"].get("folds", []), ["fold_id", "validation_start", "validation_end", "validation_rows", "passed"])}
  </section>

  <section>
    <h2>BTC Data / Fold / Regime Status</h2>
    <div class="grid">
      <div class="metric"><strong>SQLite</strong><span class="ok">{esc(data_status["sqlite"].get("status"))}</span></div>
      <div class="metric"><strong>Manifest Lineage</strong><span class="ok">{esc(data_status["manifest_lineage"].get("status"))}</span></div>
      <div class="metric"><strong>Regime Status</strong><span class="bad">{esc(data_status["regime_status"].get("status"))}</span></div>
    </div>
    {table(data_status.get("intervals", []), ["interval", "status", "row_count", "expected_rows", "missing_rows", "manifest_status", "data_version"])}
  </section>

  <section>
    <h2>Repairability Decision</h2>
    <p>Conclusion: <strong>{esc(failure["repairability_assessment"].get("conclusion"))}</strong></p>
    {table([failure["repairability_assessment"]], ["fold_3_4_have_single_shared_failure_pattern", "shared_worst_regimes_across_failed_folds", "do_not_parameter_tune_to_pass", "recommended_next_step"])}
  </section>

  <section>
    <h2>Artifacts</h2>
    <ul>
      <li><code>{esc(run_dir / "compression_expansion_failure_mode_report.json")}</code></li>
      <li><code>{esc(run_dir / "fold_regime_contract_audit.json")}</code></li>
      <li><code>{esc(run_dir / "btc_data_fold_regime_status_report.json")}</code></li>
      <li><code>{esc(run_dir / "event_ledger_attribution_report.json")}</code></li>
    </ul>
  </section>

  <section>
    <h2>Tests</h2>
    {_tests(tests)}
  </section>

  <section>
    <h2>Final Decision</h2>
    <p><strong>{esc(final_line)}</strong></p>
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
                value = json.dumps(value, sort_keys=True)
            cells.append(f"<td>{esc(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _fold_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        output.append(
            {
                "fold_id": row.get("fold_id"),
                "full_event_pf": row.get("full_fold_distribution", {}).get("event_pf"),
                "active_event_pf": row.get("active_exposure_distribution", {}).get("event_pf"),
                "inactive_event_pf": row.get("inactive_or_unmapped_distribution", {}).get("event_pf"),
                "worst_regimes": [item.get("regime") for item in row.get("worst_regimes", [])[:3]],
                "worst_age_buckets": [item.get("segment_age_bucket") for item in row.get("worst_age_buckets", [])[:3]],
            }
        )
    return output


def _tests(payload: Mapping[str, Any]) -> str:
    if "commands" in payload:
        return table(payload["commands"], ["command", "result"])
    return table([payload], ["command", "result"])


if __name__ == "__main__":
    main()
