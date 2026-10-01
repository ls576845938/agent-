"""Shared research-only sidecar; deliberately outside fit, scoring and risk inputs."""
from collections import Counter, deque
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_shared.trend_environment import Bar, EnvironmentConfig, estimate
from quant_shared.trend_environment.model import MODEL_VERSION, digest
from quant_shared.strategy_runtime.models import StrategyDecisionContext, StrategyIdentity
from .schemas import QlibAdapterError, build_run_paths, read_json, write_json, resolve_git_commit

EVIDENCE = "trend_environment.json"
OBSERVATIONS = "trend_environment_observations.jsonl"
SAFETY = {key: False for key in ("execution_permission", "runtime_observed", "promotion", "paper", "live", "private",
                                  "order", "real_order", "transfer", "withdraw")}


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(root: Path):
    manifest = read_json(root / "qlib_input/dataset_manifest.json")
    meta = read_json(root / "qlib_run_metadata.json")
    if manifest.get("run_id") != root.name or meta.get("run_id") != root.name:
        raise QlibAdapterError("environment_run_identity_mismatch")
    version = manifest.get("input_contract", {}).get("data_version_request")
    candidate = read_json(root / "qlib_strategy_manifest.json") if (root / "qlib_strategy_manifest.json").exists() else {}
    result = {"run_id": root.name, "data_version": version, "code_version": meta["code_version"],
              "research_config_hash": meta["config_sha256"], "dataset_manifest_hash": sha(root / "qlib_input/dataset_manifest.json"),
              "metadata_hash": sha(root / "qlib_run_metadata.json"), "candidate_id": candidate.get("manifest_id"),
              "factory_run_id": manifest.get("factory_run_id"), "source_input_run_id": manifest.get("source_input_run_id"),
              "source_input_seal_hash": manifest.get("source_input_seal_sha256")}
    if not result["code_version"] or not result["research_config_hash"]: raise QlibAdapterError("environment_version_missing")
    return result, manifest


def source_root_for(root: Path, identity: dict):
    source_id = identity.get("source_input_run_id")
    if not source_id: return root
    from .research_pipeline import read_sealed_evidence
    source = build_run_paths(source_id, root.parent).run_root
    if source == root: raise QlibAdapterError("environment_cyclic_source")
    # A factory input is dataset-only. Never recurse through arbitrary trial graphs.
    source_manifest = read_json(source / "qlib_input/dataset_manifest.json")
    if source_manifest.get("source_input_run_id"): raise QlibAdapterError("environment_nested_source_forbidden")
    verified = read_sealed_evidence(source)
    if verified["integrity_status"] != "passed" or digest(verified["seal"]) != identity["source_input_seal_hash"]:
        raise QlibAdapterError("environment_source_seal_mismatch")
    if source_manifest.get("input_contract", {}).get("data_version_request") != identity["data_version"]:
        raise QlibAdapterError("environment_source_version_mismatch")
    return source


