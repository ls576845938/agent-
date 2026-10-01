# STRATEGY-V3-QLIB-OFFLINE independent review

## Status

- Review state: `blocked_pending_one_bounded_producer_correction`
- Change risk: `demo_execution_semantics`
- Integration base: `b6b4b14c37bd6ae3d201b56f64eba439ec428399`
- Reviewed source: `f4cb423121e54c0259fdd110b9115fd39669c0a8`
- Reviewed published handoff: `0b924caa4f29fe6fdf3bd17c6cef2be3573c2272`
- Isolated integration HEAD before this report: `2dfe0089eee77d2df54783de29f1b0a9705e819b`
- Main merge, release, service, UI, Demo, account, network, private, order and live work: `not_started`
- Promotion, paper, live, private, order, real-order, transfer, withdraw and execution permission: `false`

The source and handoff were consumed only in the dedicated sparse integration worktree. This checkpoint is a rejection of the first candidate, not approval or publication.

## Accepted boundaries

- The handoff schema, base ancestry and all eight committed deliverable SHA-256 values were verified.
- The candidate and explicit nonzero fixture remain separate namespaces; the historical candidate still reports 1,392 decisions, zero approvals and zero fills.
- No training, search, network, service or broker/exchange endpoint was invoked by this review.

## Blocking findings

1. **The verified archive is not the data actually read.** `evaluate_frozen_candidate` verifies the sealed archive, then reads the absolute paths embedded in `qlib_input/dataset_manifest.json`. Independent inspection found all six manifest paths outside the resolved archive and pointing to the older `m1-research-acceptance-20260911-01` tree. They currently exist, so the green test hides the provenance break; the verified archive hashes do not cover the bytes consumed by lines 269-272.
2. **The real candidate and persistent execution path are disconnected.** The 1,392-row function performs in-memory policy parity and fails immediately if any row is approved. It does not persist each no-trade decision through the V3 runtime. The nonzero test constructs a `0.0001 BTC` `TargetPosition` by hand and calls `execute` without calling the extracted candidate policy. Therefore Forecast -> original candidate policy -> Target/Exit -> persistent execution is not one tested chain.
3. **The fixture does not implement the frozen historical execution contract.** It reuses the V1 venue's fixed `60000` immediate fill and advances observation time by seconds. It does not prove `event+2h` delayed OPEN pricing or 6 bps price friction. Funding is asserted only as an explicit zero cashflow; nonzero funding order and missing-funding fail-closed behavior are untested.
4. **Reconstruction overwrites persisted unsafe runtime facts.** A direct reproduction persisted `FROZEN_UNKNOWN`, `write_path_trusted=false`, disconnected private WS, inactive runtime and opening disabled. Reconstructing `QlibFixtureOfflineReplay` changed them to `RUNNING`, trusted, connected, active and opening enabled. `_activate` and `execute` unconditionally call `_set_runtime_facts(active=True)` instead of preserving the verified recovery boundary.
5. **V3 recovery is not established by V1 tests.** V3 has no equivalent of the V1 recovered phase outcome. A ledger-committed/evidence-missing interruption can re-plan from the current position and lose the original fill/UOW linkage; the V3 result records only a snapshot hash. The cited V1 ledger-before-evidence and unknown-intent tests exercise a different orchestrator.
6. **The pure-policy extraction changes risk semantics.** The V3 change forces `data_anomaly=False` where the prior research trace used `bool(blockers)`. The current 1,392-row candidate does not cover the affected quality-failure branch.
7. **Exit policy is still supplied externally.** `CandidatePolicyFacts.exit_reasons` receives already-computed values. Hard stop, trailing stop, holding-period and reversal calculations remain in the old trace, while the fixture supplies phase and target manually. The source therefore does not yet prove reuse of the original candidate exit rules.

These findings are one bounded vertical-chain rejection. They do not authorize a new OMS, changed risk/Guardian semantics, altered candidate threshold, new governance work, or a second engineering branch.

