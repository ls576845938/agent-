#!/usr/bin/env python3
"""Generate BTC low-vol uptrend hypothesis HTML report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_us.research.btc_low_vol_uptrend import BTC_LOW_VOL_UPTREND_RUN_ID


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=BTC_LOW_VOL_UPTREND_RUN_ID)
    parser.add_argument("--artifact-root", default="artifacts/btc_hypothesis")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    run_dir = Path(args.artifact_root) / args.run_id
    output = Path(args.output) if args.output else Path("reports") / f"quantstation_vnext_btc_low_vol_uptrend_hypothesis_{args.run_id}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(run_dir), encoding="utf-8")
    print(output)


def render_report(run_dir: Path) -> str:
    profile = _read(run_dir / "low_vol_uptrend_feature_profile.json")
    distribution = _read(run_dir / "low_vol_uptrend_distribution_report.json")
    decision = _read(run_dir / "low_vol_uptrend_hypothesis_decision.json")
    safety = _read(run_dir / "paper_live_safety_status.json")
    tests = _read_optional(run_dir / "test_results.json")
    if decision.get("decision") == "hypothesis_passed_for_strategy_skeleton":
        final_line = "hypothesis passed; strategy skeleton generated; paper queue remains LOCKED; live remains FROZEN."
    elif decision.get("decision") == "hypothesis_needs_more_data":
        final_line = "hypothesis needs more data; no strategy generated; paper queue remains LOCKED; live remains FROZEN."
    else:
        final_line = "hypothesis rejected; no strategy generated; paper queue remains LOCKED; live remains FROZEN."
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QuantStation VNEXT - BTC Low-Vol Uptrend Event-Continuation Research Report</title>
  <style>
    :root {{ --bg:#f6f8fb; --panel:#fff; --ink:#17202a; --muted:#596775; --line:#d7dee8; --navy:#14233b; --bad:#9b1c1c; --warn:#8a5a00; --ok:#126b45; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:Arial, Helvetica, sans-serif; line-height:1.5; }}
    header {{ background:var(--navy); color:#fff; padding:24px 28px; }}
    main {{ max-width:1180px; margin:0 auto; padding:22px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; margin-bottom:18px; }}
    h1 {{ margin:0 0 8px; font-size:26px; }}
    h2 {{ margin:0 0 12px; font-size:20px; }}
    h3 {{ margin:16px 0 8px; font-size:16px; }}
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
  <h1>QuantStation VNEXT - BTC Low-Vol Uptrend Event-Continuation Research Report</h1>
  <div>Run ID: {esc(run_dir.name)}</div>
</header>
<main>
  <section>
    <h2>Safety Status</h2>
    <div class="grid">
      <div class="metric"><strong>PAPER QUEUE</strong><span class="warn">{esc(safety.get("paper_queue", "LOCKED"))}</span></div>
      <div class="metric"><strong>LIVE</strong><span class="bad">{esc(safety.get("live", "FROZEN"))}</span></div>
      <div class="metric"><strong>candidate_passed_internal_gate</strong><span>{esc(safety.get("candidate_passed_internal_gate", 0))}</span></div>
      <div class="metric"><strong>Hypothesis Decision</strong><span>{esc(decision.get("decision", "unknown"))}</span></div>
    </div>
  </section>

  <section>
    <h2>Executive Summary</h2>
    <p><strong>{esc(final_line)}</strong></p>
    <ul>
      <li>perp_dual_trend remains archived and was not restored.</li>
      <li>This sprint is research-only distribution profiling, not a paper candidate.</li>
      <li>Order-flow is not used as an entry trigger.</li>
    </ul>
  </section>

  <section>
    <h2>Previous Sprint Recap</h2>
    <ul>
      <li>perp_dual_trend archived after event-return evidence showed event_PF stuck near 1.01-1.02.</li>
      <li>Low-vol uptrend was selected from the alpha backlog because prior attribution favored long continuation contexts.</li>
      <li>Paper queue and live remain locked/frozen.</li>
    </ul>
  </section>

  <section>
    <h2>Feature Definition</h2>
    {table_dict(profile.get("feature_definitions", {}))}
    <p>No-lookahead guarantee: <code>{esc(profile.get("no_lookahead", {}).get("status", "unknown"))}</code>; future returns are labels only.</p>
  </section>

  <section>
    <h2>Event-Return Distribution</h2>
    <div class="grid">
      <div class="metric"><strong>Active events</strong><span>{esc(distribution.get("overall_distribution", {}).get("active_event_count"))}</span></div>
      <div class="metric"><strong>event_PF_proxy</strong><span>{fmt(distribution.get("overall_distribution", {}).get("event_PF_proxy"))}</span></div>
      <div class="metric"><strong>Median return</strong><span>{fmt(distribution.get("overall_distribution", {}).get("median_return"))}</span></div>
      <div class="metric"><strong>Downside tail 5%</strong><span>{fmt(distribution.get("overall_distribution", {}).get("downside_tail_5pct"))}</span></div>
    </div>
    {table([distribution.get("overall_distribution", {})], ["active_event_count", "positive_event_rate", "mean_return", "median_return", "positive_sum", "negative_sum", "event_PF_proxy", "max_adverse_event", "max_favorable_event"])}
  </section>

  <section>
    <h2>Fold Stability</h2>
    {table(distribution.get("fold_stability", {}).get("folds", []), ["fold_id", "active_event_count", "event_PF_proxy", "mean_return", "median_return", "positive_event_rate", "downside_tail_5pct", "passed"])}
  </section>

  <section>
    <h2>Horizon Analysis</h2>
    {table(_horizon_rows(distribution.get("holding_horizon_analysis", {})), ["horizon", "active_event_count", "event_PF_proxy", "positive_event_rate", "mean_return", "median_return", "downside_tail_5pct"])}
  </section>

  <section>
    <h2>Hypothesis Decision</h2>
    <p>Decision: <strong>{esc(decision.get("decision", "unknown"))}</strong></p>
    <p>Strategy skeleton generated: <strong>{esc(decision.get("strategy_skeleton_generated", False))}</strong></p>
    {ul(decision.get("reasons", []))}
  </section>

  <section>
    <h2>Strategy Skeleton</h2>
    <p>{'Generated at <code>' + esc(decision.get('strategy_skeleton_path', '')) + '</code>' if decision.get('strategy_skeleton_generated') else 'No strategy skeleton generated. The sprint remains research-only.'}</p>
  </section>

  <section>
    <h2>Tests</h2>
    <p><strong>Command:</strong> <code>{esc(tests.get("command", "N/A"))}</code></p>
    <p><strong>Result:</strong> <code>{esc(tests.get("result", "N/A"))}</code></p>
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
        return f"{float(value):.6f}"
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


def table_dict(payload: Mapping[str, Any]) -> str:
    return table([{"field": key, "definition": value} for key, value in payload.items()], ["field", "definition"])


def _horizon_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, stats in payload.items():
        row = {"horizon": key}
        row.update(dict(stats))
        rows.append(row)
    return rows


if __name__ == "__main__":
    main()
