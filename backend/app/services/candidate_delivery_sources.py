"""Server-owned source resolvers. Only explicit validation commands use these readers."""
import hashlib
import json
from pathlib import Path
import subprocess

from quant_shared.strategy_delivery.models import DeliveryError, SCHEMA, digest, source_ref

HISTORY_SPEC = "docs/research/donchian-long-50usdt-20260921.json"
FROZEN_QLIB = "tests/fixtures/strategy_v2/contract.json"


class ResearchDeliverySources:
    def __init__(self, repo_root: Path, *, archive, qlib_root: Path, factory_reader=None, delivery_artifacts=()):
        self.repo = Path(repo_root)
        self.archive, self.qlib_root, self.factory_reader = archive, Path(qlib_root), factory_reader
        self.legacy_factory_reader = factory_reader
        if delivery_artifacts:
            from integrations.qlib_adapter.factory_delivery import FactoryDeliveryReader
            self.factory_reader = FactoryDeliveryReader(factory_reader, delivery_artifacts)
        from tools.agent_governance.git_metadata import current_branch_head
        self.head = current_branch_head(self.repo)[1]

    def _committed_json(self, path):
        try:
            raw = subprocess.check_output(["git", "show", self.head + ":" + path], cwd=self.repo, stderr=subprocess.DEVNULL, timeout=10)
            return json.loads(raw), hashlib.sha256(raw).hexdigest()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
            raise DeliveryError("committed_binding_unavailable", 503) from exc

    def compile(self, reference, *, package_schema=None, package_digest=None):
        ref = source_ref(reference)
        if ref["kind"] == "registered_rule": return self._rule(ref)
        run_id = ref["run_id"]
        nomination = None
        if ref["kind"] == "factory":
            reader = self.legacy_factory_reader if package_schema == SCHEMA else self.factory_reader
            if reader is None: raise DeliveryError("factory_reader_unavailable", 503)
            from integrations.qlib_adapter.factory_delivery import FactoryDeliveryReader
            result = (reader.get(run_id, candidate_id=ref["candidate_id"], package_digest=package_digest)
                      if type(reader) is FactoryDeliveryReader else reader.get(run_id))
            if result.get("integrity_status") != "passed": raise DeliveryError("factory_integrity_blocked")
            matches = [row for row in result.get("result", {}).get("candidates", []) if row.get("candidate_id") == ref["candidate_id"]]
            if len(matches) != 1: raise DeliveryError("factory_candidate_unknown_or_ambiguous")
            nomination = matches[0]
            run_id = nomination.get("qlib_run_id", "")
            if (nomination.get("factory_run_id") != ref["run_id"] or not run_id
                or nomination.get("audit_qlib_reference", {}).get("qlib_run_id") != run_id):
                raise DeliveryError("factory_final_audit_binding_invalid")
            source_ref({"kind": "qlib", "run_id": run_id, "candidate_id": "identity-check"})
        try:
            location = self.archive.resolve_qlib_run(self.qlib_root, run_id)
        except (ValueError, RuntimeError) as exc:
            raise DeliveryError("research_source_unavailable_or_conflicting", 503) from exc
        if location is None: raise DeliveryError("research_source_not_found", 404)
        if location.run_root.resolve().parent != location.qlib_root.resolve():
            raise DeliveryError("research_source_path_escape")
        if nomination is not None and package_schema != SCHEMA:
            from integrations.qlib_adapter.factory_package import compile_factory_package
            package = compile_factory_package(ref, result, location.run_root)
            expected = result.get("delivery_expected_package_digest")
            if expected is not None and digest(package) != expected:
                raise DeliveryError("factory_delivery_package_changed")
            return package
        from integrations.qlib_adapter.research_pipeline import read_sealed_evidence
        sealed = read_sealed_evidence(location.run_root)
        if sealed.get("integrity_status") != "passed": raise DeliveryError("research_seal_invalid")
        seal, trace = sealed["seal"], sealed.get("research_trace", {})
        if nomination and digest(seal) != nomination.get("audit_qlib_reference", {}).get("seal_sha256"):
            raise DeliveryError("factory_final_seal_mismatch")
        def read(name):
            if name not in seal["files"]: raise DeliveryError("required_artifact_not_sealed")
            path = (location.run_root / name).resolve()
            if not path.is_relative_to(location.run_root.resolve()): raise DeliveryError("artifact_path_invalid")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != seal["files"][name]: raise DeliveryError("source_changed_during_validation")
            return json.loads(raw)
        manifest = read("qlib_strategy_manifest.json")
        identity = trace.get("identity", {})
        qlib_candidate = identity.get("candidate_id") or manifest.get("candidate_id")
        if (not qlib_candidate or (ref["kind"] == "qlib" and qlib_candidate != ref["candidate_id"])
            or identity.get("qlib_run_id") != run_id or manifest.get("run_id") != run_id):
            raise DeliveryError("candidate_source_mismatch")
        for field in ("candidate_id", "strategy_id"):
            if manifest.get(field) and identity.get(field) and manifest[field] != identity[field]:
                raise DeliveryError("candidate_source_mismatch")
        binding, binding_hash = self._committed_json(FROZEN_QLIB)
        compatible = run_id == binding["run_id"] and qlib_candidate == binding["candidate_id"]
        blockers = list(trace.get("blockers", []))
        if nomination: blockers.extend(nomination.get("gate", {}).get("blockers", []))
        contracts = {}
        if compatible:
            from integrations.qlib_adapter.frozen_inference import _validate_static_binding, _validate_frozen_calibration
            _validate_static_binding(binding)
            _validate_frozen_calibration(binding, repo_root=self.repo)
            if any(seal["files"].get(name) != value for name, value in binding["artifact_sha256"].items()):
                raise DeliveryError("frozen_adapter_artifact_mismatch")
            contracts = {
                "features": {"version": "causal_ohlcv_trend_v1", "names": binding["features_in_order"], "expressions": binding["feature_expressions"]},
                "preprocessing": {"version": "frozen_processors_v1", "processors": binding["infer_processors"]},
                "output": {"version": "frozen_return_v1", "kind": "return_forecast", "unit": "return_fraction", "horizon_bars": 12, "valid_for_bars": 1},
                "calibration": {"version": "validation_ols_frozen_v1", **binding["calibration"]},
                **{name: {"version": "qlib_candidate_policy_v1", **body} for name, body in binding["policy_bindings"].items()},
                "time": {"version": "frozen_qlib_time_v1", **binding["time_semantics"]},
                "state": {"version": "qlib_candidate_policy_v1", "authority": "existing_btc_offline_runtime_and_ledger"},
            }
        else: blockers.append("runtime_adapter_binding_missing")
        # Engineering package compatibility does not override the original research verdict.
        if manifest.get("promotion_status") not in {"research_ready", "candidate_ready"}:
            blockers.append("research_admission_not_proven")
        source_head = identity.get("code_version") or seal.get("source_head") or manifest.get("commit_hash", "")
        return {"schema_version": SCHEMA, "source": ref, "strategy_id": manifest.get("strategy_id", ""),
                "strategy_version": manifest.get("strategy_version", ""), "source_head": source_head,
                "market": "crypto" if compatible else manifest.get("asset_class", "unknown"),
                "settlement_currency": "USDT" if compatible else None,
                "instrument": binding["venue_instrument"] if compatible else ",".join(manifest.get("symbols", [])),
                "bar_size": binding["bar_size"] if compatible else manifest.get("timeframe", ""),
                "data_version": binding["data_version"] if compatible else identity.get("data_version", ""),
                "params_hash": digest(manifest.get("params", {})), "artifacts": dict(seal["files"]),
                "contracts": contracts, "supported_targets": ["offline"] if compatible else [],
                "adapter_id": "btc_frozen_qlib_offline_v1" if compatible else "unsupported",
                "adapter_binding_sha256": binding_hash if compatible else None,
                "execution_binding": binding if compatible else None,
                "factory_nomination_digest": digest(nomination) if nomination else None,
                "admission_blockers": sorted(set(blockers)),
                "limitations": ["historical_research_not_runtime_evidence", "no_demo_adapter", "no_training_or_search"]}

    def recompile(self, reference, *, package_schema):
        # Persisted records select their original compiler. Never migrate an old
        # factory-backed V2 package by silently recompiling it with V3 defaults.
        from quant_shared.strategy_delivery.runtime_contract import PACKAGE_SCHEMA
        if package_schema not in {SCHEMA, PACKAGE_SCHEMA}:
            raise DeliveryError("source_package_version_unsupported")
        return self.compile(reference, package_schema=package_schema)

    def recompile_record(self, row):
        return self.compile(row["source"], package_schema=row["package"]["schema_version"],
                            package_digest=row["content_digest"])

    def _rule(self, ref):
        if ref["run_id"] != "donchian-long-50usdt-20260921": raise DeliveryError("rule_binding_not_allowlisted")
        from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
        from quant_crypto.application.donchian_history_spec import HistorySpec
        raw, checksum = self._committed_json(HISTORY_SPEC)
        HistorySpec.from_payload(raw)
        strategy, execution = raw["strategy"], raw["execution"]
        if ref["candidate_id"] != strategy["candidate_id"]: raise DeliveryError("rule_candidate_mismatch")
        spec = btc_strategy_registry.get(strategy["strategy_id"], strategy["candidate_id"])
        if spec.params_hash != strategy["params_hash"] or spec.strategy_version != strategy["strategy_version"]:
            raise DeliveryError("rule_registry_drift")
        head = self.head
        return {"schema_version": SCHEMA, "source": ref, **strategy, "source_head": head,
                "settlement_currency": "USDT",
                "market": "crypto", "instrument": "BTC-USDT-SWAP", "bar_size": "1h",
                "data_version": raw["data"]["dataset_version"], "artifacts": {HISTORY_SPEC: checksum, **raw["data"]["files"]},
                "contracts": {
                    "features": {"version": "original_donchian_v1", "params": strategy["params"]},
                    "preprocessing": {"version": "completed_1h_to_4h_v1"},
                    "output": {"version": "original_direction_v1", "kind": "direction_signal", "unit": "direction", "horizon_bars": 1, "valid_for_bars": 1},
                    "calibration": {"version": "not_applicable_rule_signal"},
                    "position": {"version": execution["position_rule"], "contracts": execution["order_contracts"], "contract_value_btc": execution["contract_value_btc"], "max_notional_usdt": execution["max_notional_usdt"]},
                    "exit": {"version": execution["exit_rule"], "protection": execution["protection"]},
                    "cost": {"version": execution["cost"]["version"], "cost": execution["cost"], "matching": execution["matching"], "funding_mark": execution["funding_mark"]},
                    "time": {"version": execution["matching"]["version"], "terminal": execution["terminal"], "window": raw["window"]},
                    "state": {"version": "existing_donchian_history_spec_v2", "authority": "existing_btc_offline_runtime_and_ledger"}},
                "supported_targets": ["offline"], "adapter_id": "btc_donchian_history_offline_v1",
                "execution_binding": raw, "admission_blockers": [],
                "limitations": [raw["evidence_class"], "registration_does_not_validate_or_run_full_dataset", "no_demo_adapter"]}
