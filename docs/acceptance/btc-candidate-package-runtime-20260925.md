# BTC candidate package producer acceptance

Date: 2026-09-25. Ticket: BTC-CANDIDATE-PACKAGE-RUNTIME-20260925.
Producer: super_developer. change_risk: unclassified.
Base: 9c1dac906f4b4527aa247d14f18497f56e9d8464.
Reserved independent review/integration:
INTEGRATE-BTC-CANDIDATE-PACKAGE-RUNTIME-20260925.

## Verdict

Source implementation plus isolated offline engineering evidence only.
Readiness ceiling: quality_checked, NOT promotion evidence or permission.
adf29164 and fe883ca9 remain immutable rejected partial snapshots. This
superseding implementation addresses their four P1 and one P2 findings;
independent review of the final commit remains required.

Implemented: create-only complete factory delivery producer; content-level
audit and calibration/policy evidence verification; exact source-version
dispatch; explicit account/runtime binding; public verified registered source/
facts wiring into the existing offline BTC authority chain; durable recovery;
truthful contract details/status in the existing UI. No private verification
flags, alternative OMS, changed risk thresholds or Donchian defaults.

Source has a usable explicit library composition, described below. The default
build_delivery_service bootstrap DOES NOT configure delivery_artifacts. Thus
the current deployed/default service cannot discover a separately produced
artifact. No operator CLI, HTTP publish/start, automatic bootstrap wiring,
live worker or UI-linked execution-result storage is implemented. These are
explicit unimplemented deployment/entrypoint conveniences, not missing domain
producer/source/account/execution functions. Running this source requires
explicit composition of the supported public APIs, not modifying business
objects, authoring an adapter, or using test Sources/Accounts substitutes.

Real existing factory evidence lacking frozen delivery_policy/calibration/
currency remains blocked. No complete real research candidate was produced,
resealed, retrained or promoted. Synthetic E2E outcomes are not strategy merit.

## Scope and dirty ownership

Planner sparse worktree:
D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-btc-candidate-package-runtime-20260925.
Branch: agent/super_developer/btc-candidate-package-runtime-20260925.

Initial ticket dirty: clean. At resumed preflight, the 16 paths reported dirty
belonged to this producer's continuation: 13 modified plus new factory_delivery.py,
package_evidence.py and test_registered_candidate_execution.py. All preserved.
No other agent's dirty was read or overwritten; no merge/main write performed.
The architecture document lists the exact approved touch set, including the
architect-approved account source and existing API test extension.

Ownership:
- models/runtime_contract/package_evidence/service: versioned package validation,
  reproducible evidence, historical compiler dispatch and safety-only recovery.
- factory_package/factory_delivery/package_inference: source content verification,
  contract assembly/publication and same-factor/model causal inference.
- candidate_delivery_sources/accounts: real explicit revisions and non-secret
  server-owned offline account runtime identity; absent runtime field preserves
  the legacy projection digest, paths are redacted.
- btc_registered_candidate/qlib_offline_replay: pre-economic source/market/account
  validation and public facts assembly; existing economic algorithms unchanged.
- CandidateDelivery.tsx/API types: distinguish structure/evidence/admission/
  execution; show digest-bound contracts; no start button or invented result.
- ticket tests, architecture and acceptance; append-only superseding handoff.

## Explicit reproducible composition

Prerequisites supplied by the caller, not defaults: approved source ref
(kind=factory, run_id, candidate_id); actual immutable factory and Qlib roots;
candidate-owned frozen_evidence; NEW absolute artifact path; external management
root and reviewed accounts.json; exact BTC market bars/observations/manifest;
account_ref; exact external economic state_dir. A missing prerequisite rejects.

frozen_evidence contains frozen_policy (candidate_id, qlib_run_id, data_version,
model_sha256, feature_specs_sha256, policies, clip_fraction, frozen_at);
calibration (version=candidate_ols_v1 plus already-frozen intercept/slope/clip);
model_dependencies; feature_dependencies; settlement_evidence. Policies include
position, exit, cost and output. Its policies/clip/frozen_at must already equal
delivery_policy in the SEALED factory_config.yaml. Do not insert them into an
old seal. The producer verifies these, it does not select or estimate them.