## Independent commands and evidence

### Archive/input provenance probe

The probe loaded the committed V3/V2 contracts, resolved the verified archive, then compared every dataset-manifest path with that archive. Result: `inside_archive=false` for `daily_bars_parquet`, `dataset_manifest`, `funding`, `input_csv_dir`, `mark` and `premium`; each legacy absolute path currently exists.

### Persisted unsafe-state reconstruction probe

The probe created an isolated temporary V3 fixture state, persisted these facts, closed the first replay, and reconstructed the replay from the same state:

```text
before: risk_mode=FROZEN_UNKNOWN, trusted=false, ws_connected=false,
        runtime_status=offline_blocked, active=false, opening=false
after:  risk_mode=RUNNING, trusted=true, ws_connected=true,
        runtime_status=offline_execution, active=true, opening=true
```

The successful probe exited `0`. An earlier exploratory probe referenced a nonexistent `runtime_lifecycle` key and exited `1`; it is not used as acceptance evidence.

### Not run at this checkpoint

- Producer's full 54-test green matrix was not repeated after the blocking facts were reproduced.
- Synthetic Qlib training compatibility tests, old M1 allowlist tests, OS hard-crash, services/API/UI, network/account/exchange/private/order/live and release were not run.

## Required bounded correction

The existing producer ticket gets one correction attempt covering the same approved touch set: consume only hashed archive-relative inputs; connect real Forecast to the unchanged candidate position/exit policy and the same persistent authority entry; retain truthful zero-fill candidate evidence; use a separately labelled nonzero fixture through that same policy/entry; implement the frozen time/cost/funding contract; preserve persisted unsafe state; and directly test V3 evidence recovery/unknown intent with exact fill and ledger-UOW references. If that cannot be done within the approved boundary, this ticket remains blocked.

## Final disposition after the bounded correction

- Final verdict: `partial_blocked`.
- Source contract: `blocked_on_sealed_candidate_to_authority_entry`.
- Corrected source: `6db3a285bded0479bb8d0434f260b62c34fad2e8`.
- Corrected handoff: `14a35d4c0292a7e7c507e3bea30ef21be019e306`.
- Isolated integration HEAD before this report update: `6f5a68f2e7d5927e0fbcb507250a662d8bc2bf85`.
- Main merge, release, service, UI, Demo, account, network, private, order and live remain `not_started`; every promotion/execution permission remains `false`.

The corrected handoff supersedes the initial event, preserves the approved ancestry and touch set, and all eight committed deliverable SHA-256 values match Git object bytes. The canonical interpreter was `D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe`, Python `3.11.15`. `qlib_offline_replay`, `candidate_policy` and `okx_demo_paper_runtime` imported from this sparse integration worktree, not main or an editable-install copy.

### Disposition of the seven initial findings