def _inputs(source: Path):
    manifest = read_json(source / "qlib_input/dataset_manifest.json")
    contract = manifest.get("input_contract", {})
    path = source / "qlib_input/daily_bars.parquet"
    if sha(path) != manifest["input_sha256"]: raise QlibAdapterError("environment_input_hash_mismatch")
    extra = manifest.get("environment_contract")
    if extra:
        path = source / "qlib_input/environment_bars.parquet"
        calendar_path = source / "qlib_input/environment_calendar.parquet"
        if sha(path) != extra["bars_hash"] or sha(calendar_path) != extra["calendar_hash"]:
            raise QlibAdapterError("environment_temporal_input_hash_mismatch")
        frame = pd.read_parquet(path).rename(columns={"instrument": "symbol"})
        cal = pd.read_parquet(calendar_path)
        frame["close_time"] = frame.event_time
        schedule = pd.to_datetime(cal.event_time, utc=True).to_list()
        calendar = extra["calendar"]
        annualization = extra["periods_per_year"]
        availability = extra["availability_semantics"]
    else:
        frame = pd.read_parquet(path)
        if not {"event_time", "available_time", "decision_time", "symbol", "confirm"}.issubset(frame):
            raise QlibAdapterError("environment_temporal_contract_missing")
        calendar = manifest.get("calendar", {}).get("name")
        if calendar != "UTC_24x7" or contract.get("bar_size") != "1h":
            raise QlibAdapterError("environment_calendar_adapter_not_bound")
        frame["close_time"] = pd.to_datetime(frame.event_time, utc=True) + pd.Timedelta(hours=1)
        schedule = (pd.to_datetime(manifest["calendar"]["trading_days"], utc=True) + pd.Timedelta(hours=1)).to_list()
        annualization = contract["annualization"]
        availability = manifest.get("validation", {}).get("available_time_semantics", "unknown")
    if not {"event_time", "available_time", "decision_time", "symbol", "close", "close_time"}.issubset(frame):
        raise QlibAdapterError("environment_temporal_contract_missing")
    for key in ("event_time", "available_time", "decision_time", "close_time"):
        if any(pd.Timestamp(v).tzinfo is None for v in frame[key]): raise QlibAdapterError("environment_timezone_missing")
        frame[key] = pd.to_datetime(frame[key], utc=True, errors="raise")
        if frame[key].isna().any(): raise QlibAdapterError("environment_time_missing")
    if frame.duplicated(["symbol", "close_time"]).any(): raise QlibAdapterError("environment_duplicate_bar")
    daily = contract["bar_size"] == "1d"
    config = EnvironmentConfig((20, 60, 120) if daily else (24, 72, 168), calendar, annualization, 86400 if daily else 3600)
    return frame, schedule, config, availability, sha(path)


