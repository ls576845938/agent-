# US-V3-PAPER-DURABLE-PATH-ASSERTION-DRIFT-01

## Status

`open`; owner: `paper_runtime`; gate impact:
`blocks_final_paper_readiness`.

This ticket is an independent follow-up discovered and reproduced during
`US-V3-FINAL-PAPER-READINESS-01`. The final readiness review does not modify
paper runtime business code.

## Current-main reproduction

- Base/current main reviewed:
  `78f3e07bfb5f13431d91ce2526aed00fad70f9e3`.
- Exact validator:
  `backend/tests/test_paper_runtime.py::TestPaperRuntimeBootstrap::test_bootstrap_persists_session_manifest_history`.
- Result: `1 failed`.
- Exact failure:
  `AssertionError: False is not true` at
  `Path(str(first_history["history_artifact_path"])).exists()`.

The durable JSON correctly uses repository-relative POSIX identity, but the
test resolves that durable identity against the process CWD instead of the
explicit ledger/repository root. The path is therefore not a valid local
filesystem lookup as written.

## Repair boundary

- Preserve repository-relative POSIX paths in durable JSON.
- Keep external/temporary absolute paths out of stable artifact identity.
- Resolve durable paths only through an explicit repository/ledger-root
  resolver.
- Do not change broker adapter, paper gate, submission, paper queue, or order
  semantics.
- Add a Windows/Unix-equivalent path regression and rerun the full paper
  safety/runtime suite with a unique system temporary `basetemp`.

## Acceptance

1. The exact failing test passes without changing durable path identity.
2. Equivalent Windows and POSIX path spellings produce stable artifact
   identity/hash.
3. Paper session manifest history survives restart and is resolved through an
   explicit root.
4. No paper runner, paper queue, broker, private, order, live, or real-order
   capability is enabled.
5. A separate deliverable and append-only handoff are reviewed before G12 is
   rerun.