1. **Archive provenance: closed.** The correction verifies and reads archive-relative bars, mark, premium and funding files. Legacy absolute manifest paths are ignored and archive tamper is rejected.
2. **Candidate-to-authority entry: still blocked.** All 1,392 sealed forecasts now pass the shared pure policy/exit/conversion step and produce durable JSONL no-trade evidence. They remain correctly rejected with zero fills. However, `evaluate_frozen_candidate` still raises on any approved row and never calls the persistent `QlibFixtureOfflineReplay` authority entry. That entry requires `forecast.metadata.fixture_only=true`, which sealed forecasts do not have. The result is a shared pure policy with two acceptance branches, not a sealed candidate decision entering the same persistent Risk/Guardian/OMS/Ledger boundary.
3. **Synthetic execution semantics: closed only for the fixture.** The fixture now derives target and exit through `evaluate_candidate_step`, uses event+2h delayed OPEN, 6 bps price friction, 5 bps-per-side venue fee, nonzero funding cashflow, missing-funding rejection, unit reconversion and the existing authority chain. It remains fixture-only and is not candidate effectiveness. Continuous same-account reverse reopen is honestly blocked when post-fee/funding quantity is not exactly representable by the frozen lot; no policy or threshold was relaxed.
4. **Persisted unsafe recovery: closed for the tested cases.** FROZEN/untrusted/disconnected facts and unresolved intent remain fail-closed; the initial reconstruction bug no longer reproduces in the corrected matrix.
5. **V3 recovery/evidence: partial.** The tested ledger-committed/evidence-missing interruption recovers a client order and ledger event/hash without resubmit or duplicate fill, and unknown intent blocks retry. This does not prove arbitrary interruption-point recovery: `_recover_result` selects the latest ledger that contains the order, reports current venue aggregate counts, and does not bind an exact fill-ID list. The test interrupts `_append_decision_evidence`; it does not cover a crash after ledger commit but before the separately persisted policy-state write. OS-process hard crash remains not run.
6. **Risk semantic drift: closed.** Quality blockers again drive `data_anomaly`, and the negative branch is directly covered.
7. **Exit-policy extraction: closed as a pure component, not as sealed-candidate execution.** Long/short hard stop, trailing stop, holding progression, reversal and ordered reason accumulation are tested. The fixture still supplies synthetic account/risk facts and its own frozen config/digests; this does not convert it into the sealed candidate path.

The authorized objective was `sealed prediction -> original candidate position/exit -> existing BTC authority chain -> simulated fill/persistent ledger -> exact evidence`. The correction establishes two truthful but separate paths:

- sealed prediction -> shared original policy/exit/conversion -> persistent no-trade JSONL evidence; and
- explicit fixture forecast -> shared policy/exit/conversion -> existing BTC authority chain -> simulated fill/ledger/evidence.

Because the first path cannot enter the second path's persistent boundary, the complete vertical chain is not accepted. No further producer correction is authorized in this ticket; this is the engineering-loop stop point.

### Independent corrected-source tests

Canonical corrected V3 matrix, including the real 1,392-row archive replay:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:MLFLOW_DISABLE_AGENT_HINT='1'
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v3-integrator-final-20260916-a" tests/integrations/test_qlib_candidate_policy.py tests/contracts/test_strategy_v3_qlib_offline.py
```

Result: `26 passed in 29.03s`.

Minimal V2/V1/no-live compatibility:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:QS_V0_VERIFY_ARCHIVE='1'
$env:MLFLOW_DISABLE_AGENT_HINT='1'
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v3-integrator-compat-20260916-a" tests/integrations/test_qlib_frozen_inference.py::test_full_sealed_feature_raw_and_calibrated_prediction_parity tests/integrations/test_qlib_frozen_inference.py::test_v2_never_returns_execution_objects tests/contracts/test_strategy_v1_donchian_offline.py::test_continuous_open_hold_reverse_reopen_exit_is_economically_replayable tests/contracts/test_strategy_v1_donchian_offline.py::test_ledger_committed_before_evidence_is_recovered_without_resubmit tests/contracts/test_strategy_v1_donchian_offline.py::test_intent_persisted_before_post_remains_unknown_and_never_blind_retries tests/integrations/test_no_live_side_effects.py::test_qlib_adapter_sources_never_emit_paper_or_live_ready_states
```

Result: `6 passed in 61.14s`.

The producer's initial `54 passed` command used an unspecified interpreter and is superseded rather than reused as current evidence. Synthetic Qlib training compatibility, old M1 allowlist, arbitrary/OS hard-crash, services/API/UI, actual account/exchange/network/private/order/live, main merge/release and promotion were not run.

### Governance record

- Playbooks: `quant-agent-preflight`, `quant-gate-evidence-review`, `quant-agent-handoff`, shared pitfalls, non-negotiables and integrator role contract.
- Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-HANDOFF-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `GOV-PROMPT-001`, `GOV-WINDOWS-001`.
- Catalog SHA-256: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.
