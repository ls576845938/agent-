# Research Report v2: exp_12b8cf3532fc465b

**Strategy:** trend_momentum  
**Status:** PROMOTED_TO_CANDIDATE  
**Created:** 2026-05-11T02:49:33.528996+00:00  
**Symbols:** SPY  


## Experiment Summary
| Field | Value |
|-------|-------|
| Experiment ID | exp_12b8cf3532fc465b |
| Strategy Family | walk_forward_momentum_research_smoke |
| Data Version | qs-yfinance-SPY-1d-268b4e155ee3 |
| Date Range | 2024-07-01 -> 2024-12-31 |
| Cost Model | default |
| Walk Forward Config | {"fold": "2024-07-01", "period": "2024-07-01_2024-12-31"} |

### Metrics

| Metric | Value |
|--------|-------|
| annual_return_pct | 0.0502 |
| annual_volatility_pct | 0.8774 |
| backtest_manifest_id | ubt_56bba64c059e4f86 |
| backtest_manifest_path | data/manifests/run_ubt_56bba64c059e4f86.json |
| baseline_fill_count | 11 |
| baseline_order_count | 11 |
| cagr_pct | 0.0502 |
| calmar_ratio | 0.1072 |
| canonical_for_promotion | True |
| cost_model | default |
| data_manifest_exists | True |
| data_manifest_path | data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json |
| data_version | qs-yfinance-SPY-1d-268b4e155ee3 |
| engine | event_driven |
| fills_hash | 74ea6f431e01cf199d7a529cb44a2fb6a7f326590c87774f82c135c648928b01 |
| ledger_artifact_hash | b0698637d2c2f8c629a8a517f4b44b105b9dfa394d4e50ecd13eae162476015a |
| ledger_artifact_path | data/manifests/reconciliation/ledger_recon_artifact_b0698637d2c2f8c6.json |
| ledger_consistency_pct | 100.0000 |
| ledger_hash | 01fd22659bfc8ef60ad40cff54ff6495135c8bab9dbe7fbcc7868da7e4cc75bc |
| max_drawdown_pct | -0.4682 |
| missing_data_manifest | False |
| orders_hash | f762735f2cd061918b5a104f930fc3b4d34eb71234de697b64e985fb0d14c83a |
| profit_factor | 1.0155 |
| sharpe_ratio | 0.0616 |
| slippage_model | default |
| sortino_ratio | 0.0485 |
| total_fill_count | 11 |
| total_order_count | 11 |
| total_return_pct | 0.0253 |
| trade_count | 11 |
| turnover_pct | 40.3773 |
| win_rate_pct | 56.2500 |


## Candidate Scorecards
| Candidate | Sharpe | CAGR | MaxDD | OOS Deg | WFR | Overfit | Robust |
|-----------|--------|------|-------|---------|-----|---------|--------|
| cand_b8a622079a1 | 0.06 | 2.53% | 46.82% | 0.00% | 0.00% | LOW      | 0.43 |


## Walk-Forward Summary
| Candidate | WFR Pass Rate | OOS Degradation | Stability Score |
|-----------|---------------|-----------------|-----------------|
| cand_b8a622079a1 | 0.00% | 0.00% | 0.40 |


## Anti-Overfit Findings
| Candidate | Overfit | Degradation | Param Sens | Year Conc | Sym Conc | Reasons |
|-----------|---------|-------------|------------|-----------|----------|--------|
| cand_b8a622079a1 | no      | 0.0% | 0.000 | 0.0% | 0.0% | none |


## Validation Statistics
| Candidate | CV Method | Trials | DSR | PBO | Cost Drag | Validation Status |
|-----------|-----------|--------|-----|-----|-----------|-------------------|
| cand_b8a622079a1 | unknown | 0 | N/A | N/A | N/A | partial |


## Promotion Gate Evaluation
| Candidate | Decision | Reasons | Warnings |
|-----------|----------|---------|----------|
| cand_b8a622079a1 | BLOCKED                   | stale_data_manifest_binding: embedded backtest data manifest differs from the canonical persisted data manifest; data_manifest_id_mismatch: embedded=ecc00787c46eff1a governed=341bb17f28ecda64 | validation_cv_summary_missing: walk-forward evidence should declare purged/embargoed CV or CPCV metadata; validation_statistics_partial: promotion evidence is missing one or more validation statistics |


## Unified Backtest Evidence
### cand_b8a622079a184b30
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
1. **Review blocked candidates** (cand_b8a622079a1): Address blocking issues before re-evaluation.
4. **NOTE**: READY_FOR_PAPER_REVIEW does NOT enter paper trading. It only enters the human review pool.

