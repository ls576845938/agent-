# BTC Promotion Gate Rules

## Allowed Research States

- `research_failed`
- `research_candidate`
- `candidate_gate_failed`
- `candidate_passed_internal_gate`
- `paper_review_pending`

## Forbidden States In This Sprint

- `paper_ready`
- `live_ready`
- `live_enabled`

## Internal Gate

A candidate can reach `candidate_passed_internal_gate` only if all checks pass:

- Profit Factor >= `1.15`
- event-ledger Profit Factor >= `1.15`
- walk-forward pass rate >= `0.80`
- regime pass rate >= `0.75`
- annual turnover <= `15.0`
- max drawdown >= `-15.0%`
- base cost stress passes
- harsh cost stress does not collapse
- no-lookahead check passes
- event-ledger diagnostics pass with PnL from `ledger_fills`
- DSR >= `0.10`
- PBO <= `0.50`

## Paper Review Lock

The paper review queue remains locked unless 1 to 3 candidates pass the full internal gate. Even then:

- `paper_review_pending` is the maximum state.
- `paper_auto_start` remains `false`.
- no paper runtime is started.
- live remains frozen.

If no candidates pass, candidates remain `candidate_gate_failed`.
