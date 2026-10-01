# BTC 5m high-yield Donchian genetic search

## Decision

`BTC-HIGH-YIELD-5M-GA-MINING-01` completed one frozen genetic-search round and retained no research candidate.

- status: `complete_research_only`
- decision: `reject_current_high_yield_5m_search_batch`
- retained candidate count: `0`
- Demo strategy registration: `false`
- paper / live / private / order / real order / transfer / withdraw: `false`

This is a useful negative result. It does not establish that no viable 5m strategy exists; it establishes that the frozen translation and search space below did not survive the required cross-period and cost gates on this immutable data version.

## Origin contract

The starting point is the repository's identity-only `high_yield_donchian_v2` research candidate:

- candidate: `hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff`
- base strategy: `formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone`
- original timeframe: `completed_1h_to_4h`
- inherited economic structure: completed-bar Donchian breakout, slower trend permission, ATR protection, cooldown, volatility targeting, capped synthetic leverage and a sticky drawdown gate
- explicitly not inherited: the historical "10,000x" label, any return claim, promotion status, runtime adapter, paper or live permission

The 5m translation searches economically meaningful durations rather than dividing all original bar counts mechanically. The genome covers 2--24 hour entry channels, shorter exit channels, ATR windows and multipliers, failure-breakout delays, breakout buffers, completed 5m regime averages spanning roughly 1--20 days, volatility windows, 40%--120% target volatility, 1.0x--2.5x synthetic leverage caps and 10%--25% sticky drawdown gates.

Signals use only a completed bar. Position changes are executed at the next bar open. PnL is reconstructed from normalized fills, positions and cash; no strategy code calls a broker or exchange.

## Frozen search and validation

- seed: `20260826`
- population: `48`
- generations: `12`
- population slots: `576`
- unique genomes evaluated: `499`
- selection: deterministic tournament with elitism
- validation: four expanding chronological folds
- embargo: `5760` 5m bars, equal to the maximum feature lookback
- diagnostic tail: final 20%, excluded from genetic fitness
- cost scenarios per unit turnover: base `10.0 bps`, conservative `16.5 bps`, stress `30.0 bps`
- retained-output limit: `8`, but only candidates passing every frozen gate may be emitted

The project had already viewed the same post-November-2025 tail in earlier intraday research. It is therefore diagnostic only, is not promotion-eligible, and cannot be relabelled as unseen holdout evidence. Any follow-up confirmation requires an immutable data version after `2026-05-12T09:05:00+08:00` that has not been used for engine or parameter decisions.

## Data evidence

- manifest: `data/manifests/qs-sqlite-BTCUSDT-5m-20240101T000000-bd0200707eb9.json`
- data version: `qs-sqlite-BTCUSDT-5m-20240101T000000-bd0200707eb9`
- source / universe: SQLite / `binance_spot:BTCUSDT`
- interval: `5m`
- rows: `248270`
- range: `2024-01-01T08:00:00+08:00` through `2026-05-12T09:05:00+08:00`
- invalid OHLCV rows: `0`
- irregular time steps: `0`
- manifest checksum: `bd0200707eb9f595decb7b6122b88cdc87d97b95992f01c5e5afa61c53530374`
- resolved slice SHA-256: `ed290963dae286cdbad45ca86868ed07af91f785595e4f6a98c1a5ea4c59894a`
- access mode: SQLite URI read-only plus `PRAGMA query_only=1`

## Result

The best selection-fitness genome was `btc_high_yield_5m_ga_020ed18094a7`:

- entry / exit: `288 / 216` bars
- ATR: window `20`, multiplier `4.0`
- breakout buffer: `0.5 ATR`
- cooldown: `48` bars
- regime averages: `1440 / 5760` bars
- volatility window / target: `2016` bars / `60%`
- leverage cap / drawdown gate: `1.5x / 10%`
- walk-forward: only `1/4` folds passed and only `1/4` was positive
- diagnostic tail, base cost: total return `-7.923711%`, profit factor `0.87207944`, Sharpe `-1.93063013`, max drawdown `-10.280420%`, `0.13920329` trades/day
- diagnostic tail, conservative cost: total return `-8.392056%`, profit factor `0.85954856`
- diagnostic tail, stress cost: total return `-9.289871%`, profit factor `0.82777145`
- diagnostic tail observed only the short side for this genome
- base-cost ledger: `759` fills; ending equity `0.92076289`; reconciliation `true`
- normalized ledger SHA-256: `bc6a625e14049c64dff50988d18f2b0b57011df7293122483b74c0e1e19a66f1`

The top eight genomes all failed the frozen gates. Candidate definitions are therefore intentionally empty.

## Immutable research artifact

- source commit: `18939f455db2424d9f267ad26b5396d6e8767179`
- external artifact root: `D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-high-yield-5m-ga-mining-01/official-18939f455`
- semantic artifact hash: `f6e81efe42b600c8806b05b39294f9d8347b9cca71539d8db2c9eec14599a4f8`
- report file SHA-256: `1c1d61521ac3e2f316190fc4aa2d720472091ffa4f5c3768fc35488939e0d611`
- candidate-definitions file SHA-256: `0dd7e7a7afa8ccdf82ffbc84c88cf5c2010a6404cb3901ef17f448192af984b3`
- Chinese-summary file SHA-256: `dd73a869be84249ab478ffb6ece015bb6d21be3f53fb6d87b6822d1b793ad8ee`

The full research ledger is not committed because of its size; the artifact commits its model, hashes, row counts and samples. This is sufficient to audit this research calculation, but it is not paper fill/position/cash observation.

## Remaining blockers

- no candidate passed the frozen walk-forward and diagnostic gates
- future unseen immutable data is required because the shared tail was previously exposed
- L2 spread, depth, market impact, latency, queue and unfilled-order evidence is absent
- perpetual mark/index/funding parity and liquidation replay are absent
- paper fills, positions and cash-ledger observation are absent
- no runtime adapter was generated
- manual promotion review has not started

The next valid step is not to loosen these thresholds or register the least-bad genome. A new hypothesis or structure may be researched on the selection range, but confirmation must wait for genuinely unseen data and must preserve the fail-closed execution, ledger and promotion boundaries.
