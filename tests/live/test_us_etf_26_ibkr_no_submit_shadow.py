from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import subprocess

import pandas as pd
import pytest

from quant_us.execution.ibkr_broker import IBKRBroker, IBKRBrokerConfig
from quant_us.live.us_etf_26_ibkr_no_submit_shadow import (
    ShadowEvidenceError,
    account_sha256,
    build_no_submit_shadow,
    committed_frozen_strategy_identity,
    validate_no_submit_shadow_artifact,
)
from scripts.run_us_equity_ibkr_paper import (
    compose_exact_candidate_no_submit_shadow,
    main as paper_main,
)
from tools.agent_governance.shared_data import build_manifest, inventory_directory


ROOT = Path(__file__).resolve().parents[2]
OBSERVED_AT = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
RAW_ACCOUNT = "DU1234567"
ACCOUNT_HASH = account_sha256(RAW_ACCOUNT)
DATASET_VERSION = "us-equity-public-forward-snapshot-fixture-v1"
MANIFEST_RELATIVE = (
    ".agent/data_manifests/us-equity-public-forward-snapshot/"
    f"{DATASET_VERSION}.json"
)


class FakeReadClient:
    def __init__(self, *, raw_account: str = RAW_ACCOUNT, connected: bool = True) -> None:
        self.raw_account = raw_account
        self.connected = connected
        self.connect_calls = 0
        self.account_calls = 0
        self.position_calls = 0
        self.order_calls = 0
        self.fill_calls = 0
        self.submit_calls = 0
        self.cancel_calls = 0
        self.global_cancel_calls = 0

    def connect(self, *_args: object, **_kwargs: object) -> bool:
        self.connect_calls += 1
        self.connected = True
        return True

    def isConnected(self) -> bool:
        return self.connected

    def accountSummary(self) -> list[SimpleNamespace]:
        self.account_calls += 1
        return [
            SimpleNamespace(account=self.raw_account, tag="NetLiquidation", value="100000"),
            SimpleNamespace(account=self.raw_account, tag="TotalCashValue", value="100000"),
            SimpleNamespace(account=self.raw_account, tag="BuyingPower", value="200000"),
        ]

    def positions(self) -> list[SimpleNamespace]:
        self.position_calls += 1
        return [
            SimpleNamespace(
                account=self.raw_account,
                contract=SimpleNamespace(symbol="SPY"),
                position=1.0,
                avgCost=500.0,
                marketPrice=501.0,
                unrealizedPNL=1.0,
            )
        ]

    def openTrades(self) -> list[SimpleNamespace]:
        self.order_calls += 1
        return [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="SPY"),
                order=SimpleNamespace(
                    orderId=42,
                    action="BUY",
                    totalQuantity=1,
                    orderType="LMT",
                    tif="DAY",
                    lmtPrice=500.0,
                    orderRef="readonly-existing-42",
                ),
                orderStatus=SimpleNamespace(status="Submitted"),
            )
        ]

    def fills(self) -> list[SimpleNamespace]:
        self.fill_calls += 1
        return [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="SPY"),
                execution=SimpleNamespace(
                    orderId=41,
                    side="BOT",
                    shares=1,
                    price=499.0,
                    time=OBSERVED_AT - timedelta(hours=2),
                    execId="exec-41",
                ),
                commissionReport=SimpleNamespace(commission=1.0),
            )
        ]

    def write_call_counters(self) -> dict[str, int]:
        return {
            "submit": self.submit_calls,
            "cancel": self.cancel_calls,
            "global_cancel": self.global_cancel_calls,
        }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "fixture-repo"
    shared = tmp_path / "external-shared"
    repo.mkdir()
    shared.mkdir()
    _write_json(
        shared / ".qs_shared_data_root_owner.json",
        {
            "schema_version": "qs_shared_data_root_owner_v2",
            "owner_domain": "quant-system-agent",
            "root_semantics": "external_immutable_shared_data_root",
            "logical_prefix": "datasets/",
            "repository_identity": "sha256:" + "a" * 64,
        },
    )
    freeze_target = repo / "configs/strategies/us_etf_26_candidate_freeze_v1.json"
    freeze_target.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "configs/strategies/us_etf_26_candidate_freeze_v1.json", freeze_target)
    schema_target = repo / "schemas/us_etf_26_ibkr_no_submit_shadow.schema.json"
    schema_target.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "schemas/us_etf_26_ibkr_no_submit_shadow.schema.json", schema_target)

    dataset = shared / "datasets/us-equity-public-forward-snapshot" / DATASET_VERSION
    yahoo = dataset / "yahoo"
    yahoo.mkdir(parents=True)
    sessions = pd.bdate_range(end="2026-08-05", periods=300, tz="UTC") + pd.Timedelta(hours=20)
    close = pd.Series([100.0 + index * 0.2 for index in range(len(sessions))])
    close.iloc[-1] += 10.0
    frame = pd.DataFrame({
        "symbol": "QQQ",
        "decision_time_utc": sessions.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "available_time_utc": "2026-08-06T11:00:00Z",
        "Open": close - 0.2,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Adj Close": close * 0.5,
        "Volume": 1_000_000.0,
        "adjustment_ratio": 0.5,
    })
    qqq_path = yahoo / "QQQ_1D.csv"
    frame.to_csv(qqq_path, index=False, lineterminator="\n")
    qqq_hash = _sha256(qqq_path)
    _write_json(
        yahoo / "lineage.json",
        {
            "schema_version": "us_equity_yahoo_daily_snapshot_manifest_v1",
            "symbol": "QQQ",
            "timeframe": "1D",
            "data_file_path": "yahoo/QQQ_1D.csv",
            "data_file_sha256": qqq_hash,
            "source_commit": "2" * 40,
            "adjustment": {
                "policy": "provider_adjusted_close_with_raw_ohlcv_and_policy_recorded",
                "strategy_price_semantics": "provider_adjusted_ohlc_via_session_ratio",
            },
            "guardrails": {
                "immutable": True,
                "snapshot_complete": True,
                "consumer_network_access_allowed": False,
                "promotion_evidence_ready": False,
            },
        },
    )
    (dataset / "fred_macro_latest_vintage.csv").write_text(
        "date,DGS10\n2026-08-05,4.20\n", encoding="utf-8"
    )
    files, aggregate, total_bytes = inventory_directory(dataset)
    manifest = build_manifest(
        dataset_id="us-equity-public-forward-snapshot",
        dataset_version=DATASET_VERSION,
        readiness_class="quality_checked",
        quality_status="pass_with_research_only_warnings",
        files=files,
        aggregate_sha256=aggregate,
        total_bytes=total_bytes,
        producer_commit="1" * 40,
        known_gaps=[
            "yahoo_survivorship_bias_and_current_adjustment_vintage",
            "fred_latest_vintage_non_pit_without_realtime_bounds",
            "historical_counterfactual_replay_not_supported",
        ],
        schema_name="us_equity_public_forward_snapshot_lineage_v1",
        coverage_start="2025-06-13T20:00:00Z",
        coverage_end="2026-08-05T20:00:00Z",
        published_at="2026-08-06T11:30:00Z",
    )
    _write_json(dataset / "_dataset_manifest.json", manifest)
    _write_json(repo / MANIFEST_RELATIVE, manifest)

    _git(repo, "init")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "add", "configs", "schemas", ".agent")
    _git(repo, "commit", "-m", "fixture")
    return repo, shared, _git(repo, "rev-parse", "HEAD")


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _broker(client: FakeReadClient, port: int = 4002) -> IBKRBroker:
    return IBKRBroker(IBKRBrokerConfig(port=port), client=client)


