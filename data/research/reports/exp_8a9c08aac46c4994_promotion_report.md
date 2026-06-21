# Research Report v2: exp_8a9c08aac46c4994

**Strategy:** trend_momentum  
**Status:** PROMOTED_TO_CANDIDATE  
**Created:** 2026-05-11T02:49:33.952576+00:00  
**Symbols:** SPY  


## Experiment Summary
| Field | Value |
|-------|-------|
| Experiment ID | exp_8a9c08aac46c4994 |
| Strategy Family | cost_stress_momentum_research_smoke |
| Data Version | qs-yfinance-SPY-1d-268b4e155ee3 |
| Date Range | 2024-01-01 -> 2024-12-31 |
| Cost Model | low |
| Walk Forward Config | {} |

### Metrics

| Metric | Value |
|--------|-------|
| annual_return_pct | 0.5015 |
| annual_volatility_pct | 0.9181 |
| backtest_manifest_id | ubt_4ec815ef36364725 |
| backtest_manifest_path | data/manifests/run_ubt_4ec815ef36364725.json |
| baseline_fill_count | 27 |
| baseline_order_count | 27 |
| cagr_pct | 0.5015 |
| calmar_ratio | 0.6342 |
| canonical_for_promotion | True |
| cost_model | low |
| data_manifest_exists | True |
| data_manifest_path | data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json |
| data_version | qs-yfinance-SPY-1d-268b4e155ee3 |
| engine | event_driven |
| fills_hash | e5a29120a25ad6094e0f2bf4b13a5c7ab72337eecde1b3f7c7f03322ff6151fb |
| ledger_artifact_hash | bdc2f48a947c5821bda2d59290e628ef4fb6d30a9319694578a2699232f8c426 |
| ledger_artifact_path | data/manifests/reconciliation/ledger_recon_artifact_bdc2f48a947c5821.json |
| ledger_consistency_pct | 100.0000 |
| ledger_hash | f899a5abf3c9d39a820786ed7c94577f27b937e684b2e04423652c46fea1b4c9 |
| max_drawdown_pct | -0.7908 |
| missing_data_manifest | False |
| orders_hash | ed43ff895730d6f93caac2be39d1d23f4e73a70a1fcf6c4d1ceec2eb76bc8bd7 |
| profit_factor | 1.1247 |
| sharpe_ratio | 0.5495 |
| slippage_model | low |
| sortino_ratio | 0.5447 |
| total_fill_count | 27 |
| total_order_count | 27 |
| total_return_pct | 0.4995 |
| trade_count | 27 |
| turnover_pct | 80.9119 |
| win_rate_pct | 58.5106 |


## Candidate Scorecards
| Candidate | Sharpe | CAGR | MaxDD | OOS Deg | WFR | Overfit | Robust |
|-----------|--------|------|-------|---------|-----|---------|--------|
| cand_20b90fd795c | 0.55 | 49.95% | 79.08% | 0.00% | 0.00% | LOW      | 0.60 |


## Walk-Forward Summary
| Candidate | WFR Pass Rate | OOS Degradation | Stability Score |
|-----------|---------------|-----------------|-----------------|
| cand_20b90fd795c | 0.00% | 0.00% | 0.40 |


## Anti-Overfit Findings
| Candidate | Overfit | Degradation | Param Sens | Year Conc | Sym Conc | Reasons |
|-----------|---------|-------------|------------|-----------|----------|--------|
| cand_20b90fd795c | no      | 0.0% | 0.000 | 0.0% | 0.0% | none |


## Validation Statistics
| Candidate | CV Method | Trials | DSR | PBO | Cost Drag | Validation Status |
|-----------|-----------|--------|-----|-----|-----------|-------------------|
| cand_20b90fd795c | unknown | 0 | N/A | N/A | N/A | partial |


## Promotion Gate Evaluation
| Candidate | Decision | Reasons | Warnings |
|-----------|----------|---------|----------|
| cand_20b90fd795c | BLOCKED                   | stale_data_manifest_binding: embedded backtest data manifest differs from the canonical persisted data manifest; data_manifest_id_mismatch: embedded=ecc00787c46eff1a governed=341bb17f28ecda64 | validation_cv_summary_missing: walk-forward evidence should declare purged/embargoed CV or CPCV metadata; validation_statistics_partial: promotion evidence is missing one or more validation statistics |


## Unified Backtest Evidence
### cand_20b90fd795cd4c1d
- Reconciliation Passed: True
- Max Abs Diff: 0.0000
- Max Pct Diff: 0.0000
- Failed Snapshot Summary: none
- Corporate Actions Digest: adjustment_count=0, split_event_count=0, total_dividends=0.0000, total_borrow_fees=0.0000, total_corporate_adjustments=0.0000



## "Ready for Paper Review" Summary
**Total evaluated:** 1  
**READY_FOR_PAPER_REVIEW:** 0  
**WATCHLIST:** 0  
**BLOCKED:** 1  


## Next Research Actions
1. **Review blocked candidates** (cand_20b90fd795c): Address blocking issues before re-evaluation.
4. **NOTE**: READY_FOR_PAPER_REVIEW does NOT enter paper trading. It only enters the human review pool.

