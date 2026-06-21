# Research Report v2: exp_e22e6ad04f774d14

**Strategy:** trend_momentum  
**Status:** PROMOTED_TO_CANDIDATE  
**Created:** 2026-05-11T02:49:33.693365+00:00  
**Symbols:** SPY  


## Experiment Summary
| Field | Value |
|-------|-------|
| Experiment ID | exp_e22e6ad04f774d14 |
| Strategy Family | cost_stress_momentum_research_smoke |
| Data Version | qs-yfinance-SPY-1d-268b4e155ee3 |
| Date Range | 2024-01-01 -> 2024-12-31 |
| Cost Model | high |
| Walk Forward Config | {} |

### Metrics

| Metric | Value |
|--------|-------|
| annual_return_pct | 0.4199 |
| annual_volatility_pct | 0.9184 |
| backtest_manifest_id | ubt_197f367ff9684369 |
| backtest_manifest_path | data/manifests/run_ubt_197f367ff9684369.json |
| baseline_fill_count | 27 |
| baseline_order_count | 27 |
| cagr_pct | 0.4199 |
| calmar_ratio | 0.5179 |
| canonical_for_promotion | True |
| cost_model | high |
| data_manifest_exists | True |
| data_manifest_path | data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json |
| data_version | qs-yfinance-SPY-1d-268b4e155ee3 |
| engine | event_driven |
| fills_hash | fc8b49b9a3684851343856e7cd2353ab3870121e732be7bb8618a5e04420b24c |
| ledger_artifact_hash | be45421ecee3c29b6a5e313c8bc50be499217cdf33207c1c36dc19138b2f0cbb |
| ledger_artifact_path | data/manifests/reconciliation/ledger_recon_artifact_be45421ecee3c29b.json |
| ledger_consistency_pct | 100.0000 |
| ledger_hash | d4f9d61c517d91c23b717d93b09073ae001910badc411a5a0ac03ac711aefb6f |
| max_drawdown_pct | -0.8108 |
| missing_data_manifest | False |
| orders_hash | f3a87bab00dd46c0da82b6d4f48ce4b6961352c06a486cb853d0c8825605c219 |
| profit_factor | 1.1034 |
| sharpe_ratio | 0.4608 |
| slippage_model | high |
| sortino_ratio | 0.4631 |
| total_fill_count | 27 |
| total_order_count | 27 |
| total_return_pct | 0.4182 |
| trade_count | 27 |
| turnover_pct | 80.9120 |
| win_rate_pct | 59.0244 |


## Candidate Scorecards
| Candidate | Sharpe | CAGR | MaxDD | OOS Deg | WFR | Overfit | Robust |
|-----------|--------|------|-------|---------|-----|---------|--------|
| cand_6c923da9499 | 0.46 | 41.82% | 81.08% | 0.00% | 0.00% | LOW      | 0.57 |


## Walk-Forward Summary
| Candidate | WFR Pass Rate | OOS Degradation | Stability Score |
|-----------|---------------|-----------------|-----------------|
| cand_6c923da9499 | 0.00% | 0.00% | 0.40 |


## Anti-Overfit Findings
| Candidate | Overfit | Degradation | Param Sens | Year Conc | Sym Conc | Reasons |
|-----------|---------|-------------|------------|-----------|----------|--------|
| cand_6c923da9499 | no      | 0.0% | 0.000 | 0.0% | 0.0% | none |


## Validation Statistics
| Candidate | CV Method | Trials | DSR | PBO | Cost Drag | Validation Status |
|-----------|-----------|--------|-----|-----|-----------|-------------------|
| cand_6c923da9499 | unknown | 0 | N/A | N/A | N/A | partial |


## Promotion Gate Evaluation
| Candidate | Decision | Reasons | Warnings |
|-----------|----------|---------|----------|
| cand_6c923da9499 | BLOCKED                   | stale_data_manifest_binding: embedded backtest data manifest differs from the canonical persisted data manifest; data_manifest_id_mismatch: embedded=ecc00787c46eff1a governed=341bb17f28ecda64 | validation_cv_summary_missing: walk-forward evidence should declare purged/embargoed CV or CPCV metadata; validation_statistics_partial: promotion evidence is missing one or more validation statistics |


## Unified Backtest Evidence
### cand_6c923da949924d90
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
1. **Review blocked candidates** (cand_6c923da9499): Address blocking issues before re-evaluation.
4. **NOTE**: READY_FOR_PAPER_REVIEW does NOT enter paper trading. It only enters the human review pool.