def test_shadow_replays_full_chain_and_proves_zero_write_surface(tmp_path: Path) -> None:
    repo, shared, head = _fixture(tmp_path)
    client = FakeReadClient()
    payload = build_no_submit_shadow(
        broker_factory=lambda: _broker(client),
        repo_root=repo,
        shared_data_root=shared,
        expected_account_hash=ACCOUNT_HASH,
        observed_at_utc=OBSERVED_AT,
    )
    assert payload["code_head"] == head
    assert payload["bindings"]["dataset_id"] == "us-equity-public-forward-snapshot"
    assert payload["bindings"]["dataset_version"] == DATASET_VERSION
    assert payload["bindings"]["yahoo_file_path"] == "yahoo/QQQ_1D.csv"
    assert payload["bindings"]["yahoo_lineage_path"] == "yahoo/lineage.json"
    assert payload["identity"]["candidate_id"] == "us-etf26-complete-return-qqq-1d-v1"
    assert payload["decision"]["target_position"]["target_weight"] == 3.0
    assert payload["decision"]["portfolio_targets"][0]["target_weight"] == 0.1
    assert len(payload["decision"]["order_intents"]) == 1
    assert len(payload["decision"]["risk_decisions"]) == 1
    assert len(payload["account_snapshot"]["open_orders"]) == 1
    assert len(payload["account_snapshot"]["fills"]) == 1
    assert payload["write_counters"] == {
        "submit_call_count": 0,
        "cancel_call_count": 0,
        "global_cancel_call_count": 0,
        "submit_attempt_count": 0,
        "cancel_attempt_count": 0,
        "submit_call_count_delta": 0,
        "cancel_call_count_delta": 0,
        "global_cancel_call_count_delta": 0,
        "submit_attempt_count_delta": 0,
        "cancel_attempt_count_delta": 0,
    }
    assert all(
        payload["guardrails"][key] is False
        for key in (
            "oms_handle_intent_called",
            "submit_order_called",
            "cancel_order_called",
            "global_cancel_called",
            "promotion_allowed",
            "paper_allowed",
            "live_allowed",
            "private_allowed",
            "order_allowed",
        )
    )
    assert client.connect_calls == 0
    assert client.account_calls == 1
    assert client.position_calls == 2
    assert client.order_calls == client.fill_calls == 1
    rendered = json.dumps(payload, sort_keys=True)
    assert RAW_ACCOUNT not in rendered

    artifact = tmp_path / "shadow.json"
    artifact.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    validated = validate_no_submit_shadow_artifact(
        repo_root=repo,
        artifact_path=artifact,
        shared_data_root=shared,
    )
    assert validated["artifact_sha256"] == payload["artifact_sha256"]


