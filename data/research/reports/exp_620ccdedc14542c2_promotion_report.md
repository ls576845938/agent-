# Research Report v2: exp_620ccdedc14542c2

**Strategy:** trend_momentum  
**Status:** PROMOTED_TO_CANDIDATE  
**Created:** 2026-05-11T02:49:31.954412+00:00  
**Symbols:** SPY  


## Experiment Summary
| Field | Value |
|-------|-------|
| Experiment ID | exp_620ccdedc14542c2 |
| Strategy Family | momentum_research_smoke |
| Data Version | qs-yfinance-SPY-1d-268b4e155ee3 |
| Date Range | 2024-01-01 -> 2024-12-31 |
| Cost Model | default |
| Walk Forward Config | {} |

### Metrics

| Metric | Value |
|--------|-------|
| annual_return_pct | 0.6544 |
| annual_volatility_pct | 0.8143 |
| backtest_manifest_id | ubt_3898d790b9514a07 |
| backtest_manifest_path | data/manifests/run_ubt_3898d790b9514a07.json |
| baseline_fill_count | 28 |
| baseline_order_count | 28 |
| cagr_pct | 0.6544 |
| calmar_ratio | 1.1276 |
| canonical_for_promotion | True |
| cost_model | default |
| cost_sensitivity | 0.1628 |
| cost_stress_levels | [{'total_return_pct': 0.4182, 'cagr_pct': 0.4199, 'annual_return_pct': 0.4199, 'annual_volatility_pct': 0.9184, 'sharpe_ratio': 0.4608, 'sortino_ratio': 0.4631, 'max_drawdown_pct': -0.8108, 'calmar_ratio': 0.5179, 'win_rate_pct': 59.0244, 'profit_factor': 1.1034, 'turnover_pct': 80.912, 'trade_count': 27, 'engine': 'event_driven', 'canonical_for_promotion': True, 'backtest_manifest_path': 'data/manifests/run_ubt_197f367ff9684369.json', 'backtest_manifest_id': 'ubt_197f367ff9684369', 'ledger_artifact_path': 'data/manifests/reconciliation/ledger_recon_artifact_be45421ecee3c29b.json', 'ledger_artifact_hash': 'be45421ecee3c29b6a5e313c8bc50be499217cdf33207c1c36dc19138b2f0cbb', 'ledger_hash': 'd4f9d61c517d91c23b717d93b09073ae001910badc411a5a0ac03ac711aefb6f', 'fills_hash': 'fc8b49b9a3684851343856e7cd2353ab3870121e732be7bb8618a5e04420b24c', 'orders_hash': 'f3a87bab00dd46c0da82b6d4f48ce4b6961352c06a486cb853d0c8825605c219', 'data_manifest_path': 'data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json', 'data_manifest_exists': True, 'missing_data_manifest': False, 'data_version': 'qs-yfinance-SPY-1d-268b4e155ee3', 'cost_model': 'high', 'slippage_model': 'high', 'ledger_consistency_pct': 100.0, 'total_order_count': 27, 'total_fill_count': 27, 'baseline_order_count': 27, 'baseline_fill_count': 27, 'experiment_id': 'exp_e22e6ad04f774d14'}, {'total_return_pct': 0.4995, 'cagr_pct': 0.5015, 'annual_return_pct': 0.5015, 'annual_volatility_pct': 0.9181, 'sharpe_ratio': 0.5495, 'sortino_ratio': 0.5447, 'max_drawdown_pct': -0.7908, 'calmar_ratio': 0.6342, 'win_rate_pct': 58.5106, 'profit_factor': 1.1247, 'turnover_pct': 80.9119, 'trade_count': 27, 'engine': 'event_driven', 'canonical_for_promotion': True, 'backtest_manifest_path': 'data/manifests/run_ubt_4ec815ef36364725.json', 'backtest_manifest_id': 'ubt_4ec815ef36364725', 'ledger_artifact_path': 'data/manifests/reconciliation/ledger_recon_artifact_bdc2f48a947c5821.json', 'ledger_artifact_hash': 'bdc2f48a947c5821bda2d59290e628ef4fb6d30a9319694578a2699232f8c426', 'ledger_hash': 'f899a5abf3c9d39a820786ed7c94577f27b937e684b2e04423652c46fea1b4c9', 'fills_hash': 'e5a29120a25ad6094e0f2bf4b13a5c7ab72337eecde1b3f7c7f03322ff6151fb', 'orders_hash': 'ed43ff895730d6f93caac2be39d1d23f4e73a70a1fcf6c4d1ceec2eb76bc8bd7', 'data_manifest_path': 'data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json', 'data_manifest_exists': True, 'missing_data_manifest': False, 'data_version': 'qs-yfinance-SPY-1d-268b4e155ee3', 'cost_model': 'low', 'slippage_model': 'low', 'ledger_consistency_pct': 100.0, 'total_order_count': 27, 'total_fill_count': 27, 'baseline_order_count': 27, 'baseline_fill_count': 27, 'experiment_id': 'exp_8a9c08aac46c4994'}] |
| data_manifest_exists | True |
| data_manifest_path | data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json |
| data_version | qs-yfinance-SPY-1d-268b4e155ee3 |
| engine | event_driven |
| fills_hash | 07be93bb7fcfd54454b738a513ff2d3144d7e57084c5b47e46b1aff8cdb46d47 |
| ledger_artifact_hash | d6861149a7df794be1a28c20367615763e019a1cadb9c8bd1d359dbffb65f6fc |
| ledger_artifact_path | data/manifests/reconciliation/ledger_recon_artifact_d6861149a7df794b.json |
| ledger_consistency_pct | 100.0000 |
| ledger_hash | 0f26be4d7ba01d28b8b536a0fd68b2624f85c6d4ebb599334bbb9b8865b0d048 |
| max_drawdown_pct | -0.5804 |
| missing_data_manifest | False |
| oos_degradation | 0.4756 |
| orders_hash | 31184a4002085283377f5c0c505e0398da296c46354019928167920782242249 |
| out_of_sample_sharpe | 0.6630 |
| profit_factor | 1.1937 |
| sharpe_ratio | 0.8051 |
| slippage_model | default |
| sortino_ratio | 0.7839 |
| stress_survival_rate | 0.0000 |
| total_fill_count | 28 |
| total_order_count | 28 |
| total_return_pct | 0.6518 |
| trade_count | 28 |
| turnover_pct | 140.6800 |
| walk_forward_pass_rate | 0.0000 |
| wf_fold_drawdowns | [0.483, 0.4682] |
| wf_fold_results | [{'total_return_pct': 0.5041, 'cagr_pct': 1.0271, 'annual_return_pct': 1.0271, 'annual_volatility_pct': 0.8108, 'sharpe_ratio': 1.2644, 'sortino_ratio': 1.5633, 'max_drawdown_pct': -0.483, 'calmar_ratio': 2.1262, 'win_rate_pct': 58.4158, 'profit_factor': 1.3016, 'turnover_pct': 30.4083, 'trade_count': 12, 'engine': 'event_driven', 'canonical_for_promotion': True, 'backtest_manifest_path': 'data/manifests/run_ubt_3ce66d0d7fa34b89.json', 'backtest_manifest_id': 'ubt_3ce66d0d7fa34b89', 'ledger_artifact_path': 'data/manifests/reconciliation/ledger_recon_artifact_45743ababb228f56.json', 'ledger_artifact_hash': '45743ababb228f562936d6b1b432cb25b35d0638919e4110aa611477fa1811ad', 'ledger_hash': 'f0acd251e4355163bb69435f59a99d0bf1995935432a0191158e83aeb56a279d', 'fills_hash': '0f20718dc7e35cfb02557126c7501a031af962076df1fbbda8167b3a7c8a06bc', 'orders_hash': '3b2b607631237051b9a2fc502362faf080d129ff3b69569569e3a39e0d8b7a91', 'data_manifest_path': 'data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json', 'data_manifest_exists': True, 'missing_data_manifest': False, 'data_version': 'qs-yfinance-SPY-1d-268b4e155ee3', 'cost_model': 'default', 'slippage_model': 'default', 'ledger_consistency_pct': 100.0, 'total_order_count': 12, 'total_fill_count': 12, 'baseline_order_count': 12, 'baseline_fill_count': 12, 'experiment_id': 'exp_e43f674bcdad41e8', 'period': {'fold': '2024-01-01', 'period': '2024-01-01_2024-07-01'}}, {'total_return_pct': 0.0253, 'cagr_pct': 0.0502, 'annual_return_pct': 0.0502, 'annual_volatility_pct': 0.8774, 'sharpe_ratio': 0.0616, 'sortino_ratio': 0.0485, 'max_drawdown_pct': -0.4682, 'calmar_ratio': 0.1072, 'win_rate_pct': 56.25, 'profit_factor': 1.0155, 'turnover_pct': 40.3773, 'trade_count': 11, 'engine': 'event_driven', 'canonical_for_promotion': True, 'backtest_manifest_path': 'data/manifests/run_ubt_56bba64c059e4f86.json', 'backtest_manifest_id': 'ubt_56bba64c059e4f86', 'ledger_artifact_path': 'data/manifests/reconciliation/ledger_recon_artifact_b0698637d2c2f8c6.json', 'ledger_artifact_hash': 'b0698637d2c2f8c629a8a517f4b44b105b9dfa394d4e50ecd13eae162476015a', 'ledger_hash': '01fd22659bfc8ef60ad40cff54ff6495135c8bab9dbe7fbcc7868da7e4cc75bc', 'fills_hash': '74ea6f431e01cf199d7a529cb44a2fb6a7f326590c87774f82c135c648928b01', 'orders_hash': 'f762735f2cd061918b5a104f930fc3b4d34eb71234de697b64e985fb0d14c83a', 'data_manifest_path': 'data/manifests/qs-yfinance-SPY-1d-268b4e155ee3.json', 'data_manifest_exists': True, 'missing_data_manifest': False, 'data_version': 'qs-yfinance-SPY-1d-268b4e155ee3', 'cost_model': 'default', 'slippage_model': 'default', 'ledger_consistency_pct': 100.0, 'total_order_count': 11, 'total_fill_count': 11, 'baseline_order_count': 11, 'baseline_fill_count': 11, 'experiment_id': 'exp_12b8cf3532fc465b', 'period': {'fold': '2024-07-01', 'period': '2024-07-01_2024-12-31'}}] |
| wf_fold_returns | [0.5041, 0.0253] |
| wf_fold_sharpes | [1.2644, 0.0616] |
| wf_fold_trade_counts | [12, 11] |
| win_rate_pct | 57.7381 |


