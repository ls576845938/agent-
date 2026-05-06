# QuantStation VNEXT Agent Rules

## Project Goal

Build a personal US equity quantitative trading platform.

Priority order:
1. Data correctness
2. Backtest reproducibility
3. Ledger correctness
4. Risk control
5. Execution reliability
6. Strategy performance

## Hard Rules

- Strategy must not call broker directly.
- Strategy only emits Signal, OrderIntent, or TargetPosition.
- All orders must pass Risk Engine.
- All PnL must be derived from fills and ledger.
- Every backtest must generate a manifest.
- Every experiment must record: data_version, strategy_version, params, cost_model, slippage_model, commit_hash.
- Do not optimize Sharpe before validating cost, slippage, and walk-forward robustness.
- Do not introduce live trading code before paper trading gate passes.
- No future function. No look-ahead bias.
- No survivorship-bias-prone universe unless explicitly marked.

## Agent Matrix

### Daily (3 agents)

| Agent | Role | Reasoning | Can Edit Code |
|-------|------|-----------|---------------|
| quant-architect | Module boundaries, interfaces, DB, task decomposition | high / xhigh | No (docs only) |
| quant-developer | Implement features per ticket | medium / high | Yes |
| quant-risk-auditor | Tests, future-function, cost defects, backtest bugs | high | Tests yes, source minimal |

### Sprint 2/3 (5 agents)

| Agent | Role | Reasoning | Scope |
|-------|------|-----------|-------|
| quant-architect | Architecture, trading path, research gate | high / xhigh | Read-only + docs |
| data-engineer | Data sources, cleaning, manifest, quality | high | `quant_us/data/`, `tests/`, schema |
| backtest-engineer | Event-driven engine, fills, ledger, PnL | high | `quant_us/backtest/`, `tests/` |
| quant-risk-auditor | Audit, tests, cost stress, look-ahead | high | Tests freely, source via patch plan |
| dx-frontend-agent | Dashboard, reports, DX, docs | low / medium | `frontend/` only (non-core) |

## Reasoning Effort Guide

| Task | Reasoning |
|------|-----------|
| Daily development | medium |
| Architecture review | high / xhigh |
| Complex bug | high |
| Test writing | medium / high |
| Frontend styling | low / medium |
| Documentation | low / medium |

Default: `reasoning = medium`, `personality = "pragmatic"`.

## Coding Rules

- Keep modules small.
- Prefer typed dataclasses / Pydantic for core objects.
- Use UTC internally. No implicit timezone conversion.
- Add tests for every core module change.
- Run relevant tests after changes. Report failures with exact command and output.
- Do not rewrite unrelated files.
- Do not silently catch trading or accounting errors.

## Current Priority

Build trustworthy research pipeline:
data quality → cost stress → walk-forward → ledger-based backtest → promotion gate.

Frontend is good enough. Real短板: data, backtest, risk, ledger.
