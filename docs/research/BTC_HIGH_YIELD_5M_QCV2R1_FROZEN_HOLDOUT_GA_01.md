# BTC high-yield 5m qcv2r1 frozen-holdout GA round 2

## Decision

`BTC-HIGH-YIELD-5M-QCV2R1-FROZEN-HOLDOUT-GA-01` completed its pre-registered
second genetic-search round and retained no research candidate.

- status: `complete_research_only`
- decision: `reject_selection_batch_holdout_not_revealed`
- retained candidate count: `0`
- holdout exposure after run: `preserved_unseen`
- holdout candidates revealed: `0`
- Demo strategy registration: `false`
- promotion / paper / live / private / order / real order / transfer / withdraw:
  `false`

This is a selection-stage negative result.  It is not a negative holdout result:
the program did not calculate any return, Sharpe, profit factor, cost stress, or
ledger on the frozen unseen tail.

## Pre-registration and immutable data

- authorized run HEAD: `5f21c25d98a190e9f401ed7b61e9d97bddc16fb4`
- engine code commit: `809347c507f9f1e4b94cff630f4110ee46a0d867`
- pre-registration:
  `docs/research/BTC_HIGH_YIELD_5M_QCV2R1_FROZEN_HOLDOUT_GA_01_PREREG.json`
- dataset version:
  `btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-src40741d39-main64e20af8-qc2r1`
- selector blob SHA-256:
  `b934de48d233c1f813494825c82b89ed1cd128a0ccf2e48bb28908f6967b0590`
- Git manifest SHA-256:
  `ad6981dc7c8d5124b594ff4212192e5e94ff87c965bd3e3470f247da56efa9ee`
- physical manifest SHA-256:
  `0ee09f51f53608c16c9306334c5e4fbe7ede86f948c625ba91bbd36d7f327068`
- aggregate SHA-256:
  `cfe0fe05e59e0fef4919a601926563750f94a27dfb08f84f093e6440270385f4`
- 5m file SHA-256:
  `76e8654cd11fc40b873b30d4a6fa8b2ed618256721e3b7840e180bd0f0359c08`
- total rows: `278,928`
- access mode: `immutable_shared_data_jsonl`
- public network called during run: `false`
- mutable SQLite consumed: `false`

## Frozen train, validation, and unseen holdout

Selection used only the first `248,270` completed 5m bars:

- selection start: `2024-01-01T00:00:00Z`
- prior-research cutoff / selection end: `2026-05-12T01:05:00Z`
- validation: four expanding chronological folds
- fold embargo: `5,760` bars, equal to the maximum feature lookback

The unseen tail remained outside every target build and selection simulation:

- holdout start: `2026-05-12T01:10:00Z`
- holdout end: `2026-08-26T11:55:00Z`
- holdout rows: `30,658`
- boundary from selection to holdout: contiguous 5m cadence
- used for selection: `false`
- statistically unseen before run: `true`
- revealed: `false`
- reusable for tuning: `false`

The v2 engine writes a single-candidate lock before a holdout reveal.  A reveal
is authorized only when the locked champion passes at least three of four folds
and is positive in all four.  Because this champion failed that gate, the lock
records `reveal_authorized=false` and no holdout calculation was executed.

## Frozen search budget

- seed: `20260827`
- population: `64`
- generations: `16`
- population slots this round: `1,024`
- unique genomes this round: `858`
- prior recorded population slots: `576`
- cumulative recorded population slots: `1,600`
- prior recorded unique genomes: `499`
- champion rule: maximum selection fitness, then deterministic genome-hash tie
  break
- reported / reveal-eligible candidates: exactly `1`
- gene-space SHA-256:
  `ce52675defe0744a03bb90131e0c3af88a7b40111f46954eaca5273032a32f00`
- cost-scenarios SHA-256:
  `bf8e24d5db8280f5bd68999b73600f7ff809c529fc25c9ad4684e2eab114cefb`

## Locked champion and selection result

The deterministic champion was
`btc_high_yield_5m_ga_c8a8d1440782` with genome SHA-256
`c8a8d14407827b229dba7cd85331dd64ceb1a18cd964c87cb5f3d79cf78c0dba`.

- entry / exit: `288 / 216` bars
- ATR window / multiplier: `20 / 4.0`
- breakout buffer: `0.25 ATR`
- cooldown / failed-breakout bars: `0 / 0`
- regime fast / slow: `288 / 1,152` bars
- volatility window / target: `576` bars / `120%`
- synthetic leverage cap: `2.0x`
- sticky drawdown gate: `10%`
- selection fitness: `-4.46434958`
- passed folds: `0 / 4`
- positive folds: `2 / 4`

| Fold | Total return | Profit factor | Sharpe | Max drawdown | Trades/day | Exposure | Passed |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | -8.569181% | 0.86517856 | -2.26478307 | -10.265258% | 0.13722999 | 1.702668% | false |
| 2 | -10.392123% | 0.59908118 | -4.06896633 | -10.392123% | 0.06404066 | 0.486023% | false |
| 3 | 0.858463% | 1.00907484 | 0.24789790 | -10.632652% | 0.34764930 | 6.159466% | false |
| 4 | 8.623670% | 1.06754808 | 1.19869127 | -10.523056% | 0.20125786 | 2.480783% | false |

Selection rejection reasons:

- `walk_forward_passed_folds_below_3_of_4`
- `walk_forward_positive_folds_below_4_of_4`
- `unseen_holdout_not_revealed_selection_gate_failed`

The candidate definitions file is intentionally empty.

## Immutable research artifact

External artifact root:

`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-high-yield-5m-qcv2r1-frozen-holdout-ga-01/official-5f21c25d98a1`

- semantic report artifact hash:
  `371b2dd31c10ca8659a29c2b48f8f99dd440429ea4f8da533eef966556d4869f`
- report file SHA-256:
  `c55cf2600679e508174365c7a012f74c9baef37fbcd4663b8b90f03ddd7bcfe4`
- frozen holdout lock semantic SHA-256:
  `faee8abb284e9d25bd15e6a01b0ea4dc19979943a8a64973428dbfb5c57c9de7`
- frozen holdout lock file SHA-256:
  `c41208b38193492278c6af27386be932ab3ebb27fce2af90cbdecfc9a37fbcb7`
- candidate definitions file SHA-256:
  `589007cc4fb3c8b4d740b441b7e6c55cf3a76e6f975fddff4016c32518d1a6e8`
- Chinese summary file SHA-256:
  `fc51179e1c5d295111d427292fd2b6b959f697898246a60cd1df77cf1b2e096b`

The lock file was created at `2026-08-26T21:40:16Z`; the report and candidate
files were created one second later.  The lock contains no holdout values or
metrics and records `reveal_authorized=false`.

## Interpretation and remaining blockers

The second search round confirms that this frozen 5m translation does not have
a robust walk-forward champion under its current economic structure and base
turnover cost model.  It does not justify loosening gates, selecting the
least-bad genome, or looking at the unseen tail “for diagnosis.”

The unseen tail remains available only for a materially new, pre-registered
hypothesis whose candidate is selected without that tail.  Any future work must
add its trials to the cumulative search count.

Independently of this negative result, promotion remains blocked by missing L2
spread/depth/impact, latency/queue/unfilled-order evidence, perpetual
mark/index/funding parity, liquidation replay, paper fills/positions/cash
ledger, runtime adapter, and manual review.  This artifact is research-only and
cannot unlock Demo, paper, live, private, or order permissions.
