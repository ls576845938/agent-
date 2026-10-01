# Performance Notes

## Why pandas eager loading causes CPU/Memory issues

The original `ParquetBarStore.read_bars()` loaded ALL partition files into memory
before filtering by date range:

```python
parts = [pd.read_parquet(path) for path in base.glob("date=*.parquet")]
frame = pd.concat(parts, ignore_index=True)
frame = frame[frame["timestamp_utc"] >= start]  # filter AFTER loading everything
```

For 3 years of 1d bars (~750 partitions), all 750 files were loaded even when
requesting only 5 days of data. This caused:
- CPU saturation from decompressing and parsing unused data
- Memory pressure from holding the full dataset
- VM freeze-like symptoms during concurrent test runs

## DuckDB lazy read with predicate pushdown

The new `read_bars()` method uses DuckDB when date filters are present:

```python
SELECT * FROM read_parquet('vendor=yfinance/.../date=*.parquet')
WHERE timestamp_utc >= '2024-01-01' AND timestamp_utc <= '2024-12-31'
```

DuckDB's `read_parquet()` function pushes the WHERE clause down to the parquet
row group level — only matching row groups are decompressed and read.

**Benefits:**
- Reads only the partitions/row-groups matching the date range
- Column projection reduces I/O
- Falls back gracefully to pandas if DuckDB is unavailable

## Modules that must NOT be DataFrame-converted

These modules maintain state machine logic with typed dataclasses. Do NOT
convert them to DataFrames:

- `quant_us/execution/oms.py` — Order lifecycle
- `quant_us/risk/kill_switch.py` — Risk state tracking
- `quant_us/risk/pre_trade.py` — Risk evaluation
- `quant_us/execution/ledger.py` — Ledger persistence
- `quant_us/execution/paper_broker.py` — Broker state
- `quant_us/live/shadow_live.py` — Safety gates

## FeatureStore DuckDB lazy read

`ParquetFeatureStore.read_factor_values()` now supports DuckDB lazy scans:

```python
store = ParquetFeatureStore(root=Path("data/features"))

# Eager (old) — loads all date partitions
frame = store.read_factor_values("momentum_60", "v1")

# Lazy (new) — DuckDB predicate pushdown, only matching row groups
frame = store.read_factor_values(
    "momentum_60", "v1",
    columns=["symbol", "date", "value"],
    start="2024-01-01",
    end="2024-06-30",
    use_duckdb=True,  # default
)
```

Falls back to eager pandas if DuckDB is unavailable.

## FeatureCache

`FeatureCache` provides in-memory caching for computed factors:

```python
from quant_us.data.storage.feature_store import FeatureCache

cache = FeatureCache()
frame = cache.compute_or_get("momentum_60_v1", lambda: expensive_computation())
```

## Thread limit configuration

To prevent CPU saturation during backtest runs, set these environment variables:

```bash
# Limit Polars thread pool (if using Polars)
export POLARS_MAX_THREADS=2

# Limit OpenMP threads (numpy, scipy)
export OMP_NUM_THREADS=2

# Limit MKL threads (Intel Math Kernel Library)
export MKL_NUM_THREADS=2

# Limit NumExpr threads (pandas eval)
export NUMEXPR_NUM_THREADS=2

# Limit DuckDB threads
export DUCKDB_THREADS=2
```

For a 4-core VM, set all to 2 to leave headroom for OS and other processes.
For a 2-core VM, set all to 1.

Add these to your shell profile or `.env` file:

```bash
# .env
POLARS_MAX_THREADS=2
OMP_NUM_THREADS=2
MKL_NUM_THREADS=2
NUMEXPR_NUM_THREADS=2
```

## Benchmarking

To compare pandas vs DuckDB read performance:

```python
from pathlib import Path
from datetime import datetime, timezone
from quant_us.data.storage.parquet_store import ParquetBarStore

store = ParquetBarStore(root=Path("data") / "cleaned")

# Test: read 1 year of 1d bars for AAPL
start = datetime(2024, 1, 1, tzinfo=timezone.utc)
end = datetime(2024, 12, 31, tzinfo=timezone.utc)

# Triggers DuckDB lazy read (predicate pushdown)
frame = store.read_bars(
    vendor="yfinance", asset_class="equity",
    bar_size="1d", symbol="AAPL",
    start=start, end=end,
)
print(f"Rows: {len(frame)}, Columns: {list(frame.columns)}")
```
