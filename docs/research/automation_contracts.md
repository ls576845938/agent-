# Research Automation Contracts

## Generated Formula Factors

Generated factor specs under `data/research/generated_factors/factors.json` now carry:

- `formula_type`: `linear_combo`, `ratio`, `interaction`, `signed_power`, `gated_combo`, `minmax_spread`
- `components` and `weights`
- `params` for non-linear operators such as `power` and `gate_scale`
- `generation_family`
- `signature`
- `complexity_score`

The `signature` is a canonicalized hash input. Commutative templates are normalized before hashing so duplicate seeds or component order do not create duplicate factors.
Generation also enforces a configurable `max_complexity` ceiling so automated formula search does not spill into overly nested blends before the research gate.

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

BTC family-sweep candidate generation under `quant_us.research.automation.candidate_gen` now also supports conservative research-only candidate packs with:

- `strategy_family = btc_conservative_family_sweep`
- `strategy_family_variant` and `strategy_family_class`
- `research_metadata.regime`
- `research_metadata.filters`
- `research_metadata.turnover_aware`
- `research_metadata.runtime_hints`
- `gate_requirements.requires_walk_forward`
- `gate_requirements.requires_cost_stress`
- `gate_requirements.requires_regime_evidence`

These fields are candidate metadata only. They do not replace walk-forward, cost-stress, event-ledger, or promotion-gate evidence, and BTC/crypto candidates remain fail-closed without canonical persisted artifacts.

Factor-mining outputs now also persist research evidence that is used to keep
the candidate set small and interpretable:

- `candidate_rank`
- `stability_score` and `stability_components`
- `score_components`
- `candidate_evidence.style_exposure`
- `correlation_report_path`
- top-level `manifest_evidence`

`candidate_evidence.style_exposure` is derived from factor values at timestamp
`t` versus next-bar returns from `t -> t+1` only. Correlation de-duplication is
persisted under `data/research/factor_mining/<run_id>_correlation.json` so
rejected near-duplicate factors leave an auditable trail.

## Promotion Gate Validation Contract

`quant_us.research.validation.summarize_candidate_validation()` now emits `promotion_gate_contract` and `multiple_testing` sections. The promotion gate treats the contract as a hard artifact for research promotion.

Required checks:

- CV method must be recorded as `cpcv` for promotion-statistics evidence
- Validation must record purge and embargo parameters explicitly
- No-lookahead feature/label timing controls must be recorded
- At least 2 validation paths/folds
- At least 2 effective trials and 2 independent trials
- DSR must exist and be `>= 0.10`
- PBO must exist and be `<= 0.50`
- Family-wise multiple-testing control must be present and passed

This blocks candidates that only look good on a single validation path, candidates
with inferred-but-unrecorded purge/embargo controls, and candidates whose raw
Sharpe does not survive DSR/PBO/multiple-testing checks.

## Strategy Manifest Contract

Paper-review evidence now summarizes each strategy manifest against a documented contract. Required research fields include:

- `trial_count`
- `pbo`
- `dsr`
- `cpcv`
- `cost_stress`
- `style_exposure`
- `turnover`
- `capacity`

The summary separates:

- `contract_complete`: every required field is present
- `contract_documented`: every missing field has an explicit reason

Portfolio evidence may explain why a field is missing, but promotion and paper-review gates remain fail-closed when key statistics are absent.
