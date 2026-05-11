# Research Automation Contracts

## Generated Formula Factors

Generated factor specs under `data/research/generated_factors/factors.json` now carry:

- `formula_type`: `linear_combo`, `ratio`, `interaction`, `signed_power`, `gated_combo`, `minmax_spread`
- `components` and `weights`
- `params` for non-linear operators such as `power` and `gate_scale`
- `generation_family`
- `signature`

The `signature` is a canonicalized hash input. Commutative templates are normalized before hashing so duplicate seeds or component order do not create duplicate factors.

## Generated Strategy Configs

Factor mining emits research-only strategy DSL configs under `data/research/generated_strategies/` with:

- `template_id`
- `strategy_id`
- `factor_ids`
- `signal`
- `execution_semantics = signal_at_bar_close_order_next_bar`
- `risk_overlays`
- `lookahead_guard`

Current templates:

- `single_factor_rank`
- `weighted_factor_basket`
- `consensus_rank`

These artifacts are research configs only. They are not executable broker instructions.

## Promotion Gate Validation Contract

`quant_us.research.validation.summarize_candidate_validation()` now emits `promotion_gate_contract` and `multiple_testing` sections. The promotion gate treats the contract as a hard artifact for research promotion.

Required checks:

- CV method must be `cpcv`, `purged_kfold`, or `embargoed_walk_forward`
- Validation must be purged or embargoed
- At least 2 validation paths/folds
- At least 2 effective trials and 2 independent trials
- DSR must exist and be `>= 0.10`
- PBO must exist and be `<= 0.50`
- Family-wise multiple-testing control must be present and passed

This blocks candidates that only look good on a single validation path, even when the raw Sharpe is high.