The following are concrete production API calls; capitalized variables represent
the caller's explicit inputs. This sequence is documentation, not an instruction
to execute on the user's real catalogs or register accounts during this ticket.

```python
from pathlib import Path
from backend.app.services.alpha_factory import AlphaFactoryService
from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
from backend.app.services.candidate_delivery_sources import ResearchDeliverySources
from backend.app.services.candidate_delivery_accounts import DeliveryAccounts
from backend.app.services.candidate_delivery_store import DeliveryStore
from quant_shared.strategy_delivery.service import DeliveryService
from quant_shared.strategy_delivery.models import digest
from integrations.qlib_adapter.factory_delivery import publish_factory_delivery
from tools.agent_governance.git_metadata import current_branch_head

repo = Path(REPO_ROOT).resolve()
archive = ResearchArchiveCatalog(repo_root=repo)
factory = AlphaFactoryService(root=Path(FACTORY_ROOT), qlib_root=Path(QLIB_ROOT),
                              queue=None, readonly_archive=archive)
envelope = factory.get(SOURCE_REF["run_id"])
candidate = next(c for c in envelope["result"]["candidates"]
                 if c["candidate_id"] == SOURCE_REF["candidate_id"])
location = archive.resolve_qlib_run(Path(QLIB_ROOT), candidate["qlib_run_id"])
# This is the only publication step; do not repeat it on restart.
publication = publish_factory_delivery(
    SOURCE_REF, envelope, location.run_root,
    frozen_evidence=FROZEN_EVIDENCE, destination=Path(NEW_ARTIFACT_PATH))
# Persist this exact pair as operator input, never discover a latest revision.
revision = (Path(NEW_ARTIFACT_PATH), publication["content_digest"])
sources = ResearchDeliverySources(repo, archive=archive, qlib_root=Path(QLIB_ROOT),
                                  factory_reader=factory, delivery_artifacts=[revision])
management = Path(MANAGEMENT_ROOT)
accounts = DeliveryAccounts(management / "accounts.json", repo_root=repo)
head = current_branch_head(repo)[1]
service = DeliveryService(
    DeliveryStore(management, digest({"repository": str(repo)})), sources, accounts,
    head=head, head_provider=lambda: current_branch_head(repo)[1])
row = service.create(SOURCE_REF, "offline", key=CREATE_KEY, actor=OPERATOR_ID)
row = service.command(row["id"], "bind", expected_revision=row["revision"],
                      key=BIND_KEY, actor=OPERATOR_ID, account_ref=ACCOUNT_REF)
row = service.command(row["id"], "review", expected_revision=row["revision"],
                      key=REVIEW_KEY, actor=REVIEWER_ID,
                      decision="approve", reason=REVIEW_REASON)
row = service.command(row["id"], "register", expected_revision=row["revision"],
                      key=REGISTER_KEY, actor=OPERATOR_ID)
```

Each key is an explicit stable idempotency key for that action. Approval is an
operator decision, not a producer-generated quality flag. GET/register do not
execute. On restart reconstruct service with the SAME revision, management root,
HEAD and account catalog, then read the SAME stored registration ID; do not
create a new candidate or reset initial equity.

Offline accounts.json uses delivery_account_catalog_v1 and accounts rows with
account_ref, environment=offline, simulation_namespace, revision, market=crypto,
instruments=[BTC-USDT-SWAP], currency=USDT, expires_at. Explicit offline_runtime:
schema_version=delivery_offline_runtime_v1, absolute state_directory,
initial_equity_usdt>0, currency=USDT, equity_unit=USDT. All supplied server-side.
No secret, health, verified or digest field is accepted as input authority.

