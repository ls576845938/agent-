# BTC Derivatives Sentiment Data Plan

## Scope

This plan wires CoinGlass-like derivatives data into the BTC data layer without unlocking paper or live trading.

Target source roles:

- `open_interest_1h`
- `funding_rate`
- `liquidation_1h`
- `long_short_ratio_1h`
- `derivatives_sentiment_1h`

## Required Fields

Every row must keep the same point-in-time boundary as other BTC data:

- `event_time`
- `available_time`
- `ingested_at`
- `processed_at`
- `venue`
- `symbol`
- `source_provider`
- `is_final`
- `source_raw_payload_hash`

Feature fields:

- `open_interest_usd`
- `funding_rate`
- `long_liquidation_usd`
- `short_liquidation_usd`
- `long_short_ratio`

## Current Implementation

The first-stage contract lives in:

- `quant_crypto/data/derivatives_sentiment.py`
- `scripts/build_btc_derivatives_sentiment_report.py`
- `tests/contracts/test_btc_derivatives_sentiment_report.py`

It builds:

- PIT and finalization checks.
- Role coverage checks for OI, funding, liquidation, and long/short ratio.
- A `crowding_score` feature.
- Risk states: `normal`, `crowded`, `crowded_long_risk`, `crowded_short_risk`, `liquidation_shock`, `blocked`.

The report is blocked until enough real history is present. This is intentional: a short sample can validate schema and pipeline mechanics, but it cannot support strategy alpha claims.

## Operator Command

Generate a local sample diagnostic:

```powershell
python scripts/build_btc_derivatives_sentiment_report.py --write-sample
```

Build against a real redacted/local vendor export:

```powershell
python scripts/build_btc_derivatives_sentiment_report.py --rows <local-derivatives-sentiment-export.json>
```

Do not store API keys or account identifiers in this file. Vendor data exports must be raw market data only.

## Free Public Source Plan

Before buying a paid vendor, build the free-source plan:

```powershell
python scripts/build_btc_free_derivatives_source_report.py
```

This uses public market-data endpoints only and defaults to dry-run planning. The initial free-source coverage is:

- Binance USD-M: funding, open interest, open-interest history, global/top long-short ratios, taker long-short flow, recent force orders.
- OKX swap: funding history, open interest, liquidation orders.
- Bybit: funding history, open interest, public liquidation WebSocket subscription plan.
- CoinGecko: derivatives and derivative exchange cross-checks.

Network execution is opt-in:

```powershell
python scripts/build_btc_free_derivatives_source_report.py --execute-network
```

The report never unlocks a strategy gate by itself. It only proves the free public sources are reachable or planned. The normalized derivatives sentiment gate still requires enough finalized, PIT-safe history.
