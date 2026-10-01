# BTC-V3-GATE-SNAPSHOT-WINDOWS-ATOMICITY-01

## Classification

- Category: `engineering`
- Owner: `btc_developer`
- Found by: `BTC-V3-FINAL-PAPER-READINESS-01`
- Gate impact: `blocks_gate`

## Reproduction

The final 13-module Windows BTC regression observed:

```text
tests/contracts/test_btc_gate_snapshot.py::
test_concurrent_snapshot_publishers_never_create_a_mixed_batch
PermissionError: [WinError 5]
os.replace(<unique temp>, artifacts/btc_gate_runs/latest_pointer.json)
```

The isolated test passed on one immediate diagnostic rerun, so the failure is
nondeterministic. The full-suite failure remains valid evidence that the
current Windows atomic-publish contract is not reliable under contention.

## Required repair

Make latest-pointer publication deterministic on Windows while preserving
the unique writer lock, immutable per-run manifests, no mixed batches and
atomic fail-closed pointer semantics. Do not weaken the concurrency test.

## Acceptance

- Repeated concurrent-publisher stress runs pass on Windows.
- Readers never observe a mixed batch or partial JSON.
- A failed publish cannot advance the latest pointer.
- Paper/private/order/live flags remain false.

## Resolution

- Status: `retired_engineering_blocker`
- Goal: `BTC-V3-ENGINEERING-BLOCKER-CLOSURE-01`
- Latest-pointer replacement is serialized by a pointer-specific
  single-writer lock, separate from the whole-builder lock.
- Windows transient `WinError 5`/sharing violations use a bounded retry around
  the final atomic `os.replace`; exhaustion raises and leaves the old pointer
  unchanged.
- Immutable per-run manifests remain separate and no rejected or failed
  publication advances the pointer.
- The strengthened concurrency contract ran 12 publisher pairs per test and
  passed five additional repeated Windows stress invocations. Failure
  injection confirmed that the previous valid batch remains readable.