```python
from quant_crypto.application.btc_registered_candidate import (
    open_btc_registered_candidate_offline, market_frame_digest, observation_digest)

manifest = {
    "schema_version": "registered_offline_market_v1",
    **{k: row["package"][k] for k in
       ("data_version", "instrument", "bar_size", "settlement_currency")},
    "bars_sha256": market_frame_digest(BARS),
    "observations_sha256": observation_digest(OBSERVATIONS),
    "initial_equity_usdt": EXPLICIT_INITIAL_EQUITY_USDT,
}
kwargs = dict(
    content_digest=row["content_digest"],
    account_identity_hash=row["binding"]["identity_hash"],
    adapter_id=row["package"]["adapter_id"], bars=BARS,
    market_manifest=manifest, market_manifest_digest=digest(manifest),
    observations=OBSERVATIONS, state_dir=Path(STATE_DIRECTORY), repo_root=repo)
with open_btc_registered_candidate_offline(service, row["id"], **kwargs) as runtime:
    receipt = runtime.execute_registered(EXPLICIT_OBSERVATION_INDEX)
# Same index after reopening returns/reconstructs the same durable decision.
# Revoked/expired authority: reconcile existing state only, never new decisions.
with open_btc_registered_candidate_offline(
        service, row["id"], **kwargs, recovery_only=True) as runtime:
    recovery_receipt = runtime.reconcile_registered()
```

BARS columns: event_time, available_time, decision_time, instrument, open, high,
low, close, volume; explicit UTC with hourly completed-bar availability.
OBSERVATIONS is a sequence of CandidateMarketObservation with market/funding
facts and OfflineMaintenanceFact records; no observed facts are synthesized by
the entrypoint. Forecasts are recomputed from visible inputs. Future execution
prices do not enter the model's past feature prefix.

Persistent outputs are under the explicit STATE_DIRECTORY: qlib_fixture_replay_identity.json,
offline_venue.json, guardian_latch.json, runtime and boundary stores, plus
existing decision evidence in runtime events. Never delete or reinitialize
these for recovery. Input hashes bind the caller's explicit offline observations;
they do not certify new data-steward provenance or live quote availability.

## Test matrix and commands

Runtime: D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe.
PowerShell sets PYTHONUTF8=1. All commands use -B -X utf8 -m pytest -q
--tb=short -p no:cacheprovider unless stated. No production database was used.

1. Review failure-first: new calibration/quality/asset/window/policy mutations
   initially 8 failed, 13 deselected (5.01s); fixed with reproducible receipts.
2. Maintenance failure-first:
   tests/contracts/test_registered_candidate_execution.py -k incomplete_or_future
   -> 1 failed, 9 deselected (38.75s), economic_constructor_reached.
   Fix moves missing/out-of-window/gapped facts rejection before construction.
   <=90s is this adapter's explicit input capability; existing 100s risk threshold
   is unchanged. Recovery still verifies input and never erases existing facts.
   Mixed V2/V3 reader failure-first: test_actual_factory_backed_v2_recompile_never_dispatches_to_v3
   -> 1 failed,27 deselected (6.83s): historical V2 incorrectly loaded an unrelated
   V3 artifact. Fixed by selecting the original reader before schema dispatch.
3. Final package suite:
   tests/contracts/test_candidate_package_runtime.py
   tests/integrations/test_candidate_package_inference.py
   tests/contracts/test_candidate_delivery_api.py
   tests/contracts/test_strategy_delivery.py
   -> 112 passed, one Starlette deprecation warning in 109.34s, including the
   corrected mixed V2/V3 reader regression.
4. Final registered suite:
   tests/contracts/test_registered_candidate_execution.py.
   -> 13 passed in 830.85s (13:50).
   Includes real AlphaFactoryService/ResearchArchiveCatalog/ResearchDeliverySources/
   DeliveryAccounts/DeliveryService/Store, two models, FOK fills, repeated event,
   restart/terminal exit, fees/funding/ledger, changed account/data/digest,
   expiry/revocation, constructor-before-facts rejection, writer lease,
   constructed-object bypass denial, durable intent and ledger crash recovery.
5. Current-source legacy regression:
   tests/integrations/test_qlib_candidate_policy.py
   tests/contracts/test_strategy_v0_freeze.py
   tests/contracts/test_strategy_v1_donchian_offline.py
   tests/contracts/test_strategy_v3_qlib_offline.py::test_explicit_nonzero_fixture_uses_existing_oms_ledger_and_survives_restart
   tests/contracts/test_strategy_v3_qlib_offline.py::test_ledger_commit_before_evidence_is_recovered_without_resubmit
   tests/integrations/test_qlib_frozen_inference.py::test_full_sealed_feature_raw_and_calibrated_prediction_parity
   -> 47 passed, 1 skipped in 279.15s. The unchanged V0 archive opt-in skips
   without QS_V0_VERIFY_ARCHIVE=1; selected fixed-Qlib parity checks all 1392 rows.
