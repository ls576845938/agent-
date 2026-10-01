# Acceptance Checklist

## Baseline Acceptance

- [ ] README quick start includes the full test command with `PYTHONPATH=.`
- [ ] README states that real Alpaca paper is not yet integrated
- [ ] README does not claim automatic paper or live trading
- [ ] `docs/VNEXT_MINIMAL_CLOSED_LOOP.md` states promotion is not execution
- [ ] `docs/VNEXT_MINIMAL_CLOSED_LOOP.md` states the baseline scope only covers current boundary items
- [ ] `docs/report/cli_report_commands.md` remains read-only and report-oriented
- [ ] The baseline directory contains `scope.md`
- [ ] The baseline directory contains `change_slices.md`
- [ ] The baseline directory contains `verification.md`
- [ ] The baseline directory contains `evidence_map.md`
- [ ] The baseline directory contains `known_gaps.md`
- [ ] The baseline directory contains `acceptance_checklist.md`

## Boundary Acceptance

- [ ] Real Alpaca paper stays fail-closed
- [ ] Paper/live are not described as automatic
- [ ] Current docs separate evidence inspection from execution
- [ ] The baseline mentions the current slice set:
  - `doc-contract`
  - `data-manifest`
  - `unified-backtest-evidence`
  - `research-gate-canonical-evidence`
  - `paper-runtime-fail-closed`
  - `surface-alignment`
