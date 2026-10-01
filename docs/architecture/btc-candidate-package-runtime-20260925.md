# BTC candidate package source implementation

Ticket: BTC-CANDIDATE-PACKAGE-RUNTIME-20260925
Base: 9c1dac906f4b4527aa247d14f18497f56e9d8464
Role: super_developer. change_risk: unclassified.
Independent consumer: INTEGRATE-BTC-CANDIDATE-PACKAGE-RUNTIME-20260925.

## Current continuation checkpoint

The direct user pause at 2026-09-25 10:28:41 Asia/Shanghai
(2026-09-25T02:28:41.721Z) was superseded by the same user's architect-task
continuations at 11:27:33 and 11:53:52. Verified from both task histories.
The assistant's 12:37 pause mistakenly reapplied the old instruction after
compaction; it was not a new user pause. Continue this same ticket/worktree.
Do not restart from fe883ca9 or treat adf29164/fe883ca9 as approved delivery.

At continuation preflight all 16 dirty paths were this producer's preserved
implementation (13 modified, 3 new); no other writer's changes were consumed.
Final package/API/inference/service sweep: 112 passed (109.34s); full registered
suite through actual factory/archive/source/account components: 13 passed
(830.85s), including object forgery/writer exclusion and both crash boundaries.
Separate IOC/OMS 17 passed; TypeScript, compile and scoped diff check exit 0.
Current-source legacy regression: 47 passed, 1 existing opt-in archive skip
(279.15s). Implementation and focused tests are complete. Next: commit source,
validate/commit superseding handoff and deliver for independent review. No
main/service/trading changes; missing real frozen evidence remains blocked.

## Ownership and exact touch set

- quant_shared/strategy_delivery/{models.py,service.py,runtime_contract.py,package_evidence.py}
- integrations/qlib_adapter/{factory_package.py,factory_delivery.py,package_inference.py}
- backend/app/services/{candidate_delivery_sources.py,candidate_delivery_accounts.py}
- quant_crypto/application/{btc_registered_candidate.py,qlib_offline_replay.py}
- frontend/src/workspaces/research/{CandidateDelivery.tsx,candidate-delivery-api.ts}
- tests/contracts/{test_candidate_package_runtime.py,test_candidate_delivery_api.py,test_registered_candidate_execution.py}
- tests/integrations/test_candidate_package_inference.py
- this document; docs/acceptance/btc-candidate-package-runtime-20260925.md
- .agent/handoffs/BTC-CANDIDATE-PACKAGE-RUNTIME-20260925/

Initial ticket status was clean. This continuation preserves its own dirty.
Planner sibling sparse worktree:
D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-btc-candidate-package-runtime-20260925.
No ownership of BTC risk/OMS/protection/ledger algorithms, Donchian defaults,
settings/launchers, real account catalogs, raw data, or production runtime data.

## Supported package and source production

The new strategy_delivery_package_v3 is asset-neutral in structure, with one
implemented capability factory_lgbm_ast_v1: BTC-USDT-SWAP, USDT, 1h, LightGBM
text regression, ordered bounded factory AST factors and no inference processors.
No pickle, eval, user-selected imports, model fitting or implicit calibration.

publish_factory_delivery explicitly receives a verified final factory envelope
and candidate-owned frozen evidence (or a complete frozen contract). The builder
assembles candidate.delivery_contract; it never invents economic policy,
dependency versions, currency or calibration parameters. It creates a NEW file
with exclusive-create semantics, flush/fsync and exact content/package digests.
The original envelope/result/seal is not rewritten.

The producer verifies factory_trial/config/model plus features, labels,
pred_score, dataset_manifest and recorder_metrics. It recomputes audit model
scores and factory signal metrics from sealed content, checks exact feature/
asset/data/model/segment identities, and rejects omissions or resealed content
that fails reproduction. Recorder identity is required; optional empty recorder
signal metrics do not replace the reproduced authoritative factory metrics.
Labels remain authoritative sealed inputs; this is not a fresh raw-market
label audit or a claim that fabricated upstream seals could become trusted.

Candidate OLS parameters must reproduce from the sealed validation samples.
Quality/sample counts/hashes are recomputed, not accepted as submitted flags.
Runtime forecast quality uses only pre-audit validation rows; audit metrics
cannot be backfilled into historical sizing. Policy/output/clip/freeze time
must match the sealed research config's explicit delivery_policy. Zero fees or
zero aggregate friction fail closed. Policy changes require new immutable
source evidence, a new package and renewed review, not a rehash of old evidence.
prediction_start equals the exact audit bar-open start plus one hour; clock,
label window, asset, currency, dependencies and implementation hashes are bound.