6. Separate existing IOC/OMS compatibility: 17 passed in8.69s:
   tests/contracts/test_btc_okx_demo_adapter.py::test_partial_fill_drill_opt_in_allows_only_0p03_ioc_opening
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_fill_order_plan_uses_one_ioc_entry_with_0p03_cap
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_entry_truth_requires_matching_order_fill_position_and_oco
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_entry_truth_rejects_duplicate_fill_identity_before_deduplication
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_partial_reconciliation_covers_order_fill_position_oco_ledger_and_ws
   tests/contracts/test_btc_okx_demo_paper_runtime.py::test_fok_partial_fill_enters_risk_reducing_only
   tests/contracts/test_btc_paper_oms_lifecycle.py
   tests/contracts/test_btc_paper_oms_session_reconciliation.py.
   Existing injected fixtures only; never ran a live fault-drill CLI.
7. frontend/node_modules/.bin/tsc.cmd --noEmit -p frontend/tsconfig.json -> exit0.
   No worktree frontend server or canonical browser was started.
8. py -3 -B -m compileall -q on the touched package/source/application modules,
   plus scoped git diff --check -> exit0 (only Git LF/CRLF conversion warnings).

Earlier real-Accounts E2Es passed (3/533.66s plus ledger recovery1/119.73s);
these are checkpoints, not additional independent totals. A recovery idempotency
conflict was reproduced and corrected by honoring an already reconciled exact
snapshot instead of committing it twice. Unknown post-intent outcomes correctly
stay pending/frozen. Initial float exact-lot and management-namespace guard
failures were fixed in fixture funding selection and explicit runtime namespace,
not by loosening minimum size, converter checks or the live guard.

Synthetic disclosure: two tiny LightGBM models, three boosting rounds each,
different feature/model hashes, generated260-bar fixtures; validation labels and
sealed research are synthetic. Explicit fixture equity is chosen to represent
exactly one .01contract under the unchanged converter. No claims about economic
performance, real quote continuity or accepted production candidates follow.

New candidate legal partial opening is unsupported/unverified (.01 min/max/lot
and FOK). Separate IOC tests are not that E2E; abnormal FOK partial remains a
failure/recovery drill. All runtime artifacts remain pytest-temp evidence.

## Governance and remaining limits

Read AGENTS, super-developer role TOML, knowledge README/non-negotiables,
shared/super_developer playbooks, delivery_risk_policy, data reliability,
financial ML validation, execution microstructure and domain architecture;
quant-agent-preflight and quant-agent-handoff skills. Team Context read as
discovery only; no uncommitted upstream consumed or raw pitfall logs bulk-read.

Catalog: 6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af.
Active IDs: BACKTEST-COST-001,GOV-CONCURRENCY-001,GOV-DIRTY-001,
GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,
GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,
REPLAY-ISOLATION-001,RESEARCH-HOLDOUT-001,GOV-PROMPT-001,GOV-WINDOWS-001.

No production artifact/manifest/ledger/latest was rebuilt; no current-main
artifact freshness or deployment acceptance established. No management config,
secrets, actual account, network broker/private/order endpoint accessed.
Not run: full repo suite, real factory research/training, raw-market rederivation
of sealed labels, full-year replay, browser visual QA, deployment or actual
registered-candidate legal partial fills. UI verification is TypeScript only.

Owners: independent integrator reviews final shared schema/capability/source
and execution acceptance; evidence owner supplies missing real frozen inputs;
deployment/entrypoint enablement requires its own authorization. Default service
discovery/CLI/UI execution linkage remains absent as stated above.

All flags remain false: demo_control_enabled,promotion,paper,live,private,order,
real_order,transfer,withdraw,execution_permission,runtime_worker_enabled,
runtime_observed. No main merge, service restart, push or release.
