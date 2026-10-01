# US v3 domain read-model contract

`us_equity_domain_read_model_v1` is a read-only, current-HEAD projection over
the committed G06 data/PIT, G07 canonical backtest/portfolio, and G08
OMS/ledger/recovery evidence.

## Source and path rules

- Source evidence is read from `git show <current-head>:<path>`, not mutable
  working-tree bytes.
- Every source integration commit must be an ancestor of the projected HEAD.
- Artifact and manifest SHA-256 values are validated against committed LF bytes.
- Durable repository-relative paths use POSIX separators. Absolute, parent
  traversal, and Windows private paths fail closed.
- Missing artifacts, missing manifests, schema mismatch, hash mismatch, and a
  wrong HEAD produce `freshness=blocked`.

## Read and materialization boundaries

- `USDomainReadModelService.read()` builds only an in-memory projection.
- `GET /api/research/us-equity/domain-read-model` sets `Cache-Control:
  no-store`, has no write path, and never triggers data sync, backtest, paper
  run/reset, broker runtime, or order submission.
- Only `scripts/build_us_equity_domain_read_model.py` may materialize the Team
  Context candidate at
  `artifacts/us_equity_strategy_production_line/latest/us_equity_operator_read_model.json`.
- The materialized artifact is valid only when `source_head` equals current
  HEAD and its canonical identity hash matches.

## Gate semantics

The current evidence remains blocked by missing production PIT and separately
authorized paper evidence/approval. `quality_checked`, `research_ready`, and
`backtest_ready` do not imply promotion eligibility. Promotion, paper, live,
private, order, broker, queue, withdraw, and real-order flags are all false.
