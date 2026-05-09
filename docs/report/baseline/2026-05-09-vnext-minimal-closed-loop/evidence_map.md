# Evidence Map

This map ties each baseline slice to the current documentation and inspection surface.

| Slice | Evidence Sources | How to Inspect |
|------|------------------|----------------|
| `doc-contract` | `README.md`, `docs/VNEXT_MINIMAL_CLOSED_LOOP.md`, `docs/report/cli_report_commands.md` | Read the top-level quick start and the minimal closed-loop boundary text |
| `data-manifest` | `docs/VNEXT_MINIMAL_CLOSED_LOOP.md`, `docs/report/evidence_registry.md` | Check manifest creation and manifest registry language |
| `unified-backtest-evidence` | `docs/VNEXT_MINIMAL_CLOSED_LOOP.md`, `docs/report/cli_report_commands.md` | Use `python -m quant_us.cli report backtest ...` against persisted evidence |
| `research-gate-canonical-evidence` | `docs/VNEXT_MINIMAL_CLOSED_LOOP.md`, `docs/report/cli_report_commands.md`, `docs/report/evidence_registry.md` | Inspect the promotion gate language and the canonical evidence description |
| `paper-runtime-fail-closed` | `docs/VNEXT_MINIMAL_CLOSED_LOOP.md`, `README.md`, `docs/report/cli_report_commands.md` | Confirm the text says paper runtime is a boundary and that real Alpaca paper is not wired |
| `surface-alignment` | `README.md`, `docs/VNEXT_MINIMAL_CLOSED_LOOP.md`, `docs/report/cli_report_commands.md` | Confirm the same boundary language appears across entry points |

## Evidence Principles

- Prefer persisted evidence and boundary docs over runtime assumptions.
- Treat report commands as inspection tools only.
- Do not use this map to imply automatic paper or live execution.
