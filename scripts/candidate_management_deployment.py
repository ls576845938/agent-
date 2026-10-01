"""Non-secret, create-only deployment preparation; no alternative server runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_shared.strategy_delivery.models import DeliveryError, digest, identifier

CONFIG_KEYS = (
    "QS_CANDIDATE_DELIVERY_ROOT", "QS_CANDIDATE_DELIVERY_OPERATOR",
    "QS_CANDIDATE_OFFLINE_CATALOG", "QS_CANDIDATE_OFFLINE_CATALOG_SHA256",
    "QS_CANDIDATE_OFFLINE_CATALOG_REVISION", "QS_CANDIDATE_OFFLINE_ENABLED",
    "QS_BACKEND_EVIDENCE_PROFILE", "QS_ALLOW_FIXTURE_FALLBACK", "QS_BTC_DEMO_CONTROL_ENABLED",
)
OWNER_FILE = ".candidate-deployment-owner.json"


def _owner(repo):
    return {"schema_version": "candidate_deployment_owner_v1",
            "repository_owner": digest({"repository": str(Path(repo).resolve())})}


def _external(path, repo):
    from quant_crypto.adapters.btc_runtime_artifact_store import git_worktree_roots
    path = Path(path)
    if not path.is_absolute():
        raise DeliveryError("candidate_deployment_external_absolute_required")
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise DeliveryError("candidate_deployment_link_rejected")
    path = path.resolve()
    if path == Path(path.anchor) or any(path.is_relative_to(r) or r.is_relative_to(path)
                                       for r in git_worktree_roots(Path(repo))):
        raise DeliveryError("candidate_deployment_external_absolute_required")
    return path


def _json(path):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise DeliveryError("candidate_deployment_metadata_oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(repo, root, operator, revision):
    """Explicit command only. Never adopts or overwrites an existing deployment."""
    root = _external(root, repo)
    identifier(operator); identifier(revision)
    owner = _owner(repo)
    catalog = {"schema_version": "candidate_offline_catalog_v1",
        "repository_owner": owner["repository_owner"], "revision": revision,
        "factory_root": "factory", "qlib_root": "qlib", "sources": [], "inputs": []}
    encode = lambda value: (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    catalog_bytes = encode(catalog)
    config = {
        "QS_CANDIDATE_DELIVERY_ROOT": str(root), "QS_CANDIDATE_DELIVERY_OPERATOR": operator,
        "QS_CANDIDATE_OFFLINE_CATALOG": str(root / "offline-catalog.json"),
        "QS_CANDIDATE_OFFLINE_CATALOG_SHA256": hashlib.sha256(catalog_bytes).hexdigest(),
        "QS_CANDIDATE_OFFLINE_CATALOG_REVISION": revision, "QS_CANDIDATE_OFFLINE_ENABLED": "false",
        "QS_BACKEND_EVIDENCE_PROFILE": "candidate_management", "QS_ALLOW_FIXTURE_FALLBACK": "false",
        "QS_BTC_DEMO_CONTROL_ENABLED": "false",
    }
    files = {OWNER_FILE: encode(owner), "offline-catalog.json": catalog_bytes,
             "accounts.json": encode({"schema_version": "delivery_account_catalog_v1", "accounts": []}),
             "deployment.json": encode(config)}
    if root.exists() and (not root.is_dir() or (any(root.iterdir()) and not (root / OWNER_FILE).is_file())):
        raise DeliveryError("candidate_deployment_existing_unowned_directory")
    for name, data in files.items():
        p = _external(root / name, repo)
        if p.exists() and (not p.is_file() or p.read_bytes() != data):
            raise DeliveryError("candidate_deployment_existing_file_conflict")
    for name in ("factory", "qlib"):
        p = _external(root / name, repo)
        if p.exists() and not p.is_dir(): raise DeliveryError("candidate_deployment_directory_conflict")
    root.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        try:
            with (root / name).open("xb") as stream: stream.write(data)
        except FileExistsError:
            if (root / name).read_bytes() != data: raise DeliveryError("candidate_deployment_create_race")
    for name in ("factory", "qlib"): (root / name).mkdir(exist_ok=True)
    return {"status": "prepared_empty", "configuration": str(root / "deployment.json"),
            "catalog_sha256": config["QS_CANDIDATE_OFFLINE_CATALOG_SHA256"],
            "accounts": 0, "sources": 0, "inputs": 0, "offline_enabled": False,
            "authentication_provisioned": False, "candidate_runnable": False}


def inspect_configuration(repo, environment):
    """Read-only checks. No values from authentication are returned or persisted."""
    blockers = ["missing:" + key for key in CONFIG_KEYS if not environment.get(key)]
    mode = environment.get("QS_CANDIDATE_AUTH_MODE", "key")
    if mode not in {"key", "local_no_password"}:
        blockers.append("candidate_management_auth_mode_invalid")
    if mode == "key" and not environment.get("QS_WEB_API_KEY", "").strip():
        blockers.append("candidate_management_authentication_missing")
    if environment.get("QS_BACKEND_EVIDENCE_PROFILE") != "candidate_management":
        blockers.append("candidate_management_profile_required")
    for key in ("QS_ALLOW_FIXTURE_FALLBACK", "QS_BTC_DEMO_CONTROL_ENABLED"):
        if environment.get(key) != "false": blockers.append(key + "_must_be_false")
    if environment.get("QS_CANDIDATE_OFFLINE_ENABLED") not in {"true", "false"}:
        blockers.append("candidate_offline_enabled_explicit_boolean_required")
    counts = None
    metadata_keys = CONFIG_KEYS[:5]
    if all(environment.get(k) for k in metadata_keys):
        try:
            identifier(environment["QS_CANDIDATE_DELIVERY_OPERATOR"])
            identifier(environment["QS_CANDIDATE_OFFLINE_CATALOG_REVISION"])
            root = _external(environment["QS_CANDIDATE_DELIVERY_ROOT"], repo)
            if not root.is_dir(): raise DeliveryError("candidate_management_root_missing")
            marker = _external(root / OWNER_FILE, repo)
            if not marker.is_file(): raise DeliveryError("candidate_management_owner_missing")
            if _json(marker) != _owner(repo): raise DeliveryError("candidate_management_owner_mismatch")
            catalog_path = _external(environment["QS_CANDIDATE_OFFLINE_CATALOG"], repo)
            if not catalog_path.is_file(): raise DeliveryError("candidate_management_catalog_missing")
            from backend.app.services.candidate_offline_inputs import OfflineInputs
            inputs = OfflineInputs(catalog_path, environment["QS_CANDIDATE_OFFLINE_CATALOG_SHA256"],
                                   environment["QS_CANDIDATE_OFFLINE_CATALOG_REVISION"], repo=repo)
            catalog = inputs.catalog()
            for name in ("factory_root", "qlib_root"):
                if not inputs.path_for(catalog[name]).is_dir():
                    raise DeliveryError("candidate_management_source_directory_missing")
            accounts_path = _external(root / "accounts.json", repo)
            if not accounts_path.is_file(): raise DeliveryError("candidate_management_accounts_missing")
            accounts = _json(accounts_path)
            if (not isinstance(accounts, dict) or accounts.get("schema_version") != "delivery_account_catalog_v1"
                or not isinstance(accounts.get("accounts"), list)):
                raise DeliveryError("candidate_management_accounts_invalid")
            # Metadata presence is not an account/candidate execution admission.
            counts = {"accounts": len(accounts["accounts"]), "sources": len(catalog["sources"]), "inputs": len(catalog["inputs"])}
        except DeliveryError as exc: blockers.append(exc.code)
        except (OSError, ValueError, KeyError, TypeError):
            blockers.append("candidate_management_metadata_unreadable_or_invalid")
    return {"status": "blocked" if blockers else "configuration_checked",
            "blockers": blockers, "inventory": counts, "candidate_runnable": False,
            "offline_enabled": environment.get("QS_CANDIDATE_OFFLINE_ENABLED") == "true",
            "paper_allowed": False, "live_allowed": False, "broker_or_order_allowed": False}


def load_configuration(path):
    value = _json(path)
    if (not isinstance(value, dict) or set(value) != set(CONFIG_KEYS)
        or any(not isinstance(v, str) for v in value.values())):
        raise DeliveryError("candidate_deployment_nonsecret_configuration_invalid")
    return value


def official_command(repo, *, check):
    # Invoke the same guarded PS1 used by start-backend.cmd. No uvicorn fallback.
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            "scripts/start_backend_current_main.ps1", *(["-Check"] if check else [])]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check", "start"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--operator")
    parser.add_argument("--revision", default="empty-v1")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--auth-mode", choices=("key", "local_no_password"),
                        help="Explicit local candidate mode, or existing environment key mode.")
    args = parser.parse_args(argv)
    from scripts.start_backend_current_main import _registered_main_worktree
    repo = _registered_main_worktree(REPO_ROOT)
    try:
        if args.action == "prepare":
            if args.root is None or not args.operator: raise DeliveryError("candidate_deployment_root_operator_required")
            print(json.dumps(prepare(repo, args.root, args.operator, args.revision), sort_keys=True))
            return 0
        if args.config is None: raise DeliveryError("candidate_deployment_config_required")
        environment = {**os.environ, **load_configuration(args.config)}
        if args.auth_mode is not None:
            environment["QS_CANDIDATE_AUTH_MODE"] = args.auth_mode
        inspection = inspect_configuration(repo, environment)
        if inspection["blockers"]:
            print(json.dumps(inspection, sort_keys=True))
            return 2
        # Only child process inherits configuration/credential; no os.environ/User write.
        return subprocess.run(official_command(repo, check=args.action == "check"),
                              cwd=repo, env=environment, check=False).returncode
    except DeliveryError as exc:
        print(json.dumps({"status": "blocked", "error": exc.code}))
        return 2
    except (OSError, ValueError, EOFError):
        print(json.dumps({"status": "blocked", "error": "candidate_deployment_configuration_or_launcher_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
