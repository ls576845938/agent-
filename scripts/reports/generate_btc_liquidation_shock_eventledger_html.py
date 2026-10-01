#!/usr/bin/env python3
"""Generate BTC liquidation-shock event-ledger validation HTML report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_liquidation_shock_validation import BTC_LIQUIDATION_SHOCK_VALIDATION_RUN_ID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LIQUIDATION_SHOCK_VALIDATION_RUN_ID)
    parser.add_argument("--artifact-root", default="artifacts/btc_candidate_validation")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = (
        Path(args.output)
        if args.output
        else Path("reports") / f"quantstation_vnext_btc_liquidation_shock_eventledger_{args.run_id}.html"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    canonical = _read(run_dir / "canonical_backtest_report.json")
    candidate = _read(run_dir / "candidate_validation_result.json")
    walk_forward = _read(run_dir / "walk_forward_report.json")
    regime = _read(run_dir / "regime_report.json")
    pbo_dsr = _read(run_dir / "pbo_dsr_report.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    cost = _read(run_dir / "cost_stress_report.json")
    tests = _read_optional(run_dir / "test_results.json")
    metrics = canonical["metrics"]
    final_line = "liquidation-shock recovery failed event-ledger gate; paper queue remains LOCKED; live remains FROZEN."
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Liquidation-Shock Event-Ledger Candidate Validation Report</title>
  <style>
    :root {{ --bg:#f6f8fb; --panel:#fff; --ink:#17202a; --muted:#596775; --line:#d7dee8; --navy:#14233b; --bad:#9b1c1c; --warn:#8a5a00; --ok:#126b45; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Arial, Helvetica, sans-serif; line-height:1.5; }}
    header {{ background:var(--navy); color:#fff; padding:24px 28px; }}
    main {{ max-width:1180px; margin:0 auto; padding:22px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; margin-bottom:18px; }}
    h1 {{ margin:0 0 8px; font-size:25px; }}
    h2 {{ margin:0 0 12px; font-size:20px; }}
    h3 {{ margin:16px 0 8px; font-size:16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(195px, 1fr)); gap:10px; }}
    .metric {{ border:1px solid var(--line); border-radius:6px; padding:10px; background:#fbfcfe; }}
    .metric strong {{ display:block; color:var(--muted); font-size:13px; }}
    .metric span {{ display:block; margin-top:4px; font-size:19px; font-weight:700; }}
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
  <h1>QuantStation VNEXT - BTC Liquidation-Shock Event-Ledger Candidate Validation Report</h1>
  <div>Run ID: {esc(run_dir.name)}</div>
</header>
<main>
  <section>
    <h2>Safety Status</h2>
    <div class="grid">
      <div class="metric"><strong>PAPER QUEUE</strong><span class="warn">{esc(safety.get("paper_queue", "LOCKED"))}</span></div>
      <div class="metric"><strong>LIVE</strong><span class="bad">{esc(safety.get("live", "FROZEN"))}</span></div>
      <div class="metric"><strong>candidate_passed_internal_gate</strong><span>{esc(safety.get("candidate_passed_internal_gate", 0))}</span></div>
      <div class="metric"><strong>Gate Status</strong><span class="bad">{esc(candidate.get("status", "unknown"))}</span></div>
    </div>
  </section>

  <section>
    <h2>Executive Summary</h2>
    <p><strong>{esc(final_line)}</strong></p>
    <ul>
      <li>Hypothesis layer passed, but event-ledger candidate validation failed.</li>
      <li>ordinary PF remains diagnostic; event_PF is the hard promotion metric.</li>
      <li>No paper review pending was created; live remains frozen.</li>
    </ul>
  </section>

  <section>
    <h2>Gate Metrics</h2>
    <div class="grid">
      <div class="metric"><strong>PF</strong><span>{fmt(metrics.get("profit_factor"))}</span></div>
      <div class="metric"><strong>event_PF</strong><span class="bad">{fmt(metrics.get("event_profit_factor"))}</span></div>
      <div class="metric"><strong>Sharpe</strong><span>{fmt(metrics.get("sharpe"))}</span></div>
      <div class="metric"><strong>MDD %</strong><span>{fmt(metrics.get("max_drawdown"))}</span></div>
      <div class="metric"><strong>Turnover</strong><span>{fmt(metrics.get("annual_turnover"))}</span></div>
      <div class="metric"><strong>WF Pass</strong><span class="bad">{fmt(metrics.get("walk_forward_pass_rate"))}</span></div>
      <div class="metric"><strong>Regime Pass</strong><span class="ok">{fmt(metrics.get("regime_pass_rate"))}</span></div>
      <div class="metric"><strong>PBO / DSR</strong><span>{fmt(metrics.get("pbo"))} / {fmt(metrics.get("dsr"))}</span></div>
    </div>
    <p>Fail reasons: <code>{esc(", ".join(candidate.get("gate_fail_reasons", [])))}</code></p>
  </section>

  <section>
    <h2>Walk-Forward</h2>
    <p>Pass rate: <strong>{fmt(walk_forward.get("pass_rate"))}</strong></p>
    {table(_wf_rows(walk_forward.get("windows", [])), ["fold", "passed", "profit_factor", "trade_count", "total_return_pct", "max_drawdown_pct"])}
  </section>

  <section>
    <h2>Regime Gate</h2>
    <p>Pass rate: <strong>{fmt(regime.get("pass_rate"))}</strong>; dragging regimes: <code>{esc(", ".join(regime.get("dragging_regimes", [])))}</code></p>
    {table(regime.get("regimes", []), ["regime", "passed", "trade_count", "profit_factor", "net_pnl", "win_rate"])}
  </section>

  <section>
    <h2>Cost Stress</h2>
    <p>Base pass: <strong>{esc(cost.get("base", {}).get("passed", metrics.get("cost_stress_base_pass")))}</strong>; harsh survives: <strong>{esc(cost.get("harsh", {}).get("survives", metrics.get("cost_stress_harsh_survives")))}</strong></p>
    {table(_cost_rows(cost), ["scenario", "profit_factor", "total_return_pct", "max_drawdown_pct", "passed", "survives"])}
  </section>

  <section>
    <h2>PBO / DSR</h2>
    {table([{"pbo": pbo_dsr.get("pbo"), "dsr": pbo_dsr.get("dsr"), "warnings": pbo_dsr.get("warnings", [])}], ["pbo", "dsr", "warnings"])}
  </section>

  <section>
    <h2>Promotion Decision</h2>
    <ul>
      <li>event_PF gate: failed.</li>
      <li>WF gate: failed.</li>
      <li>Regime gate: passed.</li>
      <li>Cost stress: failed.</li>
      <li>PBO/DSR: DSR failed.</li>
      <li>No-lookahead: pass by construction and tests.</li>
      <li>Event-ledger: pass as evidence source, fail as performance gate.</li>
    </ul>
  </section>

  <section>
    <h2>Tests</h2>
    {_tests(tests)}
  </section>

  <section>
    <h2>Artifacts</h2>
    <ul class="paths">
      {''.join(f'<li><code>{esc(str(path))}</code></li>' for path in sorted(run_dir.iterdir()) if path.is_file())}
    </ul>
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


def _wf_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        summary = row.get("summary", {})
        out.append(
            {
                "fold": row.get("fold"),
                "passed": row.get("passed"),
                "profit_factor": summary.get("profit_factor"),
                "trade_count": summary.get("trade_count"),
                "total_return_pct": summary.get("total_return_pct"),
                "max_drawdown_pct": summary.get("max_drawdown_pct"),
            }
        )
    return out


def _cost_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, value in payload.items():
        if isinstance(value, Mapping) and "summary" in value:
            summary = value.get("summary", {})
            rows.append(
                {
                    "scenario": key,
                    "profit_factor": summary.get("profit_factor"),
                    "total_return_pct": summary.get("total_return_pct"),
                    "max_drawdown_pct": summary.get("max_drawdown_pct"),
                    "passed": value.get("passed"),
                    "survives": value.get("survives"),
                }
            )
    return rows


def _tests(payload: Mapping[str, Any]) -> str:
    if "commands" in payload:
        return table(payload["commands"], ["command", "result"])
    return table([payload], ["command", "result"])


if __name__ == "__main__":
    main()