## Candidate Scorecards
| Candidate | Sharpe | CAGR | MaxDD | OOS Deg | WFR | Overfit | Robust |
|-----------|--------|------|-------|---------|-----|---------|--------|
| cand_fdfa9b95233 | 0.81 | 65.18% | 58.04% | 47.56% | 0.00% | LOW      | 0.48 |


## Walk-Forward Summary
| Candidate | WFR Pass Rate | OOS Degradation | Stability Score |
|-----------|---------------|-----------------|-----------------|
| cand_fdfa9b95233 | 0.00% | 47.56% | 0.21 |


## Anti-Overfit Findings
| Candidate | Overfit | Degradation | Param Sens | Year Conc | Sym Conc | Reasons |
|-----------|---------|-------------|------------|-----------|----------|--------|
| cand_fdfa9b95233 | no      | 0.0% | 0.000 | 0.0% | 0.0% | none |


## Validation Statistics
| Candidate | CV Method | Trials | DSR | PBO | Cost Drag | Validation Status |
|-----------|-----------|--------|-----|-----|-----------|-------------------|
| cand_fdfa9b95233 | unknown | 4 | 0.395 | N/A | N/A | partial |


## Promotion Gate Evaluation
| Candidate | Decision | Reasons | Warnings |
|-----------|----------|---------|----------|
| cand_fdfa9b95233 | BLOCKED                   | stale_data_manifest_binding: embedded backtest data manifest differs from the canonical persisted data manifest; data_manifest_id_mismatch: embedded=ecc00787c46eff1a governed=341bb17f28ecda64 | validation_cv_summary_missing: walk-forward evidence should declare purged/embargoed CV or CPCV metadata; validation_statistics_partial: promotion evidence is missing one or more validation statistics |


## Unified Backtest Evidence
### cand_fdfa9b95233d4b45
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
1. **Review blocked candidates** (cand_fdfa9b95233): Address blocking issues before re-evaluation.
4. **NOTE**: READY_FOR_PAPER_REVIEW does NOT enter paper trading. It only enters the human review pool.