@pytest.mark.parametrize("port", [4002, 7497])
def test_only_paper_ports_compose_without_connect(tmp_path: Path, port: int) -> None:
    repo, shared, _ = _fixture(tmp_path)
    client = FakeReadClient()
    composition = compose_exact_candidate_no_submit_shadow(
        client=client,
        expected_account_hash=ACCOUNT_HASH,
        repo_root=repo,
        shared_data_root=shared,
        strategy_identity=committed_frozen_strategy_identity(repo_root=repo),
        port=port,
    )
    assert client.connect_calls == 0
    payload = composition.run(observed_at_utc=OBSERVED_AT)
    assert payload["foundation"]["port"] == port
    assert client.connect_calls == 0


@pytest.mark.parametrize("port", [4001, 7496])
def test_live_ports_are_rejected_before_client_access(tmp_path: Path, port: int) -> None:
    repo, shared, _ = _fixture(tmp_path)
    client = FakeReadClient()
    with pytest.raises(ValueError, match="ibkr_live_endpoint_forbidden"):
        compose_exact_candidate_no_submit_shadow(
            client=client,
            expected_account_hash=ACCOUNT_HASH,
            repo_root=repo,
            shared_data_root=shared,
            strategy_identity=committed_frozen_strategy_identity(repo_root=repo),
            port=port,
        )
    assert client.connect_calls == client.account_calls == 0


