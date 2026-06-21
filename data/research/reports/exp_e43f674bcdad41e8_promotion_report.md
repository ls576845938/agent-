# Research Report v2: exp_e43f674bcdad41e8

**Strategy:** trend_momentum  
**Status:** PROMOTED_TO_CANDIDATE  
**Created:** 2026-05-11T02:49:33.335433+00:00  
**Symbols:** SPY  


## Experiment Summary
| Field | Value |
|-------|-------|
| Experiment ID | exp_e43f674bcdad41e8 |
| Strategy Family | walk_forward_momentum_research_smoke |
| Data Version | qs-yfinance-SPY-1d-268b4e155ee3 |
| Date Range | 2024-01-01 -> 2024-07-01 |
| Cost Model | default |
| Walk Forward Config | {"fold": "2024-01-01", "period": "2024-01-01_2024-07-01"} |

### Metrics

| Metric | Value |
|--------|-------|
| annual_return_pct | 1.0271 |
| annual_volatility_pct | 0.8108 |
| backtest_manifest_id | ubt_3ce66d0d7fa34b89 |
| backtest_manifest_path | data/manifests/run_ubt_3ce66d0d7fa34b89.json |
| baseline_fill_count | 12 |
| baseline_order_count | 12 |
| cagr_pct | 1.0271 |
| calmar_ratio | 2.1262 |
| canonical_for_promotion | True |
| cost_model | default |
| data_manifest_exists | True |
| data_manifest_path | data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json |
| data_version | qs-yfinance-SPY-1d-268b4e155ee3 |
| engine | event_driven |
| fills_hash | 0f20718dc7e35cfb02557126c7501a031af962076df1fbbda8167b3a7c8a06bc |
| ledger_artifact_hash | 45743ababb228f562936d6b1b432cb25b35d0638919e4110aa611477fa1811ad |
| ledger_artifact_path | data/manifests/reconciliation/ledger_recon_artifact_45743ababb228f56.json |
| ledger_consistency_pct | 100.0000 |
| ledger_hash | f0acd251e4355163bb69435f59a99d0bf1995935432a0191158e83aeb56a279d |
| max_drawdown_pct | -0.4830 |
| missing_data_manifest | False |
| orders_hash | 3b2b607631237051b9a2fc502362faf080d129ff3b69569569e3a39e0d8b7a91 |
| profit_factor | 1.3016 |
| sharpe_ratio | 1.2644 |
| slippage_model | default |
| sortino_ratio | 1.5633 |
| total_fill_count | 12 |
| total_order_count | 12 |
| total_return_pct | 0.5041 |
| trade_count | 12 |
| turnover_pct | 30.4083 |
| win_rate_pct | 58.4158 |


## Candidate Scorecards
| Candidate | Sharpe | CAGR | MaxDD | OOS Deg | WFR | Overfit | Robust |
|-----------|--------|------|-------|---------|-----|---------|--------|
| cand_60f059c12a4 | 1.26 | 50.41% | 48.30% | 0.00% | 0.00% | LOW      | 0.61 |


## Walk-Forward Summary
| Candidate | WFR Pass Rate | OOS Degradation | Stability Score |
|-----------|---------------|-----------------|-----------------|
| cand_60f059c12a4 | 0.00% | 0.00% | 0.40 |


## Anti-Overfit Findings
| Candidate | Overfit | Degradation | Param Sens | Year Conc | Sym Conc | Reasons |
|-----------|---------|-------------|------------|-----------|----------|--------|
| cand_60f059c12a4 | no      | 0.0% | 0.000 | 0.0% | 0.0% | none |


## Validation Statistics
| Candidate | CV Method | Trials | DSR | PBO | Cost Drag | Validation Status |
|-----------|-----------|--------|-----|-----|-----------|-------------------|
| cand_60f059c12a4 | unknown | 0 | N/A | N/A | N/A | partial |


## Promotion Gate Evaluation
| Candidate | Decision | Reasons | Warnings |
|-----------|----------|---------|----------|
| cand_60f059c12a4 | BLOCKED                   | stale_data_manifest_binding: embedded backtest data manifest differs from the canonical persisted data manifest; data_manifest_id_mismatch: embedded=ecc00787c46eff1a governed=341bb17f28ecda64 | validation_cv_summary_missing: walk-forward evidence should declare purged/embargoed CV or CPCV metadata; validation_statistics_partial: promotion evidence is missing one or more validation statistics |


## Unified Backtest Evidence
### cand_60f059c12a494fee
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
1. **Review blocked candidates** (cand_60f059c12a4): Address blocking issues before re-evaluation.
4. **NOTE**: READY_FOR_PAPER_REVIEW does NOT enter paper trading. It only enters the human review pool.

