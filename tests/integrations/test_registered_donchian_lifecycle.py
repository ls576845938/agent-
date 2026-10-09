"""Bounded software proof for the registered Donchian lifecycle.

The fixture supplies immutable in-memory copies of a small synthetic market
table, but the coordinator, registered driver, original historical replay,
risk, OMS, fill venue, and ledger are production implementations.  It is not
candidate or promotion evidence.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

import pandas as pd
import pytest

from backend.app.services.alpha_factory import AlphaFactoryService
from backend.app.services.candidate_delivery_accounts import DeliveryAccounts
from backend.app.services.candidate_delivery_sources import HISTORY_SPEC, ResearchDeliverySources
from backend.app.services.candidate_delivery_store import DeliveryStore
from backend.app.services.candidate_offline_inputs import OfflineInputs
from backend.app.services.candidate_offline_service import CandidateOfflineService
from backend.app.services.candidate_offline_store import OfflineStore
from backend.app.services.research_archive_discovery import ResearchArchiveCatalog
from quant_crypto.application.donchian_historical_replay import HistoricalInput
from quant_crypto.application.donchian_history_spec import HistorySpec
from quant_shared.strategy_delivery.models import digest
from quant_shared.strategy_delivery.service import DeliveryService
from tests.contracts.test_strategy_delivery import command


ROOT = Path(__file__).resolve().parents[2]
KEY = "bounded-software-fixture-key"


def _write_json(path: Path, value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _bounded_input(spec: HistorySpec, root: Path) -> HistoricalInput:
    events = pd.date_range(spec.warmup_start, spec.end - timedelta(hours=1), freq="h")
    values = [60_000.0 + index * 8.0 for index in range(len(events))]
    available = events + timedelta(hours=1)
    frame = pd.DataFrame(
        {
            "open_time": events,
            "open": values,
            "high": [value + 1.0 for value in values],
            "low": [value - 1.0 for value in values],
            "close": values,
            "volume": 1.0,
        },
        index=available,
    )
    selected = pd.DataFrame(
        {
            "event_time": events[-spec.signal_rows :],
            "available_time": available[-spec.signal_rows :],
            "open": values[-spec.signal_rows :],
            "high": [value + 1.0 for value in values[-spec.signal_rows :]],
            "low": [value - 1.0 for value in values[-spec.signal_rows :]],
            "close": values[-spec.signal_rows :],
            "volume": 1.0,
        }
    )
    marks = {
        when.to_pydatetime(): {
            "available_time": ready.to_pydatetime(),
            "open": value,
            "high": value + 1.0,
            "low": value - 1.0,
            "close": value,
        }
        for when, ready, value in zip(events, available, values, strict=True)
    }
    premium = {
        when.to_pydatetime(): {
            "available_time": ready.to_pydatetime(),
            "index_close": value,
        }
        for when, ready, value in zip(events, available, values, strict=True)
    }
    data = spec.payload["data"]
    return HistoricalInput(
        manifest={
            "dataset_id": data["dataset_id"],
            "dataset_version": data["dataset_version"],
            "aggregate_sha256": data["aggregate_sha256"],
        },
        manifest_sha256=data["manifest_sha256"],
        dataset_root=root,
        frame=frame,
        signal_rows=selected,
        mark_by_event=marks,
        premium_by_event=premium,
        funding_events=(),
    )


def _fixture(tmp_path: Path, monkeypatch):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    spec_git = f"{head}:{HISTORY_SPEC}"
    committed_spec = HistorySpec.from_git(ROOT, spec_git)
    bounded_payload = committed_spec.payload
    bounded_payload["window"]["evaluation_end"] = (
        committed_spec.start + timedelta(hours=2)
    ).isoformat()
    spec = HistorySpec.from_payload(
        bounded_payload,
        git_spec=spec_git,
        blob_sha256=hashlib.sha256(
            json.dumps(bounded_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    historical_input = _bounded_input(spec, tmp_path / "synthetic-data")

    original_rule = ResearchDeliverySources._rule

    def bounded_rule(self, ref):
        package = original_rule(self, ref)
        package["execution_binding"] = spec.payload
        package["limitations"] = [
            *package["limitations"],
            "bounded_two_bar_synthetic_software_fixture",
        ]
        return package

    monkeypatch.setattr(ResearchDeliverySources, "_rule", bounded_rule)

    management = tmp_path / "management"
    output_root = tmp_path / "economic-history"
    accounts_path = management / "accounts.json"
    _write_json(
        accounts_path,
        {
            "schema_version": "delivery_account_catalog_v1",
            "accounts": [
                {
                    "account_ref": "history-fixture-account",
                    "environment": "offline",
                    "simulation_namespace": "history-fixture",
                    "revision": 1,
                    "market": "crypto",
                    "instruments": ["BTC-USDT-SWAP"],
                    "currency": "USDT",
                    "expires_at": "2027-01-01T00:00:00+00:00",
                    "offline_runtime": {
                        "schema_version": "delivery_offline_runtime_v2",
                        "adapter_id": "btc_donchian_history_offline_v1",
                        "output_root": str(output_root.resolve()),
                        "run_id": "history-fixture-run",
                        "initial_equity_usdt": 5000,
                        "currency": "USDT",
                        "equity_unit": "USDT",
                    },
                }
            ],
        },
    )
    input_row = {
        "schema_version": "candidate_offline_donchian_history_v1",
        "input_revision_id": "history-fixture-input",
        "evidence_kind": "verified_historical_observations",
        "input_head": head,
        "history_spec_git": spec_git,
        "history_spec_blob_sha256": spec.blob_sha256,
        "history_spec_digest": spec.digest,
    }
    input_row["content_digest"] = digest(input_row)
    catalog = {
        "schema_version": "candidate_offline_catalog_v1",
        "repository_owner": digest({"repository": str(ROOT.resolve())}),
        "revision": "history-fixture-v1",
        "factory_root": "factory",
        "qlib_root": "qlib",
        "sources": [],
        "inputs": [input_row],
    }
    catalog_path = tmp_path / "catalog" / "offline-catalog.json"
    catalog_hash = _write_json(catalog_path, catalog)
    inputs = OfflineInputs(catalog_path, catalog_hash, "history-fixture-v1", repo=ROOT)

    archive = ResearchArchiveCatalog(repo_root=ROOT)
    factory = AlphaFactoryService(
        root=tmp_path / "factory",
        qlib_root=tmp_path / "qlib",
        queue=None,
        readonly_archive=archive,
    )
    sources = ResearchDeliverySources(
        ROOT,
        archive=archive,
        qlib_root=tmp_path / "qlib",
        factory_reader=factory,
    )
    accounts = DeliveryAccounts(accounts_path, repo_root=ROOT)
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    delivery = DeliveryService(
        DeliveryStore(management, digest({"repository": str(ROOT.resolve())})),
        sources,
        accounts,
        head=head,
        clock=lambda: now,
    )
    strategy = spec.payload["strategy"]
    source = {
        "kind": "registered_rule",
        "run_id": "donchian-long-50usdt-20260921",
        "candidate_id": strategy["candidate_id"],
    }
    row = delivery.create(source, "offline", key="create-history", actor="operator")
    row = command(delivery, row, "bind", account_ref="history-fixture-account")
    row = command(
        delivery,
        row,
        "review",
        decision="approve",
        reason="bounded software lifecycle test only",
    )
    row = command(delivery, row, "register")

    original_load = OfflineInputs.load
    load_calls = []

    def bounded_load(self, identity, expected):
        if self is not inputs:
            return original_load(self, identity, expected)
        observed = [
            value
            for value in self.catalog()["inputs"]
            if value["input_revision_id"] == identity
        ]
        assert observed == [input_row]
        assert expected == input_row["content_digest"]
        load_calls.append((identity, expected))
        return deepcopy(input_row), {
            "input_kind": "donchian_history",
            "history_spec": spec,
            "historical_input": historical_input,
        }

    monkeypatch.setattr(OfflineInputs, "load", bounded_load)
    offline = CandidateOfflineService(
        delivery,
        inputs,
        None,
        OfflineStore(management, digest({"repository": str(ROOT.resolve())})),
        profile="candidate_management",
        enabled=True,
        operator="operator",
        management_key=KEY,
    )
    body = {
        "registration_id": row["id"],
        "content_digest": row["content_digest"],
        "expected_revision": row["revision"],
        "input_revision_id": input_row["input_revision_id"],
        "input_digest": input_row["content_digest"],
    }
    return offline, row, input_row, body, output_root, load_calls


def _wait(offline: CandidateOfflineService, job_id: str, timeout: float = 120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = offline.status(job_id)
        if value["status"] in {"complete", "blocked", "interrupted", "stopped"}:
            return value
        time.sleep(0.05)
    raise AssertionError(f"offline worker timeout: {offline.status(job_id)}")


def test_public_registered_driver_rejects_wrong_output_root_before_economics(
    tmp_path: Path, monkeypatch
) -> None:
    from quant_crypto.application.btc_registered_donchian import (
        open_btc_registered_donchian_offline,
    )
    from quant_shared.strategy_delivery.models import DeliveryError

    offline, row, input_row, _body, _output_root, _load_calls = _fixture(
        tmp_path, monkeypatch
    )
    _catalog_row, loaded = offline.inputs.load(
        input_row["input_revision_id"], input_row["content_digest"]
    )
    wrong_root = tmp_path / "wrong-economic-root"
    with pytest.raises(
        DeliveryError, match="registered_donchian_runtime_location_mismatch"
    ):
        open_btc_registered_donchian_offline(
            offline.delivery,
            row["id"],
            content_digest=row["content_digest"],
            account_identity_hash=row["binding"]["identity_hash"],
            adapter_id="btc_donchian_history_offline_v1",
            runtime_binding=row["binding"]["offline_runtime"],
            output_root=wrong_root,
            run_id=row["binding"]["offline_runtime"]["run_id"],
            repo_root=ROOT,
            history_spec=loaded["history_spec"],
            historical_input=loaded["historical_input"],
        )
    assert not wrong_root.exists()


def test_real_history_replay_risk_oms_ledger_and_terminal_are_coordinated(
    tmp_path: Path, monkeypatch
) -> None:
    offline, row, input_row, body, output_root, load_calls = _fixture(tmp_path, monkeypatch)
    original_update = offline._update
    failed_once = False

    def fail_after_authoritative_event(identity, generation, *, receipt=None, **changes):
        nonlocal failed_once
        if receipt is not None and changes.get("cursor") == 1 and not failed_once:
            failed_once = True
            raise RuntimeError("fixture_projection_commit_interruption")
        return original_update(identity, generation, receipt=receipt, **changes)

    monkeypatch.setattr(offline, "_update", fail_after_authoritative_event)
    started = offline.start(body, key="start-history", credential=KEY)
    interrupted = _wait(offline, started["job_id"])
    assert interrupted["status"] == "interrupted"
    assert interrupted["cursor"] == 0
    run_root = output_root / "history-fixture-run"
    persisted = json.loads((run_root / "historical_replay.json").read_text(encoding="utf-8"))
    venue_after_first = json.loads(
        (run_root / "state" / "offline_venue.json").read_text(encoding="utf-8")
    )
    assert len(persisted["events"]) == 1
    assert len(venue_after_first["orders"]) == len(venue_after_first["fills"]) == 1
    assert len(load_calls) == 1

    monkeypatch.setattr(offline, "_update", original_update)
    resumed = offline.command(
        started["job_id"],
        "resume",
        expected_revision=interrupted["revision"],
        key="resume-history",
        credential=KEY,
    )
    assert resumed["status"] == "queued"
    terminal = _wait(offline, started["job_id"])
    assert terminal["status"] == "complete", {
        key: terminal.get(key)
        for key in ("status", "blocker", "cursor", "total", "revision")
    }
    assert terminal["cursor"] == terminal["total"] == 2
    assert len(load_calls) == 2

    linked = offline.result(started["job_id"])
    result = linked["result"]
    assert result["adapter_id"] == "btc_donchian_history_offline_v1"
    assert result["fill_count"] >= 1
    assert result["fill_count"] == len(result["fills"]) == 1
    assert result["position_contracts"] == "0.01"
    assert result["ledger"]["status"] == "reconciled"
    assert result["history_phases"][-1]["phase"] == "no_next_bar"
    assert result["history_phases"][-1]["decision_outcome"] == "unfilled_no_next_bar"
    assert not any(linked[name].get(flag, False) for name in ("job", "result") for flag in (
        "promotion", "paper", "live", "private", "order", "real_order", "withdraw"
    ))
    assert len(linked["decisions"]) == 2
    assert result["finalized"] is True
    assert result["artifact_status"] == "complete"
    assert result["marked_state"]["equity_usdt"] == result["ledger"]["final_equity_usdt"]
    assert result["marked_state"]["position_contracts"] == result["ledger"]["position_contracts"]
    assert result["ledger"]["fill_count"] == result["fill_count"]
    assert result["marked_state"]["position_contracts"] == result["position_contracts"]
    assert (run_root / "historical_replay.json").is_file()
    assert row["permissions"]["execution_permission"] is False
    assert input_row["evidence_kind"] == "verified_historical_observations"