FactoryDeliveryReader consumes explicit (artifact path, expected digest)
revisions and verifies the original factory result again. ResearchDeliverySources
accepts this reader through its explicit delivery_artifacts constructor argument.
There is no latest discovery, bootstrap/settings change, HTTP producer/start,
automatic training or scheduled worker. Existing real candidates without
delivery_policy/calibration/currency evidence remain blocked; no old seal repair.

## Registration and account identity

V2 records choose their historical compiler when refreshed; factory-backed V2
must not silently become V3. Existing Qlib/Donchian contracts stay separate.

An offline account may explicitly carry delivery_offline_runtime_v1. With no
such field, the legacy account projection and digest are unchanged. Server-owned
runtime input requires initial_equity_usdt, USDT units and an external absolute
state directory. Resolved/case-normalized paths reject disk roots, repositories,
registered worktrees, management storage, and equal/nested other account roots.
Reads create no directories and access no economic state.

The returned contract includes namespace, account_ref, contract digest, state
directory digest and the distinct fake-venue identity. The common fixture venue
UID is NOT account isolation. Physical state paths are never projected to HTTP.
Changes to runtime account data invalidate prior binding/review. No client
verified/hash/health assertion is accepted as authority.

## Explicit registered offline execution

open_btc_registered_candidate_offline calls verify_registered_candidate_inputs
before constructing the existing QlibFixtureOfflineReplay/controller/state.
It resolves exact registration/package/account/adapter/code identities and
validates immutable market/observation hashes, currency, initial equity, state
directory, timing, inferred forecast units/expiry, and simulator compatibility.
No writes to _verified_sealed_source or _sealed_expected_inputs are used.

The current in-process simulator supports 5 bps per-side fees plus 6 bps total
spread/slippage/impact and the existing .01-contract FOK limit. Other costs are
rejected, not silently simulated differently. Maintenance facts must be explicit,
inside the supplied bar-open-to-fill interval and have at most 90-second gaps.
This conservative input capability does not change existing 100-second freshness
or risk/OMS thresholds. Inference sees only available historical prefixes;
delayed-open and maintenance quotes are execution facts, not forecast features.

VerifiedRegisteredInputs.check re-runs the public verifier and inference against
the current registration. Merely constructing that Python class or rehashing
caller fields is not an authority bypass. Exact manifests/forecasts are rechecked
on use. Deterministic qlibreg namespaces avoid misclassifying the management word
delivery as a live execution namespace.

build_registered_candidate_facts derives equity/drawdown/daily loss/combined
PnL from existing recovered account and ledger evidence. It preserves actual
protection and uses candidate-owned cost/position/exit values through the existing
policy-to-risk-to-OMS-to-fill/ledger chain. Management SQLite is never the ledger.
Confidence=1 is an explicitly declared unit multiplier, not trading probability.

Revocation/expiry prevents new decisions. resolve_recovery allows exact prior
approved identity only, still checking current source/code/account bindings.
Recovery-only open requires existing durable runtime state and disallows new
decisions/orders. Reconciliation retains positions, fills, protection and
previous ledger event hashes. Unknown post-intent outcomes remain frozen without
resubmission; ledger-before-evidence recovery deduplicates the existing order.

## Acceptance and authorization limits

Two genuinely different synthetic AST/model packages use the actual producer,
AlphaFactoryService, ResearchArchiveCatalog, ResearchDeliverySources,
DeliveryAccounts, DeliveryService/Store and existing offline authority chain.
Temporary factory/market storage roots are explicit inputs; no Sources/Accounts
or factory/archive reader substitutes are used by the final registered E2E.
Tiny fixture models are trained only during pytest setup; execution prohibits
network and model training. This proves engineering, not investment performance.

Partial-fill acceptance is explicitly layered: new package normal .01/FOK
nonzero execution/duplicate/restart/exit/fees/funding/ledger; pre-existing IOC
compatibility separately. A .005 FOK fill is fault injection, not a legal partial
opening. New registered candidate legal partial opening is unsupported/unverified.
The UI distinguishes structure, content evidence, research admission and absent
linked execution results; it exposes digest-bound contract details, not a start.

Independent review/integration is still mandatory. No main merge, service
restart, deployment, management enablement, real account registration, Demo,
paper/live/private/order authority, promotion or production artifacts are granted.