@pytest.mark.parametrize("failure", ["stale", "hash", "manifest", "owner"])
def test_offline_failures_precede_broker_construction(tmp_path: Path, failure: str) -> None:
    repo, shared, _ = _fixture(tmp_path)
    observed = OBSERVED_AT
    if failure == "stale":
        observed += timedelta(days=10)
    elif failure == "hash":
        qqq = shared / "datasets/us-equity-public-forward-snapshot" / DATASET_VERSION / "yahoo/QQQ_1D.csv"
        qqq.write_text(qqq.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif failure == "manifest":
        physical = shared / "datasets/us-equity-public-forward-snapshot" / DATASET_VERSION / "_dataset_manifest.json"
        physical.unlink()
    else:
        (shared / ".qs_shared_data_root_owner.json").unlink()
    factory_calls: list[int] = []
    client = FakeReadClient()

    def factory() -> IBKRBroker:
        factory_calls.append(1)
        return _broker(client)

    with pytest.raises(ShadowEvidenceError):
        build_no_submit_shadow(
            broker_factory=factory,
            repo_root=repo,
            shared_data_root=shared,
            expected_account_hash=ACCOUNT_HASH,
            observed_at_utc=observed,
        )
    assert factory_calls == []
    assert client.account_calls == client.connect_calls == 0


def test_account_hash_mismatch_fails_closed_without_writes(tmp_path: Path) -> None:
    repo, shared, _ = _fixture(tmp_path)
    client = FakeReadClient(raw_account="DU7654321")
    with pytest.raises(ShadowEvidenceError, match="account_hash_mismatch"):
        build_no_submit_shadow(
            broker_factory=lambda: _broker(client),
            repo_root=repo,
            shared_data_root=shared,
            expected_account_hash=ACCOUNT_HASH,
            observed_at_utc=OBSERVED_AT,
        )
    assert client.write_call_counters() == {"submit": 0, "cancel": 0, "global_cancel": 0}
    assert client.connect_calls == 0


def test_import_and_constructor_have_no_network_or_write_calls() -> None:
    module_path = ROOT / "quant_us/live/us_etf_26_ibkr_no_submit_shadow.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_calls = {"connect", "handle_intent", "submit_order", "cancel_order", "globalCancel", "reqGlobalCancel"}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert forbidden_calls.isdisjoint(called)
    client = FakeReadClient(connected=False)
    broker = _broker(client)
    assert client.connect_calls == 0
    assert broker.is_connected() is False


def test_cli_exposes_no_gateway_factory_and_rejects_live_port() -> None:
    with pytest.raises(SystemExit, match="injected_fake_client_required"):
        paper_main([
            "no-submit",
            "--port",
            "4002",
            "--expected-account-hash",
            ACCOUNT_HASH,
            "--shared-data-root",
            "X:/not-used",
        ])
    with pytest.raises(SystemExit):
        paper_main([
            "no-submit",
            "--port",
            "4001",
            "--expected-account-hash",
            ACCOUNT_HASH,
            "--shared-data-root",
            "X:/not-used",
        ])


def test_validator_rejects_tampered_decision_even_when_rehashed(tmp_path: Path) -> None:
    repo, shared, _ = _fixture(tmp_path)
    payload = build_no_submit_shadow(
        broker_factory=lambda: _broker(FakeReadClient()),
        repo_root=repo,
        shared_data_root=shared,
        expected_account_hash=ACCOUNT_HASH,
        observed_at_utc=OBSERVED_AT,
    )
    payload["decision"]["portfolio_targets"][0]["target_weight"] = 0.0
    payload.pop("artifact_sha256")
    import hashlib

    payload["artifact_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    artifact = tmp_path / "tampered.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ShadowEvidenceError):
        validate_no_submit_shadow_artifact(
            repo_root=repo,
            artifact_path=artifact,
            shared_data_root=shared,
        )
