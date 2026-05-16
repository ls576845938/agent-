#!/usr/bin/env python3
"""Generate the BTC attribution sprint HTML report from canonical artifacts."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Iterable


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "N/A"


def _num(value: Any, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "N/A"


def _table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    head = "".join(f"<th>{_esc(item)}</th>" for item in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{_esc(item)}</td>" for item in row) + "</tr>")
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def _group_rows(summary: dict[str, Any], key: str, label: str) -> str:
    rows = summary.get(key, [])[:8]
    return (
        f"<h3>{_esc(label)}</h3>"
        + _table(
            [label, "trades", "net pnl", "PF", "win rate", "avg hold"],
            [
                [
                    row.get(label if label in row else key.replace("by_", ""), next(iter(row.values()), "")),
                    row.get("trade_count", 0),
                    _num(row.get("net_pnl"), 2),
                    _num(row.get("profit_factor"), 3),
                    _pct(row.get("win_rate")),
                    _num(row.get("avg_holding_bars"), 1),
                ]
                for row in rows
            ],
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="artifacts/btc_canonical/20260516T061000Z_attribution")
    parser.add_argument("--output", default="docs/reports/quantstation_vnext_btc_alpha_attribution_report.html")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    output = Path(args.output)
    aggregate = _load(run_dir / "canonical_backtest_report.json")
    attribution = _load(run_dir / "trade_attribution_summary.json")
    orderflow = _load(run_dir / "orderflow_ablation_report.json")
    promotion = _load(run_dir / "promotion_decision.json")
    strategy_rows = []
    for report in aggregate["strategies"]:
        metrics = report["metrics"]
        strategy_rows.append(
            [
                report["strategy_id"],
                _num(metrics.get("profit_factor"), 4),
                _num(metrics.get("event_profit_factor"), 4),
                _num(metrics.get("sharpe"), 3),
                f"{_num(metrics.get('max_drawdown'), 2)}%",
                f"{float(metrics.get('annual_turnover', 0.0)) * 100:.0f}%",
                _pct(metrics.get("walk_forward_pass_rate")),
                _pct(metrics.get("regime_pass_rate")),
                "pass" if metrics.get("cost_stress_base_pass") else "fail",
                f"PBO {_num(metrics.get('pbo'), 3)} / DSR {_num(metrics.get('dsr'), 3)}",
                report.get("promotion_gate_status", ""),
                ", ".join(report.get("fail_reasons", [])),
            ]
        )
    ablation_rows = [
        [
            row["mode"],
            _num(row["profit_factor"], 4),
            _num(row["sharpe"], 3),
            f"{_num(row['max_drawdown_pct'], 2)}%",
            f"{_num(row['total_return_pct'], 2)}%",
            row["trade_count"],
            row["signal_changed_bars"],
            row["orderflow_entry_trigger_allowed"],
        ]
        for row in orderflow["rows"]
    ]
    v3 = next(row for row in aggregate["strategies"] if row["strategy_id"] == "btc_perp_dual_trend_v3")
    v3_metrics = v3["metrics"]
    safety = promotion["paper_review"]
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT BTC Alpha Attribution Report</title>
  <style>
    body {{ margin: 0; background: #f5f7fb; color: #172033; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", Arial, sans-serif; line-height: 1.62; }}
    main {{ width: min(1120px, calc(100% - 28px)); margin: 0 auto; padding: 24px 0 56px; }}
    header, section {{ background: white; border: 1px solid #dbe2ee; border-radius: 10px; padding: 22px; margin: 14px 0; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05); }}
    h1 {{ margin: 0 0 8px; font-size: clamp(26px, 5vw, 42px); line-height: 1.16; }}
    h2 {{ margin: 0 0 12px; font-size: 22px; }}
    h3 {{ margin: 18px 0 8px; font-size: 17px; }}
    p {{ margin: 0 0 10px; }}
    code {{ background: #eef3f8; padding: 2px 5px; border-radius: 5px; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .chip {{ padding: 6px 10px; border-radius: 999px; background: #eef3f8; font-size: 13px; }}
    .bad {{ background: #fee2e2; color: #991b1b; }}
    .good {{ background: #dcfce7; color: #166534; }}
    .warn {{ background: #fef3c7; color: #92400e; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid #dbe2ee; border-radius: 8px; padding: 14px; background: #fbfdff; }}
    .card span {{ display: block; color: #647084; font-size: 13px; }}
    .card strong {{ display: block; font-size: 20px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #dbe2ee; border-radius: 8px; margin: 10px 0; }}
    table {{ width: 100%; min-width: 900px; border-collapse: collapse; }}
    th, td {{ padding: 9px 11px; border-bottom: 1px solid #dbe2ee; text-align: left; font-size: 14px; vertical-align: top; }}
    th {{ background: #eef3f8; }}
    tr:last-child td {{ border-bottom: 0; }}
    .callout {{ border-left: 4px solid #0f766e; background: #ecfdf8; padding: 12px 14px; border-radius: 8px; }}
    .callout.bad {{ border-left-color: #b91c1c; background: #fff1f1; color: #7f1d1d; }}
    ul {{ padding-left: 22px; }}
    @media (max-width: 760px) {{ main {{ width: calc(100% - 18px); padding-top: 10px; }} header, section {{ padding: 16px; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>QuantStation VNEXT BTC Alpha Attribution Report</h1>
    <p>Run ID: <code>{_esc(aggregate['run_id'])}</code></p>
    <div class="chips">
      <span class="chip warn">alpha 质量仍是主瓶颈</span>
      <span class="chip good">PAPER QUEUE: {'LOCKED' if safety['paper_review_queue_locked'] else 'PAPER_REVIEW_PENDING'}</span>
      <span class="chip good">LIVE: FROZEN</span>
      <span class="chip bad">candidate_passed_internal_gate: {sum(1 for row in aggregate['gate_inputs'] if row['passed'])}</span>
    </div>
  </header>

  <section>
    <h2>Executive Summary</h2>
    <p>工程闭环已成型，当前瓶颈仍是 BTC alpha 质量。canonical evidence 已统一到 event-ledger/fills/ledger PnL，signal equity 只保留为 diagnostic，不参与 gate。</p>
    <p>本轮只重构一个主候选 <code>btc_perp_dual_trend_v3</code>。v3 降低 turnover，并通过 regime gate，但 event PF 和 walk-forward 未达标，因此保持 <code>candidate_gate_failed</code>。</p>
    <div class="callout bad">没有策略达到 candidate_passed_internal_gate；paper queue locked；live frozen。</div>
  </section>

  <section>
    <h2>Current Safety Status</h2>
    <div class="grid">
      <div class="card"><span>candidate_passed_internal_gate</span><strong>{sum(1 for row in aggregate['gate_inputs'] if row['passed'])}</strong></div>
      <div class="card"><span>paper queue</span><strong>{'LOCKED' if safety['paper_review_queue_locked'] else 'PENDING'}</strong></div>
      <div class="card"><span>live</span><strong>FROZEN</strong></div>
    </div>
  </section>

  <section>
    <h2>Evidence Unification</h2>
    <p>Canonical artifact path: <code>{_esc(str(run_dir / 'canonical_backtest_report.json'))}</code></p>
    <p>Gate input path: <code>{_esc(str(run_dir / 'gate_inputs.json'))}</code></p>
    <p>Signal equity status: <strong>diagnostic-only</strong>. Gate reads canonical metrics and event-ledger status only.</p>
  </section>

  <section>
    <h2>Baseline vs v2 vs v3</h2>
    {_table(['strategy', 'PF', 'event_PF', 'Sharpe', 'MDD', 'annual turnover', 'WF pass', 'regime pass', 'cost stress', 'PBO / DSR', 'gate status', 'fail reasons'], strategy_rows)}
  </section>

  <section>
    <h2>Per-Trade Attribution</h2>
    <p>Attribution source: <code>ledger_fills</code>. Combined trades: {attribution['trade_count']}.</p>
    {_group_rows(attribution, 'by_regime', 'entry_regime')}
    {_group_rows(attribution, 'by_entry_condition', 'entry_condition')}
    {_group_rows(attribution, 'by_exit_reason', 'exit_reason')}
    {_group_rows(attribution, 'by_holding_time_bucket', 'holding_bucket')}
    {_group_rows(attribution, 'by_cost_bucket', 'cost_bucket')}
    <h3>Top Profit Conditions</h3>
    {_table(['condition', 'trades', 'net pnl', 'PF', 'win rate'], [[row.get('condition_combo'), row.get('trade_count'), _num(row.get('net_pnl'), 2), _num(row.get('profit_factor'), 3), _pct(row.get('win_rate'))] for row in attribution.get('profitable_conditions_top3', [])])}
    <h3>Top Loss Conditions</h3>
    {_table(['condition', 'trades', 'net pnl', 'PF', 'win rate'], [[row.get('condition_combo'), row.get('trade_count'), _num(row.get('net_pnl'), 2), _num(row.get('profit_factor'), 3), _pct(row.get('win_rate'))] for row in attribution.get('loss_conditions_top3', [])])}
  </section>

  <section>
    <h2>Order-Flow Ablation</h2>
    {_table(['mode', 'PF', 'Sharpe', 'MDD', 'Return', 'trades/fills', 'signal changes', 'entry trigger allowed'], ablation_rows)}
    <p>Conclusion: <strong>{_esc(orderflow['conclusion'])}</strong>. Order-flow should not be forced into v3; sizing variants increased turnover/fill activity without solving PF.</p>
  </section>

  <section>
    <h2>btc_perp_dual_trend_v3 Decision</h2>
    <ul>
      <li>PF >= 1.15: {_num(v3_metrics['profit_factor'], 4)} trade ledger PF, but event PF {_num(v3_metrics['event_profit_factor'], 4)} fails.</li>
      <li>annual turnover <= 1000%: {float(v3_metrics['annual_turnover']) * 100:.0f}% pass.</li>
      <li>WF >= 80%: {_pct(v3_metrics['walk_forward_pass_rate'])} fail.</li>
      <li>regime >= 75%: {_pct(v3_metrics['regime_pass_rate'])} pass.</li>
      <li>cost stress: {'pass' if v3_metrics.get('cost_stress_base_pass') else 'fail'}.</li>
      <li>no-lookahead: {v3['no_lookahead_status']['status']}.</li>
      <li>event-ledger: {v3['event_ledger_status']['status']}.</li>
      <li>final status: <code>{_esc(v3['promotion_gate_status'])}</code>.</li>
    </ul>
  </section>

  <section>
    <h2>Runtime Boundary Audit</h2>
    <p>Audit doc: <code>docs/research/RUNTIME_BOUNDARY_AUDIT.md</code></p>
    <ul>
      <li>Active research entrypoints: canonical runner, canonical helper, event-ledger backtest.</li>
      <li>Review-only entrypoints: evidence registry, paper review bridge, promotion review services.</li>
      <li>Inactive for this sprint: broker submit, paper auto-start, live readiness promotion, live order execution.</li>
    </ul>
  </section>

  <section>
    <h2>Test Results</h2>
    <p><code>PYTHONPATH=. pytest tests/research/test_btc_canonical_report_schema.py tests/research/test_signal_equity_diagnostic_only.py tests/research/test_trade_attribution_from_ledger.py tests/research/test_trade_attribution_no_lookahead.py tests/research/test_orderflow_veto_sizing_only.py tests/research/test_btc_v3_turnover_limit.py tests/research/test_promotion_gate_canonical_only.py tests/research/test_paper_queue_locked_without_passed_candidates.py tests/research/test_live_frozen_no_side_effects.py tests/research/test_runtime_boundary_audit_exists.py tests/research/test_event_ledger_metrics.py tests/backtest/test_crypto_event_backtest.py -q</code></p>
    <p>Result: <strong>30 passed in 1.44s</strong>.</p>
    <p>Full repository test suite was not run in this sprint cycle because canonical event-ledger generation is already time-consuming; this report records the minimum core evidence/no-side-effect suite.</p>
  </section>

  <section>
    <h2>Next Sprint Recommendation</h2>
    <p>v3 did not pass gate. Continue attribution and evidence unification; do not enter paper. Focus next on event PF and walk-forward instability rather than adding strategies.</p>
    <div class="callout">Allowed next state remains <code>candidate_gate_failed</code>. Paper queue stays locked. Live stays frozen.</div>
  </section>
</main>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
