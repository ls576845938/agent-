"""Non-secret, server-configured account references, never a private API client."""
import json
import math
import os
from pathlib import Path

from quant_shared.strategy_delivery.models import DeliveryError, digest, identifier


class DeliveryAccounts:
    def __init__(self, path: Path | None, *, repo_root: Path, approval_registry: str = ""):
        self.path, self.repo, self.approvals = path, Path(repo_root).resolve(), approval_registry

    def list(self):
        if self.path is None or not self.path.is_file(): return []
        if self.path.resolve().is_relative_to(self.repo): raise DeliveryError("account_catalog_must_be_external")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload["schema_version"] != "delivery_account_catalog_v1": raise ValueError()
            rows = payload["accounts"]
            if not isinstance(rows, list) or len(rows) > 100: raise ValueError()
            ids = [identifier(row["account_ref"]) for row in rows]
            if len(set(ids)) != len(ids): raise ValueError()
            result = []
            state_roots = []
            for row in rows:
                allowed = {"account_ref", "environment", "revision", "market", "instruments", "currency", "expires_at", "simulation_namespace", "approval_id", "offline_runtime"}
                if set(row) - allowed: raise ValueError()
                projected = {key: row[key] for key in ("account_ref", "environment", "revision", "market", "instruments", "currency", "expires_at")}
                if row["environment"] == "offline":
                    namespace = identifier(row["simulation_namespace"])
                    projected.update(identity_hash=digest({"simulation_namespace": namespace, "environment": "offline"}),
                                     evidence_ref="explicit_simulation:" + namespace, verified=True)
                    if "offline_runtime" in row:
                        runtime=row["offline_runtime"]
                        if (not isinstance(runtime,dict) or set(runtime)!={"schema_version","state_directory","initial_equity_usdt","currency","equity_unit"}
                            or runtime["schema_version"]!="delivery_offline_runtime_v1"
                            or runtime["currency"]!=row["currency"] or runtime["currency"]!="USDT"
                            or runtime["equity_unit"]!="USDT"
                            or type(runtime["initial_equity_usdt"]) not in (int,float)
                            or not math.isfinite(runtime["initial_equity_usdt"]) or runtime["initial_equity_usdt"]<=0):
                            raise ValueError("offline_runtime_contract_invalid")
                        directory=Path(runtime["state_directory"])
                        if not directory.is_absolute(): raise ValueError("offline_state_not_absolute")
                        directory=Path(os.path.normcase(str(directory.resolve())))
                        from quant_crypto.adapters.btc_runtime_artifact_store import git_worktree_roots
                        forbidden=[Path(os.path.normcase(str(p.resolve()))) for p in (*git_worktree_roots(self.repo),self.path.parent)]
                        if directory==Path(directory.anchor) or any(directory.is_relative_to(p) or p.is_relative_to(directory) for p in forbidden+state_roots):
                            raise ValueError("offline_state_scope_or_conflict")
                        state_roots.append(directory)
                        from quant_crypto.application.btc_demo_start_attempt import authoritative_account_identity_snapshot
                        identity=authoritative_account_identity_snapshot({"uid":"offline-account","mainUid":"offline-main"})["hash"]
                        contract={"schema_version":runtime["schema_version"],"simulation_namespace":namespace,
                            "account_ref":row["account_ref"],"state_directory_sha256":digest(str(directory)),
                            "initial_equity_usdt":runtime["initial_equity_usdt"],"currency":"USDT","equity_unit":"USDT",
                            "simulated_venue_identity_hash":identity,"venue_adapter":"qlib_inprocess_fok_v1"}
                        projected["offline_runtime"]={**contract,"contract_digest":digest(contract)}
                elif row["environment"] == "okx_demo":
                    if "offline_runtime" in row: raise ValueError("offline_runtime_environment_invalid")
                    from quant_crypto.oms.account_risk_facts import load_reviewed_account_facts_approval
                    approval = load_reviewed_account_facts_approval(registry_path=self.approvals,
                        approval_id=identifier(row["approval_id"]), repo_root=self.repo)
                    projected.update(identity_hash=approval["account_identity_hash"], evidence_ref=row["approval_id"],
                                     approval_digest=approval["approval_digest"], verified=True)
                else: raise ValueError()
                result.append(projected)
            return result
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise DeliveryError("account_catalog_invalid_or_unverified", 409) from exc

    def get(self, ref):
        matches = [row for row in self.list() if row["account_ref"] == ref]
        if len(matches) != 1: raise DeliveryError("account_unknown", 404)
        return matches[0]

    def offline_state_directory(self, ref, expected_contract_digest):
        """Internal only; the public account projection deliberately hides paths."""
        current = self.get(ref)
        if current.get("offline_runtime", {}).get("contract_digest") != expected_contract_digest:
            raise DeliveryError("account_binding_changed")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = [r for r in payload["accounts"] if r["account_ref"] == ref]
        if len(rows) != 1: raise DeliveryError("account_unknown", 404)
        result = Path(rows[0]["offline_runtime"]["state_directory"]).resolve()
        from quant_crypto.application.btc_registered_candidate import state_directory_digest
        if state_directory_digest(result) != current["offline_runtime"]["state_directory_sha256"]:
            raise DeliveryError("account_binding_changed")
        return result
