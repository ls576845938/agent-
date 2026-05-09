# Change Slices

These are the current recommended documentation slices for the P0 baseline.

| Slice | Purpose | Notes |
|------|---------|-------|
| `doc-contract` | Align README, CLI report commands, and boundary docs on the same language | Prevents drift between user-facing docs and report docs |
| `data-manifest` | Describe manifest creation, validation, and traceability | Keeps data correctness first |
| `unified-backtest-evidence` | Document the persisted backtest evidence surface | Focuses on ledger-backed, event-driven backtests |
| `research-gate-canonical-evidence` | Document canonical evidence required for promotion | Keeps promotion evidence explicit and read-only |
| `paper-runtime-fail-closed` | State the current paper runtime boundary | Real Alpaca paper is not yet integrated |
| `surface-alignment` | Make the README, CLI help, and boundary docs consistent | Reduces confusion about what is present versus planned |

## Recommended Order

1. `doc-contract`
2. `data-manifest`
3. `unified-backtest-evidence`
4. `research-gate-canonical-evidence`
5. `paper-runtime-fail-closed`
6. `surface-alignment`

## Expected Outcome

The docs should let a reader answer three questions without guessing:

- what is currently present
- what is only a gate or boundary
- what is still missing