def build_sidecar(root: Path, *, enabled: bool = True):
    """Call only before sealing a new run. Returns failure evidence without changing research results.

    No hidden recomputation for old runs; a sealed destination is never modified.
    Disk-write failures also return explicit blocked status to the caller receipt.
    """
    if (root / "run_seal.json").exists() or (root / EVIDENCE).exists():
        raise QlibAdapterError("environment_destination_immutable")
    identity = {"run_id": root.name}
    receipt = {"schema_version": "trend_environment_evidence_v1", "model_version": MODEL_VERSION,
               "status": "disabled" if not enabled else "blocked", "usage": "observation_only", "blockers": [], **SAFETY}
    try:
        identity, manifest = binding(root)
        receipt["identity"] = identity
        if enabled:
            if not identity["data_version"] or identity["data_version"] == "latest":
                raise QlibAdapterError("environment_exact_data_version_required")
            source = source_root_for(root, identity)
            frame, schedule, config, availability, input_hash = _inputs(source)
            # Trials may see only their declared evaluation window, never later campaign audit bars.
            if (root / "factory_trial.json").exists():
                trial = read_json(root / "factory_trial.json")
                frame = frame[frame.decision_time <= pd.Timestamp(trial["segments"]["test"][1])]
            if frame.empty: raise QlibAdapterError("environment_empty_input")
            counts = Counter()
            as_of = None
            with (root / OBSERVATIONS).open("x", encoding="utf-8", newline="\n") as out:
                for asset, group in frame.groupby("symbol", sort=True):
                    if not group.close_time.is_monotonic_increasing: raise QlibAdapterError("environment_unordered_input")
                    window = deque(maxlen=max(config.horizons)+2)
                    # Keep delayed bars in the window: the pure function, not sorting by arrival,
                    # decides what was actually visible at each historical decision.
                    schedule_index = 0
                    for row in group.itertuples():
                        window.append(Bar(asset, row.event_time.to_pydatetime(), row.close_time.to_pydatetime(),
                                          row.available_time.to_pydatetime(), float(row.close), getattr(row, "confirm", 1) == 1))
                        decision = row.decision_time.to_pydatetime()
                        while schedule_index < len(schedule) and schedule[schedule_index] <= decision: schedule_index += 1
                        expected = schedule[max(0, schedule_index-max(config.horizons)-2):schedule_index]
                        observations = estimate(list(window), asset=asset, decision_time=decision,
                                                expected_close_times=expected, config=config)
                        for observation in observations:
                            out.write(json.dumps(observation, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
                            counts[observation["status"]] += 1
                        as_of = max(as_of, decision) if as_of else decision
            reference = {"run_id": root.name, "artifact": OBSERVATIONS, "sha256": sha(root / OBSERVATIONS),
                         "model_version": MODEL_VERSION, "environment_config_hash": config.config_hash, **identity}
            # Existing immutable Context is reused for evidence only. Never pass it into the BTC runtime.
            context = StrategyDecisionContext(identity=StrategyIdentity(root.name, identity.get("candidate_id") or "factory_trial",
                MODEL_VERSION, identity["code_version"], identity["data_version"]),
                parameters={"evidence_refs": {"trend_environment_v1": reference}})
            receipt.update(status="completed", observation_counts=dict(counts), observation_count=sum(counts.values()),
                as_of=as_of.isoformat(), config=asdict(config), config_hash=config.config_hash,
                availability_semantics=availability, input_hash=input_hash, observations=reference,
                context={"schema_version": context.schema_version, "identity_digest": context.identity.digest,
                         "parameters": {"evidence_refs": {"trend_environment_v1": reference}}})
    except Exception as exc:
        receipt.update(status="blocked", identity=identity, blockers=["environment_observation_failed:" + type(exc).__name__ + ":" + str(exc)])
    try:
        write_json(root / EVIDENCE, receipt)
    except OSError:
        return {"status": "blocked", "blockers": ["environment_evidence_write_failed"], **SAFETY}
    return {"status": receipt["status"], "run_id": root.name, "artifact": EVIDENCE, "sha256": sha(root / EVIDENCE),
            "blockers": receipt["blockers"], **SAFETY}


def read_sidecar(root: Path, seal: dict):
    """Read only: called after the outer seal was verified. No latest, creation or recompute."""
    if not (root / EVIDENCE).exists(): return {"status": "missing", "blockers": ["old_run_has_no_environment_evidence"], **SAFETY}
    payload = read_json(root / EVIDENCE)
    if payload.get("schema_version") != "trend_environment_evidence_v1" or payload.get("usage") != "observation_only":
        raise QlibAdapterError("environment_schema_mismatch")
    if payload.get("status") not in {"completed", "blocked", "disabled"} or payload.get("model_version") != MODEL_VERSION:
        raise QlibAdapterError("environment_status_or_model_mismatch")
    if any(payload.get(k) is not False for k in SAFETY): raise QlibAdapterError("environment_safety_mismatch")
    actual, _ = binding(root)
    if payload.get("identity") != actual or actual["code_version"] != seal["source_head"]:
        raise QlibAdapterError("environment_binding_mismatch")
    source_root_for(root, actual)
    preview = deque(maxlen=48)
    if payload["status"] == "completed":
        config = dict(payload["config"]); config["horizons"] = tuple(config["horizons"])
        if EnvironmentConfig(**config).config_hash != payload["config_hash"]: raise QlibAdapterError("environment_config_mismatch")
        reference = payload["observations"]
        if reference.get("artifact") != OBSERVATIONS or reference.get("sha256") != seal["files"].get(OBSERVATIONS):
            raise QlibAdapterError("environment_observation_hash_mismatch")
        if any(reference.get(k) != v for k,v in actual.items()): raise QlibAdapterError("environment_reference_mismatch")
        if payload["context"]["parameters"]["evidence_refs"]["trend_environment_v1"] != reference:
            raise QlibAdapterError("environment_context_mismatch")
        count = 0
        counts = Counter()
        with (root / OBSERVATIONS).open(encoding="utf-8") as rows:
            for line in rows:
                row = json.loads(line)
                if row["config_hash"] != payload["config_hash"] or row["model_version"] != payload["model_version"]:
                    raise QlibAdapterError("environment_row_identity_mismatch")
                if row["usage"] != "observation_only" or row["status"] not in {"observed", "unknown"}:
                    raise QlibAdapterError("environment_row_status_mismatch")
                counts[row["status"]] += 1
                count += 1; preview.append(row)
        if count != payload["observation_count"] or dict(counts) != payload["observation_counts"]:
            raise QlibAdapterError("environment_row_count_mismatch")
    current = resolve_git_commit(Path(__file__).resolve().parents[2])
    return {**payload, "preview": list(preview), "source_stale": actual["code_version"] != current,
            "historical_observation_only": True, "evidence_sha256": seal["files"][EVIDENCE]}
