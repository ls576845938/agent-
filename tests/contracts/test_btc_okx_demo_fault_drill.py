from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

import scripts.run_btc_okx_demo_fault_drill as fault_drill_cli
import quant_crypto.application.btc_okx_demo_fault_drill as fault_drill_module
import quant_crypto.oms.okx_demo_paper_runtime as okx_demo_runtime_module
import quant_crypto.oms.runtime_store as runtime_store_module

from quant_crypto.application.btc_okx_demo_fault_drill import (
    DEMO_FAULT_DRILL_SCENARIOS,
    OKX_DOCS_REVIEW_METADATA,
    BtcOkxDemoFaultDrillConfig,
    BtcOkxDemoFaultDrillService,
    BtcOkxDemoFailedReceiptBinding,
    FaultDrillReceiptError,
)
from quant_crypto.application.btc_strategy_registry import btc_strategy_registry
from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperStartRequest
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.runtime.control_plane import BTCDemoExecutionDispatcher


_FIXTURE_USE_EVENT_SOURCE_HEAD = object()


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class FakeRuntime:
    def __init__(
        self,
        *,
        post: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> None:
        self.run_calls: list[str] = []
        self.freeze_calls: list[str] = []
        self._post = dict(post or _snapshot())
        self._result = dict(result or {})

    def fault_drill_snapshot(self) -> dict[str, Any]:
        return _snapshot() if not self.run_calls else dict(self._post)

    def run_fault_drill_scenario(
        self,
        scenario: str,
        *,
        fault_injector: Any,
        authorization: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.run_calls.append(scenario)
        assert authorization["execute_demo"] is True
        fault_injector.record("actual_demo_fault_injected", scenario=scenario)
        return {
            "clOrdId": "btcDPdrill0001",
            "algoClOrdId": "btcDPdrill0001A",
            "orders_posted": 1,
            **self._result,
        }

    def freeze_fault_drill(self, reason: str) -> None:
        self.freeze_calls.append(reason)


class FilledThenRaisedRuntime:
    """Expose the real exchange side effect even when the runtime raises."""

    def __init__(self) -> None:
        self.run_calls = 0
        self.freeze_calls: list[str] = []

    def fault_drill_snapshot(self) -> dict[str, Any]:
        snapshot = _snapshot()
        if self.run_calls:
            snapshot["exchange"]["orders"] = [
                {
                    "order_id": "order-filled-after-response-loss",
                    "client_order_id": "btcDPowned0001",
                    "state": "filled",
                }
            ]
            snapshot["exchange"]["fills"] = [
                {
                    "fill_id": "fill-filled-after-response-loss",
                    "client_order_id": "btcDPowned0001",
                    "size": "0.01",
                }
            ]
            snapshot["exchange"]["positions"] = [
                {"position_side": "long", "contracts": "0.01"}
            ]
        return snapshot

    def run_fault_drill_scenario(
        self,
        scenario: str,
        *,
        fault_injector: Any,
        authorization: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del authorization
        assert scenario == "post_response_loss"
        self.run_calls += 1
        fault_injector.record(
            "risk_oms_opening_path_entered",
            clOrdId="btcDPowned0001",
            algoClOrdId="btcDPowned0001A",
        )
        raise RuntimeError("response_lost_after_exchange_fill")

    def freeze_fault_drill(self, reason: str) -> None:
        self.freeze_calls.append(reason)


def _snapshot(*, contracts: str = "0") -> dict[str, Any]:
    return {
        "runtime": {
            "run_id": "runtime-1",
            "active": True,
            "opening_allowed": True,
            "last_reconciled_at_utc": "2026-08-05T00:00:00+00:00",
        },
        "risk_control": {
            "pending_order_intents": {},
            "mode": "RUNNING",
            "dead_man": {"armed": True},
        },
        "private_ws": {
            "connected": True,
            "listener_alive": True,
            "opening_allowed_after_reconciliation": True,
        },
        "exchange": {
            "orders": [],
            "fills": [],
            "positions": [] if contracts == "0" else [{"position_side": "long", "contracts": contracts}],
            "pending_orders": [],
            "pending_algo_orders": [],
        },
        "ledger_reconciliation": {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
            "ledger_hash": "a" * 64,
        },
    }


def _config(tmp_path: Path, source_head: str, scenario: str, *, execute: bool) -> BtcOkxDemoFaultDrillConfig:
    return BtcOkxDemoFaultDrillConfig(
        repo_root=Path.cwd(),
        receipt_external_root=tmp_path.resolve(),
        source_head=source_head,
        scenario=scenario,
        run_id=f"run-{scenario}",
        execute_demo=execute,
        environment="OKX Demo",
        instrument_id="BTC-USDT-SWAP",
        margin_mode="isolated",
        leverage="3",
        order_contracts=("0.03" if scenario == "partial_fill_disconnect" else "0.01"),
        max_notional_usdt=(
            "25" if scenario == "partial_fill_disconnect" else "10"
        ),
        partial_fill_reference_price_usdt=(
            "64600" if scenario == "partial_fill_disconnect" else ""
        ),
        confirm_dedicated_demo_account=True,
    )


def _flat_hosted_exit_bundle_fixture(tmp_path: Path) -> dict[str, Any]:
    """Minimal immutable source bundle; no runtime root or provider exists."""

    head = _head()
    sources = tmp_path / "immutable-sources"
    sources.mkdir()
    failed = {
        "schema_version": "btc_okx_demo_fault_drill_receipt_v1",
        "source_head": head,
        "scenario": "post_response_loss",
        "run_id": "20a8d165b75949759f4c8e7eee6d0c8d",
        "orders_posted": 1,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
        "credentials_redacted": True,
        "post_snapshot": {
            "orders": [{"clOrdId": "btcDP20a8d1650001", "order_id": "3816659792351170560", "state": "filled"}],
            "fills": [{"clOrdId": "btcDP20a8d1650001", "order_id": "3816659792351170560", "fill_id": "4322812521", "size": "0.01"}],
            "pending_algo_orders": [{"algoClOrdId": "btcDP20a8d1650001A", "algo_id": "3816659794069377024", "state": "live"}],
        },
    }
    known = {
        "entry_cl_ord_id": "btcDP20a8d1650001",
        "entry_ord_id": "3816659792351170560",
        "oco_algo_cl_ord_id": "btcDP20a8d1650001A",
        "oco_algo_id": "3816659794069377024",
        "entry_orders": [{"clOrdId": "btcDP20a8d1650001", "ordId": "3816659792351170560", "side": "buy", "posSide": "long", "state": "filled", "sz": "0.01", "accFillSz": "0.01"}],
        "entry_fills": [{"clOrdId": "btcDP20a8d1650001", "ordId": "3816659792351170560", "side": "buy", "posSide": "long", "fillSz": "0.01", "ts": "1786247725627"}],
        "exact_oco_detail": [{"algoClOrdId": "btcDP20a8d1650001A", "algoId": "3816659794069377024", "ordType": "oco", "state": "effective", "reduceOnly": "true", "side": "sell", "posSide": "long", "sz": "0.01"}],
        "exact_oco_history": [{"algoClOrdId": "btcDP20a8d1650001A", "algoId": "3816659794069377024", "ordType": "oco", "state": "effective", "reduceOnly": "true", "side": "sell", "posSide": "long", "sz": "0.01"}],
    }
    fresh = {
        "schema_version": "btc_okx_demo_fresh_broker_truth_receipt_v2", "main_head": head,
        "environment": "OKX Demo", "instrument_id": "BTC-USDT-SWAP", "status": "blocked_fail_closed",
        "payload_sha256": "a" * 64, "exchange_order_post_count": 0, "exchange_cancel_post_count": 0,
        "exchange_transfer_post_count": 0, "exchange_withdraw_post_count": 0, "physical_non_get_count": 0,
        "rest": {"known_identity": known, "positions": [{"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "posSide": "long", "pos": "0"}], "ordinary_pending": {"count": 0}, "conditional_pending": {"count": 0}, "oco_pending": {"count": 0}, "account": {"position_mode": "long_short_mode", "withdraw_permission_present": False}, "leverage": [{"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "lever": "3", "posSide": "long"}, {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "lever": "3", "posSide": "short"}], "funding_bills": {"bills": [{"instId": "BTC-USDT-SWAP"}]}},
    }
    diagnostic = {
        "schema_version": "btc_okx_demo_fill_identity_diagnostic_v1", "main_head": head,
        "environment": "OKX Demo", "instrument_id": "BTC-USDT-SWAP", "status": "blocked_fail_closed",
        "payload_sha256": "b" * 64, "exchange_order_post_count": 0, "exchange_cancel_post_count": 0,
        "exchange_transfer_post_count": 0, "exchange_withdraw_post_count": 0, "non_get_count": 0,
        "fills": [{"clOrdId": "O3821053454550453248", "ordId": "3821053454707298304", "fillId": "", "instId": "BTC-USDT-SWAP", "side": "sell", "posSide": "long", "fillSz": "0.01", "ts": "1786378666918"}],
    }
    exit_order = {
        "schema_version": "btc_okx_demo_unknown_fill_exact_order_receipt_v1", "main_head": head,
        "environment": "OKX Demo", "instrument_id": "BTC-USDT-SWAP", "status": "blocked_fail_closed",
        "payload_sha256": "c" * 64, "exchange_order_post_count": 0, "exchange_cancel_post_count": 0,
        "exchange_transfer_post_count": 0, "exchange_withdraw_post_count": 0, "non_get_count": 0,
        "known_oco": {"algo_cl_ord_id": "btcDP20a8d1650001A", "algo_id": "3816659794069377024"},
        "order": {"clOrdId": "O3821053454550453248", "ordId": "3821053454707298304", "algoClOrdId": "btcDP20a8d1650001A", "algoId": "3816659794069377024", "state": "filled", "ordType": "market", "reduceOnly": "true", "side": "sell", "posSide": "long", "sz": "0.01", "accFillSz": "0.01", "uTime": "1786378666918"},
    }
    documents = {"failed": failed, "fresh": fresh, "diagnostic": diagnostic, "order": exit_order}
    paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for name, document in documents.items():
        path = sources / f"{name}.json"
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        paths[name] = path
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "failed_receipt_path": paths["failed"], "failed_receipt_sha256": hashes["failed"],
        "fresh_truth_path": paths["fresh"], "fresh_truth_sha256": hashes["fresh"], "fresh_truth_payload_sha256": "a" * 64,
        "fill_diagnostic_path": paths["diagnostic"], "fill_diagnostic_sha256": hashes["diagnostic"], "fill_diagnostic_payload_sha256": "b" * 64,
        "exit_order_path": paths["order"], "exit_order_sha256": hashes["order"], "exit_order_payload_sha256": "c" * 64,
        "binding_external_root": tmp_path / "external-bindings", "repo_root": Path.cwd(),
    }


def test_flat_hosted_exit_bundle_publishes_only_exact_derived_identity(tmp_path: Path) -> None:
    kwargs = _flat_hosted_exit_bundle_fixture(tmp_path)
    binding = BtcOkxDemoFailedReceiptBinding.load_flat_hosted_exit_bundle(**kwargs)
    assert binding.recovery_mode == "already_flat"
    assert binding.binding_source == "immutable_flat_hosted_exit_receipt_bundle"
    assert binding.opening_cl_ord_id == "btcDP20a8d1650001"
    assert binding.expected_close_cl_ord_id == "O3821053454550453248"
    assert binding.binding_path is not None and binding.binding_path.is_file()
    document = json.loads(binding.binding_path.read_text(encoding="utf-8"))
    assert document["safety"]["order_allowed"] is False
    assert (binding.binding_path.parent / "sources" / "exit_order.json").is_file()
    controller = object.__new__(okx_demo_runtime_module.OkxDemoPaperRuntimeController)
    controller.config = SimpleNamespace(repo_root=Path.cwd())
    authorization = binding.runtime_authorization(runtime_source_head=_head())
    assert controller._incident_recovery_binding_blockers(authorization) == []
    source_copy = binding.binding_path.parent / "sources" / "exit_order.json"
    source_copy.write_text("{}", encoding="utf-8")
    assert controller._incident_recovery_binding_blockers(authorization) == [
        "okx_demo_flat_hosted_exit_binding_source_hash_mismatch"
    ]
    with pytest.raises(FaultDrillReceiptError, match="binding_already_exists"):
        BtcOkxDemoFailedReceiptBinding.load_flat_hosted_exit_bundle(**kwargs)


def test_flat_hosted_exit_bundle_accepts_only_real_private_ws_blocked_fresh_receipt(
    tmp_path: Path,
) -> None:
    kwargs = _flat_hosted_exit_bundle_fixture(tmp_path)
    fresh_path = kwargs["fresh_truth_path"]
    fresh = json.loads(fresh_path.read_text(encoding="utf-8"))
    fresh.update(
        {
            "status": "blocked",
            "blockers": ["private_ws_reconciliation_not_current"],
        }
    )
    fresh_path.write_text(json.dumps(fresh, sort_keys=True), encoding="utf-8")
    kwargs["fresh_truth_sha256"] = hashlib.sha256(
        fresh_path.read_bytes()
    ).hexdigest()

    binding = BtcOkxDemoFailedReceiptBinding.load_flat_hosted_exit_bundle(**kwargs)

    assert binding.binding_path is not None and binding.binding_path.is_file()
    assert binding.recovery_mode == "already_flat"


@pytest.mark.parametrize(
    ("target", "mutation"),
    (
        (
            "fresh",
            lambda doc: doc.update(
                {
                    "status": "blocked",
                    "blockers": ["private_ws_reconciliation_not_current", "foreign"],
                }
            ),
        ),
        (
            "fresh",
            lambda doc: doc.update(
                {"status": "blocked", "blockers": ["foreign_blocker"]}
            ),
        ),
        (
            "fresh",
            lambda doc: doc.update({"physical_non_get_count": 1}),
        ),
        (
            "fresh",
            lambda doc: doc.update({"exchange_order_post_count": 1}),
        ),
        (
            "diagnostic",
            lambda doc: doc.update({"status": "blocked"}),
        ),
    ),
)
def test_flat_hosted_exit_bundle_rejects_other_blocked_or_non_readonly_status(
    tmp_path: Path,
    target: str,
    mutation: Any,
) -> None:
    kwargs = _flat_hosted_exit_bundle_fixture(tmp_path)
    path_key = "fresh_truth_path" if target == "fresh" else "fill_diagnostic_path"
    hash_key = (
        "fresh_truth_sha256"
        if target == "fresh"
        else "fill_diagnostic_sha256"
    )
    path = kwargs[path_key]
    document = json.loads(path.read_text(encoding="utf-8"))
    mutation(document)
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    kwargs[hash_key] = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_flat_hosted_exit_readonly_receipt_invalid",
    ):
        BtcOkxDemoFailedReceiptBinding.load_flat_hosted_exit_bundle(**kwargs)
    assert not kwargs["binding_external_root"].exists()


@pytest.mark.parametrize("mutate", ["exit_side", "entry_fill", "exit_time"])
def test_flat_hosted_exit_bundle_rejects_tampered_identity_before_publish(
    tmp_path: Path,
    mutate: str,
) -> None:
    kwargs = _flat_hosted_exit_bundle_fixture(tmp_path)
    if mutate == "entry_fill":
        path = kwargs["failed_receipt_path"]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["post_snapshot"]["fills"][0]["fill_id"] = "foreign"
        hash_key = "failed_receipt_sha256"
    elif mutate == "exit_side":
        path = kwargs["exit_order_path"]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["order"]["side"] = "buy"
        hash_key = "exit_order_sha256"
    else:
        path = kwargs["fill_diagnostic_path"]
        document = json.loads(path.read_text(encoding="utf-8"))
        document["fills"][0]["ts"] = "1"
        hash_key = "fill_diagnostic_sha256"
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    kwargs[hash_key] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FaultDrillReceiptError, match="flat_hosted_exit"):
        BtcOkxDemoFailedReceiptBinding.load_flat_hosted_exit_bundle(**kwargs)
    assert not list(kwargs["binding_external_root"].rglob("binding.json")) if kwargs["binding_external_root"].exists() else True


def test_cli_partial_start_binds_dedicated_0p03_25_envelope() -> None:
    class CaptureRuntime:
        def __init__(self) -> None:
            self.payload: Mapping[str, Any] = {}

        def start(self, payload: Mapping[str, Any]) -> None:
            self.payload = dict(payload)

    args = SimpleNamespace(
        scenario="partial_fill_disconnect",
        strategy_id="long_short_donchian_top5",
        candidate_id=btc_strategy_registry.get("long_short_donchian_top5").candidate_id,
        strategy_version=btc_strategy_registry.get("long_short_donchian_top5").strategy_version,
        max_notional_usdt="25",
    )
    runtime = CaptureRuntime()

    fault_drill_cli._start_runtime(runtime, args)  # type: ignore[arg-type]

    assert runtime.payload["fault_drill_scenario"] == "partial_fill_disconnect"
    assert runtime.payload["order_contracts"] == "0.03"
    assert runtime.payload["max_net_contracts"] == "0.03"
    assert runtime.payload["max_notional_usdt"] == "25"


def _terminal_lifecycle(**overrides: bool) -> dict[str, bool]:
    lifecycle = {
        "terminal": True,
        "postflight_complete": True,
        "startup_failed": False,
        "runtime_not_constructed": False,
        "runtime_clean_stop": True,
        "threads_joined": True,
        "dead_man_disarmed": True,
        "writer_lock_released": True,
        "cleanup_complete": True,
        "receipt_written_after_cleanup": True,
    }
    lifecycle.update(overrides)
    return lifecycle


def _native_cli_args(tmp_path: Path) -> list[str]:
    spec = btc_strategy_registry.get("long_short_donchian_top5_okx_native")
    return [
        "--scenario",
        "held_position_disconnect",
        "--run-id",
        "native-data-binding",
        "--source-head",
        _head(),
        "--receipt-external-root",
        str(tmp_path.resolve()),
        "--environment",
        "OKX Demo",
        "--instrument-id",
        "BTC-USDT-SWAP",
        "--margin-mode",
        "isolated",
        "--leverage",
        "3",
        "--order-contracts",
        "0.01",
        "--max-notional-usdt",
        "10",
        "--confirm-dedicated-demo-account",
        "--execute-demo",
        "--data-db-path",
        str(tmp_path / "unused.sqlite"),
        "--runtime-output-dir",
        str(tmp_path / "runtime"),
        "--strategy-id",
        spec.strategy_id,
        "--candidate-id",
        spec.candidate_id,
        "--strategy-version",
        spec.strategy_version,
        "--okx-native-shared-manifest-git-spec",
        "feedface:.agent/data_manifests/btc-okx-native.json",
        "--okx-native-shared-data-root",
        str(tmp_path / "private-physical-shared-root"),
        "--okx-native-expected-dataset-id",
        "btc-okx-native-hourly-v1",
    ]


def _incident_cli_args(tmp_path: Path) -> list[str]:
    argv = _native_cli_args(tmp_path)
    argv[argv.index("--scenario") + 1] = "post_response_loss"
    argv[argv.index("--strategy-id") + 1] = "long_short_donchian_top5"
    for flag in (
        "--okx-native-shared-manifest-git-spec",
        "--okx-native-shared-data-root",
        "--okx-native-expected-dataset-id",
    ):
        index = argv.index(flag)
        del argv[index : index + 2]
    argv.extend(
        [
            "--incident-recovery-failed-receipt",
            str(tmp_path / "failed.json"),
            "--incident-recovery-failed-receipt-sha256",
            "a" * 64,
            "--incident-recovery-opening-clordid",
            "btcDPfailed0001",
            "--incident-recovery-algo-clordid",
            "btcDPfailed0001A",
            "--incident-recovery-algo-id",
            "algo-1",
            "--incident-recovery-close-clordid",
            "btcDPrecover0002",
        ]
    )
    return argv


def _canonical_incident_cli_args(tmp_path: Path) -> list[str]:
    argv = _incident_cli_args(tmp_path)
    for flag in (
        "--incident-recovery-opening-clordid",
        "--incident-recovery-algo-clordid",
        "--incident-recovery-algo-id",
        "--incident-recovery-close-clordid",
    ):
        index = argv.index(flag)
        del argv[index : index + 2]
    argv.extend(
        [
            "--incident-recovery-runtime-root",
            str(tmp_path / "runtime"),
            "--incident-recovery-incident-source-head",
            "b" * 40,
            "--incident-recovery-recovery-code-head",
            _head(),
            "--incident-recovery-repo-root",
            str(Path.cwd()),
            "--incident-recovery-runtime-root-sha256",
            "a" * 64,
            "--incident-recovery-state-sha256",
            "b" * 64,
            "--incident-recovery-events-sha256",
            "c" * 64,
        ]
    )
    return argv


@pytest.mark.parametrize(
    "missing_flag",
    (
        "--okx-native-shared-manifest-git-spec",
        "--okx-native-shared-data-root",
        "--okx-native-expected-dataset-id",
    ),
)
def test_native_execute_missing_shared_dataset_binding_blocks_before_runtime_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing_flag: str,
) -> None:
    argv = _native_cli_args(tmp_path)
    index = argv.index(missing_flag)
    del argv[index : index + 2]
    runtime_calls: list[str] = []

    def forbidden_runtime(*_args: Any, **_kwargs: Any) -> Any:
        runtime_calls.append("runtime_or_endpoint_constructed")
        raise AssertionError("runtime construction must remain unreachable")

    monkeypatch.setattr(fault_drill_cli, "_runtime", forbidden_runtime)
    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *argv])

    with pytest.raises(SystemExit, match="OKX Native shared dataset binding"):
        fault_drill_cli.main()

    assert runtime_calls == []


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--incident-recovery-failed-receipt", "failed.json"),
        ("--incident-recovery-failed-receipt-sha256", "a" * 64),
        ("--incident-recovery-opening-clordid", "btcDPfailed0001"),
        ("--incident-recovery-algo-clordid", "btcDPfailed0001A"),
        ("--incident-recovery-algo-id", "algo-1"),
        ("--incident-recovery-close-clordid", "btcDPrecover0002"),
    ],
)
def test_incident_recovery_partial_cli_flags_block_before_runtime_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flag: str,
    value: str,
) -> None:
    argv = _native_cli_args(tmp_path)
    argv.extend([flag, value])
    runtime_calls: list[str] = []
    monkeypatch.setattr(
        fault_drill_cli,
        "_runtime",
        lambda *_args, **_kwargs: runtime_calls.append("constructed"),
    )
    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *argv])

    with pytest.raises(SystemExit, match="all-or-none"):
        fault_drill_cli.main()

    assert runtime_calls == []


def test_non_partial_0p03_cli_is_blocked_before_runtime_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv = _native_cli_args(tmp_path)
    argv[argv.index("--order-contracts") + 1] = "0.03"
    runtime_calls: list[str] = []
    monkeypatch.setattr(
        fault_drill_cli,
        "_runtime",
        lambda *_args, **_kwargs: runtime_calls.append("constructed"),
    )
    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *argv])

    assert fault_drill_cli.main() == 2
    assert runtime_calls == []
    receipts = list(tmp_path.glob("btc_okx_demo_fault_drill/**/*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert "fault_drill_order_contracts_mismatch" in receipt["blockers"]
    assert receipt["orders_posted"] == 0


def test_incident_recovery_binding_failure_writes_blocked_receipt_zero_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_calls: list[str] = []
    monkeypatch.setattr(
        fault_drill_cli.BtcOkxDemoFailedReceiptBinding,
        "load",
        classmethod(
            lambda _cls, **_kwargs: (_ for _ in ()).throw(
                FaultDrillReceiptError("failed receipt identity mismatch")
            )
        ),
    )
    monkeypatch.setattr(
        fault_drill_cli,
        "_runtime",
        lambda *_args, **_kwargs: runtime_calls.append("constructed"),
    )
    monkeypatch.setattr(
        fault_drill_cli.sys,
        "argv",
        ["fault-drill", *_incident_cli_args(tmp_path)],
    )

    assert fault_drill_cli.main() == 2
    assert runtime_calls == []
    receipts = list(tmp_path.glob("btc_okx_demo_fault_drill/**/*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["decision"] == "startup_failed_fail_closed"
    assert receipt["orders_posted"] == 0


def test_incident_recovery_service_exception_after_success_stops_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binding = BtcOkxDemoFailedReceiptBinding(
        path=(tmp_path / "failed.json").resolve(),
        failed_receipt_sha256="a" * 64,
        failed_receipt_source_head="b" * 40,
        failed_receipt_scenario="post_response_loss",
        failed_receipt_run_id="failed-run-1",
        opening_cl_ord_id="btcDPfailed0001",
        opening_order_id="opening-order-1",
        opening_fill_id="opening-fill-1",
        algo_cl_ord_id="btcDPfailed0001A",
        algo_id="algo-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )

    class RecoveryRuntime:
        def __init__(self) -> None:
            self.stop_calls = 0
            self._fault_drill_lock_handle: object | None = object()
            self.stopped = False

        def recover_fault_drill_incident(self, **_kwargs: Any) -> dict[str, Any]:
            return {"decision": "incident_recovery_completed_safe_flat"}

        def freeze_fault_drill(self, _reason: str) -> None:
            return None

        def stop(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("incident recovery must not call generic stop")

        def finalize_incident_recovery_local(self) -> dict[str, Any]:
            self.stop_calls += 1
            self.stopped = True
            return self.status()

        def release_fault_drill_process_lock(self) -> None:
            self._fault_drill_lock_handle = None

        def status(self) -> dict[str, Any]:
            status = _snapshot()
            status["runtime"].update(
                {
                    "active": not self.stopped,
                    "worker_alive": False,
                    "status": "stopped" if self.stopped else "running",
                }
            )
            status["risk_control"]["dead_man"] = {
                "armed": False,
                "heartbeat_thread_alive": False,
            }
            status["private_ws"]["listener_alive"] = not self.stopped
            return status

    runtime = RecoveryRuntime()

    def fail_after_recovery(
        _self: Any,
        _config: Any,
        *,
        runtime: Any,
        binding: Any,
    ) -> dict[str, Any]:
        runtime.recover_fault_drill_incident(
            authorization=binding.runtime_authorization(
                runtime_source_head=_head()
            )
        )
        raise RuntimeError("receipt build failed after recovery")

    monkeypatch.setattr(
        fault_drill_cli.BtcOkxDemoFailedReceiptBinding,
        "load",
        classmethod(lambda _cls, **_kwargs: binding),
    )
    monkeypatch.setattr(fault_drill_cli, "_runtime", lambda *_args: runtime)
    monkeypatch.setattr(
        BtcOkxDemoFaultDrillService,
        "run_incident_recovery",
        fail_after_recovery,
    )
    monkeypatch.setattr(
        fault_drill_cli.sys,
        "argv",
        ["fault-drill", *_incident_cli_args(tmp_path)],
    )

    assert fault_drill_cli.main() == 2
    assert runtime.stop_calls == 1
    assert runtime._fault_drill_lock_handle is None
    receipts = list(tmp_path.glob("btc_okx_demo_fault_drill/**/*.json"))
    assert len(receipts) == 1


def test_incident_recovery_cli_success_uses_local_no_post_finalizer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binding = BtcOkxDemoFailedReceiptBinding(
        path=(tmp_path / "failed.json").resolve(),
        failed_receipt_sha256="a" * 64,
        failed_receipt_source_head="b" * 40,
        failed_receipt_scenario="post_response_loss",
        failed_receipt_run_id="failed-run-1",
        opening_cl_ord_id="btcDPfailed0001",
        opening_order_id="opening-order-1",
        opening_fill_id="opening-fill-1",
        algo_cl_ord_id="btcDPfailed0001A",
        algo_id="algo-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )

    class CliRecoveryRuntime:
        def __init__(self) -> None:
            self.posts: list[str] = []
            self._fault_drill_lock_handle: object | None = object()
            self.stopped = False

        def recover_fault_drill_incident(self, **_kwargs: Any) -> dict[str, Any]:
            self.posts.extend(["order", "cancel-algos"])
            return {"decision": "incident_recovery_completed_safe_flat"}

        def finalize_incident_recovery_local(self) -> dict[str, Any]:
            assert self.posts == ["order", "cancel-algos"]
            self.stopped = True
            return self.status()

        def stop(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
            self.posts.append("cancel-all-after")
            raise AssertionError("generic stop/CAA must remain unreachable")

        def release_fault_drill_process_lock(self) -> None:
            self._fault_drill_lock_handle = None

        def status(self) -> dict[str, Any]:
            status = _snapshot()
            status["runtime"].update(
                {
                    "active": not self.stopped,
                    "worker_alive": False,
                    "status": "stopped" if self.stopped else "running",
                }
            )
            status["risk_control"]["dead_man"] = {
                "armed": False,
                "heartbeat_thread_alive": False,
            }
            status["private_ws"]["listener_alive"] = not self.stopped
            return status

    runtime = CliRecoveryRuntime()

    def successful_recovery(
        _self: Any,
        config: Any,
        *,
        runtime: Any,
        binding: Any,
    ) -> dict[str, Any]:
        runtime.recover_fault_drill_incident(
            authorization=binding.runtime_authorization(
                runtime_source_head=config.source_head
            )
        )
        receipt = BtcOkxDemoFaultDrillService().run(config, runtime=None)
        return {
            **receipt,
            "decision": "completed_safe_flat",
            "blockers": [],
            "orders_posted": 1,
        }

    monkeypatch.setattr(
        fault_drill_cli.BtcOkxDemoFailedReceiptBinding,
        "load",
        classmethod(lambda _cls, **_kwargs: binding),
    )
    monkeypatch.setattr(fault_drill_cli, "_runtime", lambda *_args: runtime)
    monkeypatch.setattr(
        BtcOkxDemoFaultDrillService,
        "run_incident_recovery",
        successful_recovery,
    )
    monkeypatch.setattr(
        fault_drill_cli.sys,
        "argv",
        ["fault-drill", *_incident_cli_args(tmp_path)],
    )

    assert fault_drill_cli.main() == 0
    assert runtime.posts == ["order", "cancel-algos"]
    assert runtime._fault_drill_lock_handle is None


def test_native_shared_dataset_binding_is_passed_exactly_to_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_git_spec = "feedface:.agent/data_manifests/btc-okx-native.json"
    shared_data_root = (tmp_path / "shared-root").resolve()
    expected_dataset_id = "btc-okx-native-hourly-v1"
    args = SimpleNamespace(
        data_db_path=tmp_path / "market.sqlite",
        runtime_output_dir=tmp_path / "runtime",
        okx_native_shared_manifest_git_spec=manifest_git_spec,
        okx_native_shared_data_root=shared_data_root,
        okx_native_expected_dataset_id=expected_dataset_id,
    )
    config = _config(tmp_path, _head(), "held_position_disconnect", execute=True)
    captured: list[Any] = []
    sentinel = object()

    def capture_controller(*, config: Any, start_worker: bool) -> object:
        assert start_worker is False
        captured.append(config)
        return sentinel

    monkeypatch.setattr(
        fault_drill_cli,
        "OkxDemoPaperRuntimeController",
        capture_controller,
    )

    runtime = fault_drill_cli._runtime(args, config)

    assert runtime is sentinel
    assert len(captured) == 1
    assert captured[0].okx_native_shared_manifest_git_spec == manifest_git_spec
    assert captured[0].okx_native_shared_data_root == shared_data_root
    assert captured[0].okx_native_expected_dataset_id == expected_dataset_id
    assert isinstance(
        captured[0].execution_dispatcher,
        BTCDemoExecutionDispatcher,
    )


def test_owned_id_restore_arguments_are_explicitly_passed_to_runtime_and_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = {
        "owned_id_restore_archive_root": (tmp_path / "archive").resolve(),
        "owned_id_restore_current_head": _head(),
        "owned_id_restore_source_head": "1" * 40,
        "owned_id_restore_account_identity": "account-fingerprint",
        "owned_id_restore_credential_identity": "credential-fingerprint",
        "owned_id_restore_client_order_namespace": "btcDP",
    }
    args = SimpleNamespace(
        data_db_path=tmp_path / "market.sqlite",
        runtime_output_dir=tmp_path / "runtime",
        okx_native_shared_manifest_git_spec="",
        okx_native_shared_data_root=None,
        okx_native_expected_dataset_id="",
        execute_demo=True,
        scenario="held_position_disconnect",
        strategy_id="long_short_donchian_top5",
        candidate_id=btc_strategy_registry.get("long_short_donchian_top5").candidate_id,
        strategy_version=btc_strategy_registry.get("long_short_donchian_top5").strategy_version,
        max_notional_usdt="10",
        **values,
    )
    config = _config(tmp_path, _head(), "held_position_disconnect", execute=True)
    captured: list[Any] = []
    sentinel = object()

    def capture_controller(*, config: Any, start_worker: bool) -> object:
        assert start_worker is False
        captured.append(config)
        return sentinel

    monkeypatch.setattr(
        fault_drill_cli,
        "OkxDemoPaperRuntimeController",
        capture_controller,
    )
    runtime = fault_drill_cli._runtime(args, config)

    assert runtime is sentinel
    assert captured[0].owned_id_restore_archive_root == values[
        "owned_id_restore_archive_root"
    ]
    assert captured[0].owned_id_restore_current_head == values[
        "owned_id_restore_current_head"
    ]
    assert captured[0].owned_id_restore_source_head == values[
        "owned_id_restore_source_head"
    ]
    assert captured[0].owned_id_restore_account_identity == values[
        "owned_id_restore_account_identity"
    ]
    assert captured[0].owned_id_restore_credential_identity == values[
        "owned_id_restore_credential_identity"
    ]
    assert captured[0].owned_id_restore_client_order_namespace == values[
        "owned_id_restore_client_order_namespace"
    ]

    class CaptureStartRuntime:
        def __init__(self) -> None:
            self.payload: dict[str, Any] = {}

        def start(self, payload: Mapping[str, Any]) -> None:
            self.payload = dict(payload)

    start_runtime = CaptureStartRuntime()
    fault_drill_cli._start_runtime(start_runtime, args)
    for key, expected in values.items():
        assert start_runtime.payload[key] == expected


def test_owned_id_restore_cli_arguments_are_all_or_none(
    tmp_path: Path,
) -> None:
    argv = _native_cli_args(tmp_path)
    argv.extend(["--owned-id-restore-current-head", _head()])
    args = fault_drill_cli.build_parser().parse_args(argv)
    with pytest.raises(SystemExit, match="owned-id restore arguments"):
        fault_drill_cli._validate_owned_id_restore_arguments(args)


@pytest.mark.parametrize(
    "hash_flag",
    (
        "--incident-recovery-runtime-root-sha256",
        "--incident-recovery-state-sha256",
        "--incident-recovery-events-sha256",
    ),
)
def test_canonical_cli_requires_external_runtime_hashes_before_runtime_construction(
    tmp_path: Path,
    hash_flag: str,
) -> None:
    argv = _canonical_incident_cli_args(tmp_path)
    index = argv.index(hash_flag)
    del argv[index : index + 2]
    args = fault_drill_cli.build_parser().parse_args(argv)
    with pytest.raises(
        SystemExit,
        match="runtime root, state, and events sha256",
    ):
        fault_drill_cli._validate_incident_recovery_arguments(args)


def test_identity_archive_cli_is_canonical_only_and_passed_without_manual_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    noncanonical = _native_cli_args(tmp_path)
    noncanonical.extend(
        [
            "--incident-recovery-identity-archive-root",
            str(tmp_path / "identity-anchor"),
        ]
    )
    with pytest.raises(SystemExit, match="identity archive is only valid"):
        fault_drill_cli._validate_incident_recovery_arguments(
            fault_drill_cli.build_parser().parse_args(noncanonical)
        )

    canonical = _canonical_incident_cli_args(tmp_path)
    archive_root = (tmp_path / "identity-anchor").resolve()
    canonical.extend(["--incident-recovery-identity-archive-root", str(archive_root)])
    captured: dict[str, Any] = {}
    runtime_calls: list[str] = []

    def capture_loader(_cls: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        raise FaultDrillReceiptError("identity archive fixture rejected")

    monkeypatch.setattr(
        fault_drill_cli.BtcOkxDemoFailedReceiptBinding,
        "load",
        classmethod(capture_loader),
    )
    monkeypatch.setattr(
        fault_drill_cli,
        "_runtime",
        lambda *_args, **_kwargs: runtime_calls.append("constructed"),
    )
    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *canonical])
    assert fault_drill_cli.main() == 2
    assert captured["identity_archive_root"] == archive_root
    assert captured["expected_opening_cl_ord_id"] == ""
    assert runtime_calls == []


def test_canonical_cli_rejects_invalid_external_runtime_hash_before_runtime_construction(
    tmp_path: Path,
) -> None:
    argv = _canonical_incident_cli_args(tmp_path)
    index = argv.index("--incident-recovery-state-sha256") + 1
    argv[index] = "A" * 64
    args = fault_drill_cli.build_parser().parse_args(argv)
    with pytest.raises(
        SystemExit,
        match="runtime root, state, and events sha256",
    ):
        fault_drill_cli._validate_incident_recovery_arguments(args)


@pytest.mark.parametrize(
    "missing_flag",
    (
        "--incident-recovery-incident-source-head",
        "--incident-recovery-recovery-code-head",
        "--incident-recovery-repo-root",
    ),
)
def test_canonical_cli_requires_explicit_dual_heads_and_repo_root(
    tmp_path: Path,
    missing_flag: str,
) -> None:
    argv = _canonical_incident_cli_args(tmp_path)
    index = argv.index(missing_flag)
    del argv[index : index + 2]
    args = fault_drill_cli.build_parser().parse_args(argv)
    with pytest.raises(
        SystemExit,
        match="incident source, recovery code head, and repo root",
    ):
        fault_drill_cli._validate_incident_recovery_arguments(args)


def test_canonical_cli_self_verifies_actual_recovery_head_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv = _canonical_incident_cli_args(tmp_path)
    index = argv.index("--source-head") + 1
    argv[index] = "f" * 40
    runtime_calls: list[str] = []
    monkeypatch.setattr(
        fault_drill_cli,
        "_runtime",
        lambda *_args, **_kwargs: runtime_calls.append("constructed"),
    )
    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *argv])
    with pytest.raises(
        SystemExit,
        match="actual recovery code HEAD",
    ):
        fault_drill_cli.main()
    assert runtime_calls == []


def test_native_binding_validation_keeps_non_native_and_dry_run_compatible(
    tmp_path: Path,
) -> None:
    native_dry_run_argv = _native_cli_args(tmp_path)
    native_dry_run_argv.remove("--execute-demo")
    native_dry_run = fault_drill_cli.build_parser().parse_args(native_dry_run_argv)
    non_native_execute_argv = _native_cli_args(tmp_path)
    non_native_execute_argv[
        non_native_execute_argv.index("--strategy-id") + 1
    ] = "long_short_donchian_top5"
    for flag in (
        "--okx-native-shared-manifest-git-spec",
        "--okx-native-shared-data-root",
        "--okx-native-expected-dataset-id",
    ):
        index = non_native_execute_argv.index(flag)
        del non_native_execute_argv[index : index + 2]
    non_native_execute = fault_drill_cli.build_parser().parse_args(
        non_native_execute_argv
    )

    fault_drill_cli._validate_okx_native_shared_dataset_binding(native_dry_run)
    fault_drill_cli._validate_okx_native_shared_dataset_binding(non_native_execute)


def test_worker_child_argv_preserves_native_shared_dataset_binding_without_receipt_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv = _native_cli_args(tmp_path)
    argv[argv.index("--scenario") + 1] = "worker_kill"
    args = fault_drill_cli.build_parser().parse_args(argv)
    config = _config(tmp_path, _head(), "worker_kill", execute=True)
    spawned: list[list[str]] = []

    class ExitedProcess:
        pid = 43210
        returncode = 1

        def poll(self) -> int:
            return self.returncode

    def capture_spawn(child_args: list[str], **_kwargs: Any) -> ExitedProcess:
        spawned.append(list(child_args))
        return ExitedProcess()

    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *argv])
    monkeypatch.setattr(fault_drill_cli.subprocess, "Popen", capture_spawn)
    monkeypatch.setattr(
        fault_drill_cli,
        "_process_create_time",
        lambda _pid: (_ for _ in ()).throw(OSError("create-time")),
    )

    with pytest.raises(fault_drill_cli.WorkerParentEmergency):
        fault_drill_cli._run_worker_parent(args, config)

    assert len(spawned) == 1
    for flag in (
        "--okx-native-shared-manifest-git-spec",
        "--okx-native-shared-data-root",
        "--okx-native-expected-dataset-id",
    ):
        parent_index = argv.index(flag)
        child_index = spawned[0].index(flag)
        assert spawned[0][child_index + 1] == argv[parent_index + 1]
    receipt = next(
        tmp_path.glob("btc_okx_demo_fault_drill_emergency/**/*.json")
    ).read_text(encoding="utf-8")
    assert str(args.okx_native_shared_data_root) not in receipt


def test_scenario_catalog_is_exact_and_official_semantics_are_fixed() -> None:
    assert DEMO_FAULT_DRILL_SCENARIOS == (
        "held_position_disconnect",
        "post_response_loss",
        "partial_fill_disconnect",
        "protection_creation_failure",
        "worker_kill",
        "reconnect_full_reconciliation",
    )
    assert OKX_DOCS_REVIEW_METADATA == {
        "review_url": "https://www.okx.com/docs-v5/",
        "review_date": "2026-08-05",
        "demo_header": "x-simulated-trading: 1",
        "clOrdId_query": True,
        "attachAlgo_activation_after_fill": True,
        "cancel_all_after_scope": "pending_orders_only_not_positions",
        "cancel_algos_path": "/api/v5/trade/cancel-algos",
        "cancel_algos_batch_max": 10,
        "cancel_algos_required_fields": ["algoId", "instId"],
        "cancel_algos_each_sCode_zero_required": True,
        "cancel_algos_ack_alone_sufficient": False,
        "cancel_algos_pending_and_history_readback_required": True,
    }


def test_default_dry_run_writes_fail_closed_receipt_without_runtime_or_post(tmp_path: Path) -> None:
    head = _head()
    service = BtcOkxDemoFaultDrillService()
    config = _config(tmp_path, head, "held_position_disconnect", execute=False)
    receipt = service.run(
        config,
        runtime=None,
    )
    receipt_path = receipt["receipt_path"]
    assert Path(receipt_path).exists() is False
    receipt = service.publish_terminal_receipt(
        config,
        receipt,
        lifecycle=_terminal_lifecycle(runtime_not_constructed=True),
    ) | {"receipt_path": receipt_path}

    assert receipt["decision"] == "dry_run_fail_closed"
    assert receipt["orders_posted"] == 0
    assert receipt["evidence_class"] == "demo_fault_drill_evidence"
    assert receipt["promotion_eligible"] is False
    assert receipt["live_allowed"] is False
    assert Path(receipt["receipt_path"]).is_file()


def test_exception_receipt_derives_owned_filled_order_from_exchange_delta(
    tmp_path: Path,
) -> None:
    runtime = FilledThenRaisedRuntime()

    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "post_response_loss", execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert receipt["orders_posted"] == 1
    assert receipt["clOrdId"] == "btcDPowned0001"
    assert receipt["observed_order_side_effects"] == {
        "bound_client_order_ids": ["btcDPowned0001"],
        "new_observed_client_order_ids": ["btcDPowned0001"],
        "orders_posted": 1,
    }
    assert "fault_drill_execution_failed:RuntimeError:" in "\n".join(
        receipt["blockers"]
    )


def test_failed_receipt_binding_hashes_and_parses_the_same_raw_bytes(
    tmp_path: Path,
) -> None:
    failed_receipt = {
        "schema_version": "btc_okx_demo_fault_drill_receipt_v1",
        "source_head": "a" * 40,
        "scenario": "post_response_loss",
        "run_id": "failed-run-1",
        "decision": "failed_postflight_frozen",
        "execution_requested": True,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
        "orders_posted": 0,
        "clOrdId": "",
        "post_snapshot": {
            "orders": [
                {
                    "order_id": "opening-order-1",
                    "clOrdId": "btcDPfailed0001",
                    "state": "filled",
                }
            ],
            "fills": [
                {
                    "fill_id": "opening-fill-1",
                    "clOrdId": "btcDPfailed0001",
                    "size": "0.01",
                }
            ],
            "pending_algo_orders": [
                {
                    "algo_id": "algo-1",
                    "algoClOrdId": "btcDPfailed0001A",
                    "state": "live",
                }
            ],
        },
    }
    raw = json.dumps(
        failed_receipt,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    path = (tmp_path / "failed-receipt.json").resolve()
    path.write_bytes(raw)
    expected_sha256 = __import__("hashlib").sha256(raw).hexdigest()

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=path,
        expected_sha256=expected_sha256,
        expected_opening_cl_ord_id="btcDPfailed0001",
        expected_algo_cl_ord_id="btcDPfailed0001A",
        expected_algo_id="algo-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )

    assert binding.failed_receipt_sha256 == expected_sha256
    assert binding.failed_receipt_source_head == "a" * 40
    assert binding.opening_cl_ord_id == "btcDPfailed0001"
    assert binding.opening_order_id == "opening-order-1"
    assert binding.opening_fill_id == "opening-fill-1"
    assert binding.algo_cl_ord_id == "btcDPfailed0001A"
    assert binding.algo_id == "algo-1"
    assert binding.expected_close_cl_ord_id == "btcDPrecover0002"

    path.write_bytes(raw + b" ")
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_failed_receipt_sha256_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=path,
            expected_sha256=expected_sha256,
            expected_opening_cl_ord_id="btcDPfailed0001",
            expected_algo_cl_ord_id="btcDPfailed0001A",
            expected_algo_id="algo-1",
            expected_close_cl_ord_id="btcDPrecover0002",
        )


def _canonical_recovery_fixture(
    tmp_path: Path,
    *,
    source_head: str = "",
    owner_marker_recovery_head: str | None = None,
    run_id: str = "20a8d165b75949759f4c8e7eee6d0c8d",
    receipt_run_id: str | None = None,
    receipt_runtime_run_id: str = "",
    historical_run_ids: tuple[str, ...] = (),
    legacy_empty_prefix_event_count: int = 0,
    event_source_heads: tuple[Any, ...] = (),
    state_runtime_source_head: Any = _FIXTURE_USE_EVENT_SOURCE_HEAD,
    omit_state_runtime_source_head: bool = False,
    interleaved_run_id: str = "",
    interleaved_empty_run_id: bool = False,
    foreign_tail_run_id: str = "",
    state_identity: tuple[str, str] | None = (
        "b" * 64,
        "quant-system.okx-demo.trade",
    ),
) -> tuple[Path, Path, Path, str]:
    """Build one fully durable offline incident fixture."""

    source_head = source_head or _head()
    runtime_root = (tmp_path / "external-runtime").resolve()
    receipt_root = (tmp_path / "external-receipts").resolve()
    binding_root = (tmp_path / "external-bindings").resolve()
    runtime_root.mkdir()
    receipt_root.mkdir()
    binding_root.mkdir()
    namespace = f"btcDP{run_id[:8]}"
    opening = f"{namespace}0001"
    algo_clord = f"{namespace}0001A"
    order_id = "opening-order-1"
    fill_id = "opening-fill-1"
    algo_id = "algo-1"
    runtime_state: dict[str, Any] = {
        "run_id": run_id,
        "order_sequence": 1,
    }
    if not omit_state_runtime_source_head:
        runtime_state["source_head"] = (
            source_head
            if state_runtime_source_head is _FIXTURE_USE_EVENT_SOURCE_HEAD
            else state_runtime_source_head
        )
    state = {
        "schema_version": "okx_demo_paper_runtime_status_v1",
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "runtime": runtime_state,
        "risk_control": {
            "pending_order_intents": {
                opening: {
                    "client_order_id": opening,
                    "persisted_before_post": True,
                    "risk_reducing_only": False,
                    "exchange_order_id": order_id,
                    "exchange_state": "filled",
                    "status": "terminal",
                    "order": {
                        "instId": "BTC-USDT-SWAP",
                        "side": "buy",
                        "posSide": "long",
                        "ordType": "fok",
                        "sz": "0.01",
                        "clOrdId": opening,
                    },
                }
            },
            "owned_attached_algos": {
                algo_clord: {
                    "algo_client_order_id": algo_clord,
                    "algo_id": algo_id,
                    "parent_client_order_id": opening,
                    "instrument_id": "BTC-USDT-SWAP",
                    "opening_intent": True,
                    "status": "submit_pending",
                }
            },
            "owned_id_restore": (
                {
                    "account_identity": state_identity[0],
                    "credential_identity": state_identity[1],
                }
                if state_identity is not None
                else {}
            ),
        },
        "exchange": {
            "account": {
                "position_mode": "long_short_mode",
                "withdraw_permission_present": False,
            },
            "pending_orders": [],
            "pending_algo_orders": [
                {
                    "algo_client_order_id": algo_clord,
                    "algo_id": algo_id,
                    "instrument_id": "BTC-USDT-SWAP",
                    "state": "live",
                }
            ],
            "positions": [
                {
                    "instrument_id": "BTC-USDT-SWAP",
                    "position_side": "long",
                    "contracts": "0.01",
                    "margin_mode": "isolated",
                    "leverage": "3",
                }
            ],
        },
        "safety": {"opening_allowed": False, "live_allowed": False},
    }
    store = BTCRuntimeStore(runtime_root)
    event_source_index = 0

    def _event_source_head() -> str:
        nonlocal event_source_index
        if not event_source_heads:
            return source_head
        if event_source_index >= len(event_source_heads):
            raise AssertionError("fixture event source head sequence exhausted")
        value = event_source_heads[event_source_index]
        event_source_index += 1
        return value

    def _state_for(event_run_id: str, event_source_head: str) -> dict[str, Any]:
        projected = json.loads(json.dumps(state))
        projected["runtime"]["run_id"] = event_run_id
        if omit_state_runtime_source_head:
            projected["runtime"].pop("source_head", None)
        elif state_runtime_source_head is _FIXTURE_USE_EVENT_SOURCE_HEAD:
            projected["runtime"]["source_head"] = event_source_head
        else:
            projected["runtime"]["source_head"] = state_runtime_source_head
        return projected

    for index, historical_run_id in enumerate(historical_run_ids):
        historical_source_head = _event_source_head()
        store.append(
            event_type="runtime_status",
            payload={"source_head": historical_source_head, "historical": True},
            state_after=_state_for(historical_run_id, historical_source_head),
            idempotency_key=f"history-{index}",
            timestamp_utc=f"2026-08-08T00:00:0{index}+00:00",
            run_id=historical_run_id,
            safety=state["safety"],
        )
    for index in range(legacy_empty_prefix_event_count):
        historical_source_head = _event_source_head()
        store.append(
            event_type="runtime_status",
            payload={"source_head": historical_source_head, "historical": True},
            state_after=_state_for("", historical_source_head),
            idempotency_key=f"legacy-empty-history-{index}",
            timestamp_utc=f"2026-08-08T00:01:0{index}+00:00",
            run_id="",
            safety=state["safety"],
        )

    lifecycle = {
        "oms": {
            "client_order_id": opening,
            "status": "reconciled",
        },
        "exchange_order_id": order_id,
        "fills": [
            {"fill_id": fill_id, "client_order_id": opening, "order_id": order_id}
        ],
    }
    lifecycle_source_head = _event_source_head()
    store.append(
        event_type="order_lifecycle",
        payload={**lifecycle, "source_head": lifecycle_source_head},
        state_after=_state_for(run_id, lifecycle_source_head),
        idempotency_key="lifecycle-1",
        timestamp_utc="2026-08-09T00:00:00+00:00",
        run_id=run_id,
        safety=state["safety"],
    )
    if interleaved_run_id:
        historical_source_head = _event_source_head()
        store.append(
            event_type="runtime_status",
            payload={"source_head": historical_source_head, "historical": True},
            state_after=_state_for(interleaved_run_id, historical_source_head),
            idempotency_key="interleaved-foreign",
            timestamp_utc="2026-08-09T00:00:00.500000+00:00",
            run_id=interleaved_run_id,
            safety=state["safety"],
        )
    if interleaved_empty_run_id:
        historical_source_head = _event_source_head()
        store.append(
            event_type="runtime_status",
            payload={"source_head": historical_source_head, "historical": True},
            state_after=_state_for("", historical_source_head),
            idempotency_key="interleaved-empty",
            timestamp_utc="2026-08-09T00:00:00.750000+00:00",
            run_id="",
            safety=state["safety"],
        )
    ledger_source_head = _event_source_head()
    store.append(
        event_type="ledger_uow_committed",
        payload={
            "source_head": ledger_source_head,
            "order_ledger": {"orders": [{"client_order_id": opening, "order_id": order_id}]},
            "fill_ledger": [{"client_order_id": opening, "order_id": order_id, "fill_id": fill_id}],
        },
        state_after=_state_for(run_id, ledger_source_head),
        idempotency_key="ledger-1",
        timestamp_utc="2026-08-09T00:00:01+00:00",
        run_id=run_id,
        safety=state["safety"],
    )
    if foreign_tail_run_id:
        historical_source_head = _event_source_head()
        store.append(
            event_type="runtime_status",
            payload={"source_head": historical_source_head, "historical": True},
            state_after=_state_for(foreign_tail_run_id, historical_source_head),
            idempotency_key="foreign-tail",
            timestamp_utc="2026-08-09T00:00:02+00:00",
            run_id=foreign_tail_run_id,
            safety=state["safety"],
        )
    store.checkpoint(state)
    runtime_root.joinpath(".btc_okx_demo_fault_drill_writer.lock").write_text(
        json.dumps(
            {
                "nonce": "fixture",
                "process_id": 1,
                "source_head": source_head,
                **(
                    {"recovery_code_head": owner_marker_recovery_head}
                    if owner_marker_recovery_head is not None
                    else {}
                ),
                "runtime_root_sha256": fault_drill_module._sha256(str(runtime_root)),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "btc_okx_demo_fault_drill_receipt_v1",
        "source_head": source_head,
        "scenario": "post_response_loss",
        "run_id": receipt_run_id or run_id,
        "decision": "failed_postflight_frozen",
        "execution_requested": True,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
        "orders_posted": 1,
        "credentials_redacted": True,
        "opening_allowed": False,
        "promotion_eligible": False,
        "paper_promotion_allowed": False,
        "live_allowed": False,
        "clOrdId": opening,
        "provenance": (
            {"runtime_run_id": receipt_runtime_run_id}
            if receipt_runtime_run_id
            else {}
        ),
        "post_snapshot": {
            "orders": [{"clOrdId": opening, "order_id": order_id, "state": "filled"}],
            "fills": [{"clOrdId": opening, "fill_id": fill_id, "order_id": order_id, "size": "0.01"}],
            "pending_algo_orders": [{"algoClOrdId": algo_clord, "algo_id": algo_id, "state": "live"}],
            "positions": [{"instrument_id": "BTC-USDT-SWAP", "position_side": "long", "contracts": "0.01"}],
        },
    }
    receipt_path = receipt_root / "failed.json"
    receipt_path.write_bytes(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    return receipt_path, runtime_root, binding_root, source_head


def _canonical_runtime_hashes(
    runtime_root: Path,
    incident_source_head: str,
) -> dict[str, Any]:
    return {
        "repo_root": Path.cwd(),
        "expected_incident_source_head": incident_source_head,
        "expected_recovery_code_head": _head(),
        "expected_runtime_root_sha256": fault_drill_module._sha256(
            str(runtime_root.resolve())
        ),
        "expected_runtime_state_sha256": hashlib.sha256(
            runtime_root.joinpath("state.json").read_bytes()
        ).hexdigest(),
        "expected_runtime_events_sha256": hashlib.sha256(
            runtime_root.joinpath("events.jsonl").read_bytes()
        ).hexdigest(),
    }


def _worker_parent_emergency_recovery_fixture(
    tmp_path: Path,
    *,
    pending_algo_client_order_id: str | None = None,
    pending_parent_client_order_id: str = "",
    pending_state: str = "live",
    pending_size: str = "0.01",
    pending_position_side: str = "long",
    owned_present: bool = True,
    owned_algo_client_order_id: str | None = None,
    owned_parent_client_order_id: str | None = None,
    owned_algo_id: str = "",
    owned_status: str = "submit_pending",
    owned_opening_intent: bool = True,
    duplicate_owned_match: bool = False,
) -> tuple[Path, Path, Path, Path, str]:
    """Build the exact parent-timeout / child-durable-identity shape offline."""

    receipt_path, runtime_root, binding_root, source_head = (
        _canonical_recovery_fixture(tmp_path)
    )
    recovered = BTCRuntimeStore(runtime_root).recover()
    assert recovered.blockers == ()
    state = json.loads(json.dumps(recovered.state))
    runtime = state["runtime"]
    run_id = runtime["run_id"]
    namespace = f"btcDP{run_id[:8]}"
    opening = f"{namespace}0003"
    algo_clord = f"{opening}A"
    order_id = "worker-parent-opening-order"
    fill_id = "worker-parent-opening-fill"
    algo_id = "worker-parent-algo"
    runtime["order_sequence"] = 3
    risk = state["risk_control"]
    risk["pending_order_intents"] = {
        opening: {
            "client_order_id": opening,
            "persisted_before_post": True,
            "risk_reducing_only": False,
            "exchange_order_id": order_id,
            "exchange_state": "filled",
            "status": "terminal",
            "order": {"clOrdId": opening},
        }
    }
    pending_algo_client_order_id = pending_algo_client_order_id or algo_clord
    owned_algo_client_order_id = owned_algo_client_order_id or algo_clord
    owned_parent_client_order_id = (
        opening
        if owned_parent_client_order_id is None
        else owned_parent_client_order_id
    )
    owned_record = {
        "algo_client_order_id": owned_algo_client_order_id,
        "parent_client_order_id": owned_parent_client_order_id,
        "instrument_id": "BTC-USDT-SWAP",
        "opening_intent": owned_opening_intent,
        "status": owned_status,
    }
    if owned_algo_id:
        owned_record["algo_id"] = owned_algo_id
    risk["owned_attached_algos"] = (
        {
            algo_clord: owned_record,
            **(
                {"duplicate-owned": dict(owned_record)}
                if duplicate_owned_match
                else {}
            ),
        }
        if owned_present
        else {}
    )
    state["exchange"]["pending_algo_orders"] = [
        {
            "algo_client_order_id": pending_algo_client_order_id,
            "algo_id": algo_id,
            "parent_client_order_id": pending_parent_client_order_id,
            "instrument_id": "BTC-USDT-SWAP",
            "order_type": "oco",
            "position_side": pending_position_side,
            "size": pending_size,
            "state": pending_state,
        }
    ]
    state["exchange"]["positions"][0]["contracts"] = "0.01"

    # Rebuild a five-event contiguous child chain: persisted intent, filled
    # lifecycle, protection degradation, ledger, then frozen terminal state.
    runtime_root.joinpath("state.json").unlink()
    runtime_root.joinpath("events.jsonl").unlink()
    store = BTCRuntimeStore(runtime_root)
    common = {
        "state_after": state,
        "run_id": run_id,
        "safety": state["safety"],
    }
    store.append(
        event_type="order_intent_persisted_before_post",
        payload={
            "source_head": source_head,
            "action": "open_long",
            "client_order_id": opening,
            "retry_without_query_allowed": False,
        },
        idempotency_key="intent",
        timestamp_utc="2026-08-09T00:00:00+00:00",
        **common,
    )
    store.append(
        event_type="order_lifecycle",
        payload={
            "source_head": source_head,
            "exchange_order_id": order_id,
            "exchange_state": "filled",
            "oms": {"client_order_id": opening, "status": "reconciled"},
            "fills": [
                {
                    "client_order_id": opening,
                    "order_id": order_id,
                    "fill_id": fill_id,
                    "size": "0.01",
                    "position_side": "long",
                    "side": "buy",
                }
            ],
            "order_plan": {
                "action": "open_long",
                "client_order_id": opening,
                "contracts": "0.01",
                "position_side": "long",
                "side": "buy",
                "risk_reducing_only": False,
                "attached_protection": {"attachAlgoClOrdId": algo_clord},
            },
        },
        idempotency_key="lifecycle",
        timestamp_utc="2026-08-09T00:00:01+00:00",
        **common,
    )
    store.append(
        event_type="position_safety_degraded",
        payload={
            "source_head": source_head,
            "opening_allowed": False,
            "risk_reducing_only": True,
            "error": "okx_demo_exchange_hosted_protection_unconfirmed:51603",
        },
        idempotency_key="protection-degraded",
        timestamp_utc="2026-08-09T00:00:02+00:00",
        **common,
    )
    store.append(
        event_type="ledger_uow_committed",
        payload={
            "source_head": source_head,
            "order_ledger": {
                "orders": [{"client_order_id": opening, "order_id": order_id}]
            },
            "fill_ledger": [
                {
                    "client_order_id": opening,
                    "order_id": order_id,
                    "fill_id": fill_id,
                    "size": "0.01",
                }
            ],
            "risk_context": {
                "exchange_hosted_protection": [
                    {
                        "algo_client_order_id": algo_clord,
                        "algo_id": algo_id,
                        "parent_client_order_id": opening,
                        "order_type": "oco",
                        "state": "live",
                    }
                ]
            },
        },
        idempotency_key="ledger",
        timestamp_utc="2026-08-09T00:00:03+00:00",
        **common,
    )
    store.append(
        event_type="fault_drill_frozen",
        payload={
            "source_head": source_head,
            "opening_allowed": False,
            "blind_order_append_allowed": False,
            "reason": "okx_demo_fault_drill_verified_protection_missing",
        },
        idempotency_key="frozen",
        timestamp_utc="2026-08-09T00:00:04+00:00",
        **common,
    )
    store.checkpoint(state)

    marker = {
        "nonce": "a" * 32,
        "process_id": 12345,
        "process_create_time": "123456789",
        "source_head": source_head,
        "recovery_code_head": source_head,
        "runtime_root_sha256": fault_drill_module._sha256(str(runtime_root)),
    }
    runtime_root.joinpath(".btc_okx_demo_fault_drill_writer.lock").write_text(
        json.dumps(marker, sort_keys=True), encoding="utf-8"
    )
    outer = {
        "schema_version": "btc_okx_demo_fault_drill_receipt_v1",
        "source_head": source_head,
        "scenario": "worker_kill",
        "run_id": "worker-parent-run-01",
        "decision": "startup_failed_fail_closed",
        "execution_requested": True,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
        "orders_posted": 0,
        "credentials_redacted": True,
        "opening_allowed": False,
        "promotion_eligible": False,
        "paper_promotion_allowed": False,
        "live_allowed": False,
        "clOrdId": "",
        "algoClOrdId": "",
        "algo_id": "",
        "post_snapshot": {},
    }
    receipt_path.write_text(
        json.dumps(outer, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    emergency_path = (tmp_path / "worker-parent-emergency.json").resolve()
    emergency_path.write_text(
        json.dumps(
            {
                "schema_version": "btc_okx_demo_worker_parent_emergency_v1",
                "source_head": source_head,
                "scenario": "worker_kill",
                "run_id": outer["run_id"],
                "decision": "blocked_fail_closed_worker_supervision_required",
                "disposition": (
                    "parent_waiting_on_exact_child_handle_no_kill_without_"
                    "query_first_identity_and_protection_proof"
                ),
                "failure_code": "worker_parent_marker_wait_failed",
                "failure_stage": "marker_wait",
                "exact_child_handle_owned": True,
                "credentials_redacted": True,
                "paper_allowed": False,
                "live_allowed": False,
                "promotion_eligible": False,
                "orders_retried": 0,
                "child": {
                    "process_id": marker["process_id"],
                    "worker_nonce": marker["nonce"],
                    "process_create_time": marker["process_create_time"],
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt_path, emergency_path, runtime_root, binding_root, source_head


def test_canonical_worker_parent_emergency_binding_derives_only_durable_identity(
    tmp_path: Path,
) -> None:
    receipt_path, emergency_path, runtime_root, binding_root, source_head = (
        _worker_parent_emergency_recovery_fixture(tmp_path)
    )
    kwargs = {
        "path": receipt_path,
        "expected_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "runtime_root": runtime_root,
        "binding_external_root": binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    }
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_receipt_not_eligible",
    ):
        BtcOkxDemoFailedReceiptBinding.load(**kwargs)

    binding = BtcOkxDemoFailedReceiptBinding.load(
        **kwargs,
        worker_parent_emergency_receipt=emergency_path,
        worker_parent_emergency_receipt_sha256=hashlib.sha256(
            emergency_path.read_bytes()
        ).hexdigest(),
    )

    assert binding.failed_receipt_scenario == "worker_kill"
    assert binding.opening_cl_ord_id.endswith("0003")
    assert binding.algo_cl_ord_id == binding.opening_cl_ord_id + "A"
    assert binding.opening_order_id == "worker-parent-opening-order"
    assert binding.opening_fill_id == "worker-parent-opening-fill"
    assert binding.expected_close_cl_ord_id.endswith("0004")
    document = json.loads(binding.binding_path.read_text(encoding="utf-8"))
    assert document["worker_parent_emergency"]["sha256"] == hashlib.sha256(
        emergency_path.read_bytes()
    ).hexdigest()
    assert document["durable_attestation"]["worker_parent_emergency"] is True


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("emergency_sha", "fault_drill_worker_parent_emergency_sha256_mismatch"),
        ("nonce", "fault_drill_worker_parent_emergency_owner_mismatch"),
        ("disposition", "fault_drill_worker_parent_emergency_owner_mismatch"),
        ("outer_run", "fault_drill_worker_parent_emergency_outer_invalid"),
        ("non_worker", "fault_drill_worker_parent_emergency_outer_invalid"),
        ("duplicate_lifecycle", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("close_lifecycle", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("pending_wrong_parent", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("pending_wrong_id", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("pending_not_live", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("owned_missing", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("owned_wrong_algo", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("owned_status", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("owned_not_opening", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("pending_wrong_size", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("pending_wrong_posside", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("owned_join_key", "fault_drill_worker_parent_emergency_identity_ambiguous"),
        ("owned_duplicate", "fault_drill_worker_parent_emergency_identity_ambiguous"),
    ),
)
def test_canonical_worker_parent_emergency_binding_rejects_unanchored_identity(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    fixture_kwargs: dict[str, object] = {}
    if mutation == "pending_wrong_parent":
        fixture_kwargs["pending_parent_client_order_id"] = "foreign-parent"
    elif mutation == "pending_wrong_id":
        fixture_kwargs["pending_algo_client_order_id"] = "btcDPforeign0001A"
    elif mutation == "pending_not_live":
        fixture_kwargs["pending_state"] = "canceled"
    elif mutation == "owned_missing":
        fixture_kwargs["owned_present"] = False
    elif mutation == "owned_wrong_algo":
        fixture_kwargs["owned_algo_id"] = "foreign-algo"
    elif mutation == "owned_status":
        fixture_kwargs["owned_status"] = "live"
    elif mutation == "owned_not_opening":
        fixture_kwargs["owned_opening_intent"] = False
    elif mutation == "pending_wrong_size":
        fixture_kwargs["pending_size"] = "0.02"
    elif mutation == "pending_wrong_posside":
        fixture_kwargs["pending_position_side"] = "short"
    elif mutation == "owned_join_key":
        fixture_kwargs["owned_algo_client_order_id"] = "btcDPforeign0001A"
    elif mutation == "owned_duplicate":
        fixture_kwargs["duplicate_owned_match"] = True
    receipt_path, emergency_path, runtime_root, binding_root, source_head = (
        _worker_parent_emergency_recovery_fixture(tmp_path, **fixture_kwargs)
    )
    emergency_sha = hashlib.sha256(emergency_path.read_bytes()).hexdigest()
    if mutation == "emergency_sha":
        emergency_sha = "0" * 64
    elif mutation == "nonce":
        emergency = json.loads(emergency_path.read_text(encoding="utf-8"))
        emergency["child"]["worker_nonce"] = "b" * 32
        emergency_path.write_text(
            json.dumps(emergency, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        emergency_sha = hashlib.sha256(emergency_path.read_bytes()).hexdigest()
    elif mutation == "disposition":
        emergency = json.loads(emergency_path.read_text(encoding="utf-8"))
        emergency["disposition"] = "exact_child_exited"
        emergency_path.write_text(
            json.dumps(emergency, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        emergency_sha = hashlib.sha256(emergency_path.read_bytes()).hexdigest()
    elif mutation == "outer_run":
        outer = json.loads(receipt_path.read_text(encoding="utf-8"))
        outer["run_id"] = "other-parent-run"
        receipt_path.write_text(
            json.dumps(outer, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "non_worker":
        outer = json.loads(receipt_path.read_text(encoding="utf-8"))
        outer["scenario"] = "post_response_loss"
        receipt_path.write_text(
            json.dumps(outer, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif not fixture_kwargs:
        store = BTCRuntimeStore(runtime_root)
        recovered = store.recover()
        assert recovered.blockers == ()
        event = next(
            item
            for item in recovered.events
            if item["event_type"] == "order_lifecycle"
        )
        payload = event["payload"]
        if mutation == "close_lifecycle":
            payload = json.loads(json.dumps(payload))
            payload["oms"]["client_order_id"] = "btcDPclose0004"
            payload["order_plan"]["client_order_id"] = "btcDPclose0004"
            payload["order_plan"]["action"] = "close_long"
            payload["order_plan"]["risk_reducing_only"] = True
        store.append(
            event_type="order_lifecycle",
            payload=payload,
            state_after=recovered.state,
            idempotency_key="duplicate-lifecycle",
            timestamp_utc="2026-08-09T00:00:05+00:00",
            run_id=recovered.state["runtime"]["run_id"],
            safety=recovered.state["safety"],
        )
        store.checkpoint(recovered.state)

    with pytest.raises(FaultDrillReceiptError, match=expected):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            worker_parent_emergency_receipt=emergency_path,
            worker_parent_emergency_receipt_sha256=emergency_sha,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def _identity_archive_fixture(
    tmp_path: Path,
    *,
    account_identity: str = "b" * 64,
    credential_identity: str = "quant-system.okx-demo.trade",
    current_head: str = "",
    source_archive_head: str = "",
) -> Path:
    """Write a minimal immutable identity-only archive outside the repo."""

    archive_root = (tmp_path / "identity-anchor").resolve()
    snapshots = archive_root / "source_snapshots"
    receipts = archive_root / "receipts"
    snapshots.mkdir(parents=True)
    receipts.mkdir()
    current_head = current_head or _head()
    source_archive_head = source_archive_head or current_head
    archive_id = "btc-owned-id-restore-fixture-01"
    owner_marker = (tmp_path / "identity-anchor-owner.json").resolve()
    owner_payload = {
        "schema_version": "quant_btc_external_evidence_owner_v1",
        "owner": "quant-system-agent-/btc",
        "immutable_archives_only": True,
        "repository_owner_identity": "a" * 64,
    }
    owner_marker.write_text(
        json.dumps(owner_payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    sources = {
        "source_snapshots/runtime_events.jsonl": b"{}\n",
        "source_snapshots/runtime_state.json": b"{}\n",
        "source_snapshots/receipt_ledger.jsonl": b"{}\n",
        "receipts/0001-derived.json": b"{}\n",
    }
    for relative, raw in sources.items():
        target = archive_root / relative
        target.write_bytes(raw)
    verification = {
        "schema_version": "btc_owned_id_restore_archive_v1",
        "archive_id": archive_id,
        "current_head": current_head,
        "source_head": current_head,
        "source_archive_head": source_archive_head,
        "identity_only": True,
        "status": "verified_fail_closed",
        "decision": "owned_id_restore_admission_only",
        "execution_identity": {
            "account_identity": account_identity,
            "credential_identity": credential_identity,
        },
        "owner_marker_sha256": hashlib.sha256(owner_marker.read_bytes()).hexdigest(),
        "safety": {
            "live_allowed": False,
            "network_used": False,
            "order_endpoint_allowed": False,
            "paper_allowed": False,
            "private_endpoint_allowed": False,
            "promotion_allowed": False,
            "real_order_submitted": False,
            "secret_read": False,
            "transfer_allowed": False,
            "withdraw_allowed": False,
        },
    }
    verification_path = archive_root / "verification.json"
    verification_path.write_text(
        json.dumps(verification, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    files = [
        {
            "archive_relative_path": relative,
            "kind": kind,
            "sha256": hashlib.sha256((archive_root / relative).read_bytes()).hexdigest(),
            "size_bytes": (archive_root / relative).stat().st_size,
        }
        for relative, kind in (
            ("source_snapshots/runtime_events.jsonl", "runtime_events"),
            ("source_snapshots/runtime_state.json", "runtime_state"),
            ("source_snapshots/receipt_ledger.jsonl", "receipt_ledger"),
            ("receipts/0001-derived.json", "derived_restore_receipt"),
            ("verification.json", "verification"),
        )
    ]
    manifest = {
        "schema_version": "btc_owned_id_restore_archive_v1",
        "archive_id": archive_id,
        "current_head": current_head,
        "source_archive_head": source_archive_head,
        "identity_only": True,
        "immutable": True,
        "unique_directory_no_overwrite": True,
        "status": "verified_fail_closed",
        "opening_allowed": False,
        "order_capability_restored": False,
        "position_restored": False,
        "paper_unlock": False,
        "promotion_unlock": False,
        "live_unlock": False,
        "execution_identity": verification["execution_identity"],
        "owner_marker": {
            "immutable_archives_only": True,
            "path": str(owner_marker),
            "repository_owner_identity": owner_payload["repository_owner_identity"],
            "sha256": verification["owner_marker_sha256"],
        },
        "files": files,
        "verification_sha256": hashlib.sha256(verification_path.read_bytes()).hexdigest(),
        "safety": verification["safety"],
    }
    manifest["manifest_hash"] = fault_drill_module._identity_archive_canonical_sha256(
        manifest
    )
    manifest_path = archive_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    completed = {
        "schema_version": "btc_owned_id_restore_archive_completion_v1",
        "archive_id": archive_id,
        "immutable_after_write": True,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "verification_sha256": hashlib.sha256(verification_path.read_bytes()).hexdigest(),
    }
    (archive_root / "COMPLETED.json").write_text(
        json.dumps(completed, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return archive_root


def _rewrite_runtime_account_identity(
    runtime_root: Path,
    account_identity: str,
) -> None:
    events_path = runtime_root.joinpath("events.jsonl")
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    rebuilt: list[dict[str, Any]] = []
    previous_hash = ""
    for event in events:
        body = dict(event)
        body.pop("event_hash", None)
        state_after = dict(body["state_after"])
        owned_restore = dict(
            state_after["risk_control"]["owned_id_restore"]
        )
        owned_restore["account_identity"] = account_identity
        state_after["risk_control"] = dict(state_after["risk_control"])
        state_after["risk_control"]["owned_id_restore"] = owned_restore
        body["state_after"] = state_after
        body["previous_event_hash"] = previous_hash
        body["event_hash"] = runtime_store_module._digest(
            {key: value for key, value in body.items() if key != "event_hash"}
        )
        rebuilt.append(body)
        previous_hash = body["event_hash"]
    events_path.write_bytes(
        b"".join(
            runtime_store_module._canonical(event) + b"\n"
            for event in rebuilt
        )
    )
    checkpoint_path = runtime_root.joinpath("state.json")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint_state = dict(rebuilt[-1]["state_after"])
    checkpoint_body = {
        key: value for key, value in checkpoint.items() if key != "checkpoint_hash"
    }
    checkpoint_body["state"] = checkpoint_state
    checkpoint_body["last_event_hash"] = previous_hash
    checkpoint["state"] = checkpoint_state
    checkpoint["last_event_hash"] = previous_hash
    checkpoint["checkpoint_hash"] = runtime_store_module._digest(checkpoint_body)
    checkpoint_path.write_bytes(runtime_store_module._canonical(checkpoint) + b"\n")


def _rewrite_runtime_owned_id_restore_source_head(
    runtime_root: Path,
    archive_source_head: str,
    *,
    archive_event_type: str = "owned_id_restore_applied",
) -> dict[str, Any]:
    """Build current-runtime, archive-provenance, current-runtime events."""

    store = BTCRuntimeStore(runtime_root)
    recovery = store.recover()
    assert recovery.blockers == ()
    assert recovery.truncated_tail is False
    state_after = json.loads(json.dumps(recovery.state))
    risk_control = dict(state_after["risk_control"])
    owned_restore = dict(risk_control["owned_id_restore"])
    owned_restore["source_head"] = archive_source_head
    risk_control["owned_id_restore"] = owned_restore
    state_after["risk_control"] = risk_control
    current_source_head = str(recovery.events[0]["payload"]["source_head"])
    run_id = str(recovery.events[-1]["run_id"])
    safety = recovery.events[-1]["safety"]
    store.append(
        event_type=archive_event_type,
        payload={"source_head": archive_source_head},
        state_after=state_after,
        idempotency_key="owned-id-restore-archive-provenance",
        timestamp_utc="2026-08-09T00:00:02+00:00",
        run_id=run_id,
        safety=safety,
    )
    store.append(
        event_type="private_ws_reconciled",
        payload={"private_ws": {"source_head": current_source_head}},
        state_after=state_after,
        idempotency_key="private-ws-current-runtime",
        timestamp_utc="2026-08-09T00:00:02+00:00",
        run_id=run_id,
        safety=safety,
    )
    store.checkpoint(state_after)
    return state_after


def _append_recovery_source_tail(
    runtime_root: Path,
    recovery_head: str,
) -> None:
    """Append the read-only recovery tail without replacing incident history."""

    store = BTCRuntimeStore(runtime_root)
    recovered = store.recover()
    assert recovered.blockers == ()
    assert recovered.truncated_tail is False
    state_after = json.loads(json.dumps(recovered.state))
    state_after["runtime"]["source_head"] = recovery_head
    run_id = str(recovered.state["runtime"]["run_id"])
    safety = recovered.events[-1]["safety"]
    for index, event_type in enumerate(
        ("ledger_uow_committed", "private_ws_reconciled"), start=1
    ):
        store.append(
            event_type=event_type,
            payload={"source_head": recovery_head},
            state_after=state_after,
            idempotency_key=f"append-only-recovery-tail-{index}",
            timestamp_utc=f"2026-08-09T00:00:0{index + 2}+00:00",
            run_id=run_id,
            safety=safety,
        )
    store.checkpoint(state_after)


def test_canonical_binding_derives_all_identities_and_close_id_without_manual_ids(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(tmp_path)
    hash_kwargs = _canonical_runtime_hashes(runtime_root, source_head)
    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **hash_kwargs,
    )
    assert binding.opening_cl_ord_id == "btcDP20a8d1650001"
    assert binding.algo_cl_ord_id == "btcDP20a8d1650001A"
    assert binding.expected_close_cl_ord_id == "btcDP20a8d1650002"
    assert binding.client_order_namespace == "btcDP20a8d165"
    assert binding.binding_path and binding.binding_path.is_file()
    assert binding.binding_sha256 == hashlib.sha256(binding.binding_path.read_bytes()).hexdigest()
    with pytest.raises(FaultDrillReceiptError, match="caller_identity_forbidden"):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root / "second",
            expected_opening_cl_ord_id="attacker",
            **hash_kwargs,
        )


def test_canonical_binding_accepts_ancestry_interval_append_only_source_tail(
    tmp_path: Path,
) -> None:
    incident_head = "0ed51dba33a526d643350b53dca542f7f7ecf44c"
    terminal_head = "4a7d6702dad4ae068abe122ded10fef2ce6c7711"
    run_id = "06c05f1d28b0455daa646c1f9e5482a9"
    receipt_path, runtime_root, binding_root, _ = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=incident_head,
        run_id=run_id,
        receipt_runtime_run_id=run_id,
    )
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", incident_head, terminal_head],
        check=False,
    ).returncode == 0
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", terminal_head, _head()],
        check=False,
    ).returncode == 0
    _append_recovery_source_tail(runtime_root, terminal_head)

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, incident_head),
    )

    assert binding.incident_source_head == incident_head
    assert binding.recovery_code_head == _head()
    assert binding.opening_cl_ord_id == "btcDP06c05f1d0001"


def test_canonical_binding_rejects_runtime_source_head_not_equal_to_terminal(
    tmp_path: Path,
) -> None:
    incident_head = "0ed51dba33a526d643350b53dca542f7f7ecf44c"
    terminal_head = "4a7d6702dad4ae068abe122ded10fef2ce6c7711"
    run_id = "06c05f1d28b0455daa646c1f9e5482a9"
    receipt_path, runtime_root, binding_root, _ = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=incident_head,
        run_id=run_id,
        receipt_runtime_run_id=run_id,
    )
    _append_recovery_source_tail(runtime_root, terminal_head)
    store = BTCRuntimeStore(runtime_root)
    recovered = store.recover()
    state = json.loads(json.dumps(recovered.state))
    state["runtime"]["source_head"] = incident_head
    store.checkpoint(state)

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_source_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, incident_head),
        )


def test_canonical_binding_rejects_zero_order_transport_receipt(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["orders_posted"] = 0
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_receipt_not_eligible",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )


def test_canonical_binding_uses_identity_only_archive_for_missing_state_identity(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434a74d42f5b73292c46120e523",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434a74d42f5b73292c46120e523",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
        state_identity=None,
    )
    archive_root = _identity_archive_fixture(tmp_path)
    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        identity_archive_root=archive_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.account_identity == "b" * 64
    assert binding.credential_identity == "quant-system.okx-demo.trade"
    assert binding.runtime_run_id == "51b9d434a74d42f5b73292c46120e523"
    assert binding.opening_cl_ord_id == "btcDP51b9d4340001"
    assert binding.algo_cl_ord_id == "btcDP51b9d4340001A"
    document = json.loads(binding.binding_path.read_text(encoding="utf-8"))
    anchor = document["identity_archive_anchor"]
    assert anchor["source"] == "immutable_owned_id_restore_archive"
    assert "owned_triples" not in anchor
    assert "client_order_namespace" not in anchor


@pytest.mark.parametrize(
    "mutate_archive",
    (
        "missing",
        "tamper_file",
        "secret_credential",
        "owner_mismatch",
        "head_mismatch",
    ),
)
def test_canonical_binding_rejects_invalid_identity_archive_before_binding_output(
    tmp_path: Path,
    mutate_archive: str,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        state_identity=None,
    )
    archive_root: Path | None = _identity_archive_fixture(tmp_path)
    if mutate_archive == "missing":
        archive_root = None
    elif mutate_archive == "tamper_file":
        (archive_root / "source_snapshots" / "runtime_events.jsonl").write_bytes(b"tampered\n")
    elif mutate_archive == "secret_credential":
        archive_root = _identity_archive_fixture(
            tmp_path / "secret",
            credential_identity="secret-token-value",
        )
    elif mutate_archive == "owner_mismatch":
        manifest = json.loads((archive_root / "manifest.json").read_text(encoding="utf-8"))
        manifest["owner_marker"]["repository_owner_identity"] = "c" * 64
        (archive_root / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    elif mutate_archive == "head_mismatch":
        archive_root = _identity_archive_fixture(
            tmp_path / "head",
            current_head="f" * 40,
        )

    with pytest.raises(FaultDrillReceiptError, match="identity_(missing|archive)"):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            identity_archive_root=archive_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_requires_archive_identity_to_match_existing_state_identity(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
    )
    archive_root = _identity_archive_fixture(tmp_path, account_identity="c" * 64)
    with pytest.raises(FaultDrillReceiptError, match="identity_archive_identity_mismatch"):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            identity_archive_root=archive_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_checks_matching_archive_against_existing_state_identity(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
    )
    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        identity_archive_root=_identity_archive_fixture(tmp_path),
        **_canonical_runtime_hashes(runtime_root, source_head),
    )
    assert binding.account_identity == "b" * 64
    document = json.loads(binding.binding_path.read_text(encoding="utf-8"))
    assert document["identity_archive_anchor"]["source"] == (
        "immutable_owned_id_restore_archive"
    )


def test_canonical_binding_accepts_verified_historical_prefix_and_current_run_suffix(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
    )

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.runtime_run_id == "51b9d434c0ffee1234567890abcdef12"
    assert binding.failed_receipt_run_id == "cf58b54b-s1-post-response-loss-fixture"
    assert binding.opening_cl_ord_id == "btcDP51b9d4340001"
    assert binding.algo_cl_ord_id == "btcDP51b9d4340001A"
    assert binding.expected_close_cl_ord_id == "btcDP51b9d4340002"


def test_canonical_binding_accepts_legacy_empty_prefix_and_current_run_suffix(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        legacy_empty_prefix_event_count=5,
    )

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.runtime_run_id == "51b9d434c0ffee1234567890abcdef12"
    assert binding.opening_cl_ord_id == "btcDP51b9d4340001"
    assert binding.algo_cl_ord_id == "btcDP51b9d4340001A"


def test_canonical_binding_accepts_monotonic_multihead_runtime_source_chain(
    tmp_path: Path,
) -> None:
    """Historical source heads may advance only along the verified Git chain."""

    historical_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    intermediate_head = "8ccc2b3d3377eadcf14afc21414432ccff372083"
    current_head = _head()
    for ancestor, descendant in (
        (historical_head, intermediate_head),
        (intermediate_head, current_head),
    ):
        assert subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
        ).returncode == 0
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=current_head,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="42254df9-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
        event_source_heads=(historical_head, intermediate_head, current_head),
    )

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.runtime_run_id == "51b9d434c0ffee1234567890abcdef12"
    assert binding.opening_cl_ord_id == "btcDP51b9d4340001"
    assert binding.algo_cl_ord_id == "btcDP51b9d4340001A"


def test_canonical_binding_ignores_owned_id_restore_applied_archive_source_provenance(
    tmp_path: Path,
) -> None:
    """Archive provenance is not a runtime-code source declaration."""

    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
    )
    _rewrite_runtime_owned_id_restore_source_head(
        runtime_root,
        "904296e6a0758a138964f3fb801ceeba8cd9ad7e",
    )

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.runtime_run_id == "51b9d434c0ffee1234567890abcdef12"
    assert binding.opening_cl_ord_id == "btcDP51b9d4340001"
    assert binding.algo_cl_ord_id == "btcDP51b9d4340001A"


def test_canonical_binding_ignores_owner_marker_audit_source_provenance(
    tmp_path: Path,
) -> None:
    """Historical marker audit provenance is not an event runtime-code head."""

    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="509a1bf9-s5-reconnect-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
    )
    historical_marker_head = "b830fc862813fdcb965ad95b97208d3e7790ac9c"
    store = BTCRuntimeStore(runtime_root)
    recovered = store.recover()
    assert recovered.blockers == ()
    state_after = json.loads(json.dumps(recovered.state))
    state_after["runtime"]["fresh_state_emergency_exit"] = {
        "owner_marker_audit": {
            "source_head": historical_marker_head,
            "process_id": 40360,
        }
    }
    store.append(
        event_type="private_ws_reconciled",
        payload={"source_head": source_head},
        state_after=state_after,
        idempotency_key="current-runtime-with-historical-marker-audit",
        timestamp_utc="2026-08-09T00:00:03+00:00",
        run_id="51b9d434c0ffee1234567890abcdef12",
        safety=recovered.events[-1]["safety"],
    )
    store.checkpoint(state_after)

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.opening_cl_ord_id == "btcDP51b9d4340001"
    assert binding.algo_cl_ord_id == "btcDP51b9d4340001A"


def test_runtime_source_head_rejects_nonprovenance_nested_mismatch_and_audit_only_head() -> None:
    current_head = _head()
    historical_marker_head = "b830fc862813fdcb965ad95b97208d3e7790ac9c"

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_source_mismatch",
    ):
        fault_drill_module._runtime_event_source_head(
            {
                "event_type": "runtime_status",
                "payload": {
                    "source_head": current_head,
                    "runtime_status": {"source_head": historical_marker_head},
                },
            }
        )

    assert (
        fault_drill_module._runtime_event_source_head(
            {
                "event_type": "runtime_status",
                "payload": {
                    "fresh_state_emergency_exit": {
                        "owner_marker_audit": {
                            "source_head": historical_marker_head,
                        }
                    }
                },
            }
        )
        == ""
    )
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_source_mismatch",
    ):
        fault_drill_module._runtime_event_source_head(
            {
                "event_type": "runtime_status",
                "payload": {
                    "source_head": "not-a-git-head",
                    "fresh_state_emergency_exit": {
                        "owner_marker_audit": {
                            "source_head": historical_marker_head,
                        }
                    },
                },
            }
        )


def test_canonical_binding_rejects_archive_source_in_ordinary_runtime_event(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
    )
    _rewrite_runtime_owned_id_restore_source_head(
        runtime_root,
        "904296e6a0758a138964f3fb801ceeba8cd9ad7e",
        archive_event_type="runtime_status",
    )

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_source_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_accepts_legacy_missing_runtime_state_source_head(
    tmp_path: Path,
) -> None:
    """A missing legacy state key may defer only to the proven event chain."""

    historical_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    intermediate_head = "8ccc2b3d3377eadcf14afc21414432ccff372083"
    incident_head = "42254df953a31881c532c653c0f0e72a7bd70224"
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", incident_head, _head()],
        check=False,
    ).returncode == 0
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        run_id="c6bc287f4bc44c8a97333eac88caf77e",
        receipt_run_id="42254df9-s1-post-response-loss-fixture",
        receipt_runtime_run_id="c6bc287f4bc44c8a97333eac88caf77e",
        historical_run_ids=("51b9d434a74d42f5b73292c46120e523",),
        event_source_heads=(historical_head, intermediate_head, incident_head),
        owner_marker_recovery_head=incident_head,
        omit_state_runtime_source_head=True,
    )

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.runtime_run_id == "c6bc287f4bc44c8a97333eac88caf77e"
    assert binding.opening_cl_ord_id == "btcDPc6bc287f0001"
    assert binding.algo_cl_ord_id == "btcDPc6bc287f0001A"


@pytest.mark.parametrize("state_runtime_source_head", ("", None, 7, "e" * 40))
def test_canonical_binding_rejects_present_invalid_runtime_state_source_head(
    tmp_path: Path,
    state_runtime_source_head: Any,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=_head(),
        run_id="c6bc287f4bc44c8a97333eac88caf77e",
        receipt_run_id="42254df9-s1-post-response-loss-fixture",
        receipt_runtime_run_id="c6bc287f4bc44c8a97333eac88caf77e",
        state_runtime_source_head=state_runtime_source_head,
    )

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_source_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


@pytest.mark.parametrize(
    "event_source_heads",
    (
        (
            "8ccc2b3d3377eadcf14afc21414432ccff372083",
            "cf58b54b3f96cd0319e6aa321325a975f359e8f8",
            _head(),
        ),
        (
            "cf58b54b3f96cd0319e6aa321325a975f359e8f8",
            "8ccc2b3d3377eadcf14afc21414432ccff372083",
            "8ccc2b3d3377eadcf14afc21414432ccff372083",
        ),
        (
            "cf58b54b3f96cd0319e6aa321325a975f359e8f8",
            7,
            _head(),
        ),
    ),
)
def test_canonical_binding_rejects_regressive_or_nonterminal_runtime_source_chain(
    tmp_path: Path,
    event_source_heads: tuple[Any, ...],
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=_head(),
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="42254df9-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
        event_source_heads=event_source_heads,
    )

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_source_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_rejects_unavailable_runtime_source_ancestry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    intermediate_head = "8ccc2b3d3377eadcf14afc21414432ccff372083"
    current_head = _head()
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=current_head,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="42254df9-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
        event_source_heads=(historical_head, intermediate_head, current_head),
    )
    original_probe = fault_drill_module._bounded_recovery_ancestry_probe

    def unavailable_probe(repo_root: Path, ancestor: str, descendant: str) -> dict[str, str] | None:
        if (ancestor, descendant) == (historical_head, intermediate_head):
            raise FaultDrillReceiptError(
                "fault_drill_recovery_binding_ancestry_unavailable"
            )
        return original_probe(repo_root, ancestor, descendant)

    monkeypatch.setattr(
        fault_drill_module,
        "_bounded_recovery_ancestry_probe",
        unavailable_probe,
    )
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_ancestry_unavailable",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


@pytest.mark.parametrize(
    ("interleaved_run_id", "interleaved_empty_run_id", "foreign_tail_run_id"),
    (
        ("20a8d165b75949759f4c8e7eee6d0c8d", False, ""),
        ("", True, ""),
        ("", False, "20a8d165b75949759f4c8e7eee6d0c8d"),
    ),
)
def test_canonical_binding_rejects_noncontiguous_or_foreign_current_run_tail(
    tmp_path: Path,
    interleaved_run_id: str,
    interleaved_empty_run_id: bool,
    foreign_tail_run_id: str,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
        interleaved_run_id=interleaved_run_id,
        interleaved_empty_run_id=interleaved_empty_run_id,
        foreign_tail_run_id=foreign_tail_run_id,
    )

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_multiple_runtime_runs",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_rejects_receipt_runtime_run_id_mismatch(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["provenance"]["runtime_run_id"] = "forged-runtime-run"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_receipt_run_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_keeps_legacy_single_run_receipt_compatibility(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        receipt_run_id="legacy-failed-receipt-run",
    )

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert binding.runtime_run_id == "20a8d165b75949759f4c8e7eee6d0c8d"
    assert binding.failed_receipt_run_id == "legacy-failed-receipt-run"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("expected_runtime_root_sha256", ""),
        ("expected_runtime_state_sha256", "not-a-sha256"),
        ("expected_runtime_events_sha256", "A" * 64),
    ),
)
def test_canonical_binding_requires_all_external_runtime_hashes_before_output(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(tmp_path)
    hash_kwargs = _canonical_runtime_hashes(runtime_root, source_head)
    hash_kwargs[field] = value
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_runtime_hashes_required",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **hash_kwargs,
        )
    assert not list(binding_root.rglob("*.json"))


@pytest.mark.parametrize("tamper", ["state", "events", "receipt", "namespace", "foreign"])
def test_canonical_binding_tamper_is_fail_closed_before_any_provider(
    tmp_path: Path,
    tamper: str,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(tmp_path)
    hash_kwargs = _canonical_runtime_hashes(runtime_root, source_head)
    if tamper == "state":
        runtime_root.joinpath("state.json").write_text("{}", encoding="utf-8")
    elif tamper == "events":
        runtime_root.joinpath("events.jsonl").write_bytes(
            runtime_root.joinpath("events.jsonl").read_bytes() + b"tamper"
        )
    elif tamper in {"namespace", "foreign"}:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        payload["clOrdId"] = "btcDPforeign0001"
        if tamper == "namespace":
            payload["post_snapshot"]["orders"][0]["clOrdId"] = payload["clOrdId"]
        receipt_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    elif tamper == "receipt":
        receipt_path.write_text(receipt_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(FaultDrillReceiptError):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(
                receipt_path.read_bytes() if tamper != "receipt" else b"wrong"
            ).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **hash_kwargs,
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_rejects_self_consistent_account_identity_tamper(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(tmp_path)
    hash_kwargs = _canonical_runtime_hashes(runtime_root, source_head)
    _rewrite_runtime_account_identity(runtime_root, "c" * 64)
    recovered = BTCRuntimeStore(runtime_root).recover()
    assert not recovered.blockers
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_(state|events)_sha256_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **hash_kwargs,
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_rejects_real_mixed_runtime_root_before_bundle_path(
    tmp_path: Path,
) -> None:
    receipt_path = Path(
        r"D:\vibe coding\Obsidian\量化系统\immutable-evidence\btc-demo-final-904296e6-20260809T114754189Z-ca903c6d1897-receipts\btc_okx_demo_fault_drill\904296e6a0758a138964f3fb801ceeba8cd9ad7e\post_response_loss\btc-demo-final-904296e6-552d8bc9e038-post-response-loss.json"
    )
    runtime_root = Path(
        r"D:\vibe coding\Obsidian\量化系统\runtime-state\btc-demo-final-904296e6-20260809T115220841Z-552d8bc9e038"
    )
    assert receipt_path.is_file()
    assert runtime_root.is_dir()
    with pytest.raises(FaultDrillReceiptError, match="fault_drill_recovery_binding_"):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256="809f1db0dbc49869aa1e28161354dcc9b8d249597cd15105b55c2069c18b86ca",
            runtime_root=runtime_root,
            repo_root=Path.cwd(),
            expected_incident_source_head="904296e6a0758a138964f3fb801ceeba8cd9ad7e",
            expected_recovery_code_head=_head(),
            binding_external_root=tmp_path / "real-binding",
            expected_runtime_root_sha256="4b4995981bf5470c4ab009aa88b9773b8d48d72c9ec64d2bedccfb0376a85b95",
            expected_runtime_state_sha256="9d9f6a282ea7c82d7e356cda569f8675c587bbb1e9a26c966e7e1ecc7a847572",
            expected_runtime_events_sha256="97b632008207c878f4c8e6558ca457acb816be40528fd753d8ee4f4b72e7976d",
        )
    assert not list((tmp_path / "real-binding").rglob("*.json"))


@pytest.mark.parametrize(
    ("incident_head", "recovery_head", "expected_error"),
    (
        (
            "f" * 40,
            _head(),
            "fault_drill_recovery_binding_ancestry_unavailable",
        ),
        (
            "0afed9b3d62d5516a8d43097a5e617929a722a4d",
            _head(),
            "fault_drill_recovery_binding_incident_not_recovery_ancestor",
        ),
        (
            _head(),
            "f" * 40,
            "fault_drill_recovery_binding_recovery_head_mismatch",
        ),
    ),
)
def test_canonical_binding_cross_head_ancestry_is_fail_closed_before_output(
    tmp_path: Path,
    incident_head: str,
    recovery_head: str,
    expected_error: str,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path
    )
    hash_kwargs = _canonical_runtime_hashes(runtime_root, source_head)
    hash_kwargs.update(
        {
            "expected_incident_source_head": incident_head,
            "expected_recovery_code_head": recovery_head,
        }
    )
    with pytest.raises(FaultDrillReceiptError, match=expected_error):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **hash_kwargs,
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_rejects_caller_supplied_stale_current_head(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path
    )
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_current_head_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            current_head="e" * 40,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_owner_marker_must_retain_incident_source_head(
    tmp_path: Path,
) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path
    )
    lock_path = runtime_root / ".btc_okx_demo_fault_drill_writer.lock"
    marker = json.loads(lock_path.read_text(encoding="utf-8"))
    marker["source_head"] = "e" * 40
    lock_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_owner_marker_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_accepts_ancestor_incident_owner_marker_without_rewrite(
    tmp_path: Path,
) -> None:
    """The source marker is immutable evidence, not a current-code marker."""

    incident_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=incident_head,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
    )
    lock_path = runtime_root / ".btc_okx_demo_fault_drill_writer.lock"
    original_marker_bytes = lock_path.read_bytes()
    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert lock_path.read_bytes() == original_marker_bytes
    document = json.loads(binding.binding_path.read_text(encoding="utf-8"))
    assert document["owner_marker"]["sha256"] == hashlib.sha256(
        original_marker_bytes
    ).hexdigest()
    assert document["owner_marker"]["source_head"] == incident_head
    assert document["owner_marker"]["recovery_code_head"] == incident_head
    assert document["recovery_code_head"] == _head()


def test_canonical_binding_accepts_multihop_ancestor_owner_marker_without_rewrite(
    tmp_path: Path,
) -> None:
    """A prior recovery marker may sit between incident and current HEAD."""

    incident_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    marker_recovery_head = "6b81d4eb8e740690b53d98b435c800427c69da29"
    for ancestor, descendant in (
        (incident_head, marker_recovery_head),
        (marker_recovery_head, _head()),
    ):
        assert subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
        ).returncode == 0
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=marker_recovery_head,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
    )
    lock_path = runtime_root / ".btc_okx_demo_fault_drill_writer.lock"
    original_marker_bytes = lock_path.read_bytes()

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )

    assert lock_path.read_bytes() == original_marker_bytes
    document = json.loads(binding.binding_path.read_text(encoding="utf-8"))
    assert document["owner_marker"]["source_head"] == incident_head
    assert document["owner_marker"]["recovery_code_head"] == marker_recovery_head
    assert document["ancestry_proof"]["owner_marker_multihop"] == {
        "method": "git merge-base and git merge-base --is-ancestor",
        "incident_source_head": incident_head,
        "marker_recovery_code_head": marker_recovery_head,
        "recovery_code_head": _head(),
        "incident_to_marker_merge_base": incident_head,
        "marker_to_recovery_merge_base": marker_recovery_head,
        "incident_is_marker_ancestor": True,
        "marker_is_recovery_ancestor": True,
    }


@pytest.mark.parametrize("marker_recovery_head", ("e" * 40, "not-a-git-head"))
def test_canonical_binding_rejects_unproven_multihop_owner_marker_before_output(
    tmp_path: Path,
    marker_recovery_head: str,
) -> None:
    incident_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=marker_recovery_head,
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="20a8d165b75949759f4c8e7eee6d0c8d",
    )

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_owner_marker_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_canonical_binding_multihop_marker_git_timeout_is_fail_closed_before_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    incident_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    marker_recovery_head = "6b81d4eb8e740690b53d98b435c800427c69da29"
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=marker_recovery_head,
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="20a8d165b75949759f4c8e7eee6d0c8d",
    )
    original_probe = fault_drill_module._bounded_recovery_ancestry_probe

    def timeout_after_primary_edge(
        repo_root: Path,
        ancestor: str,
        descendant: str,
    ) -> dict[str, str] | None:
        if ancestor == incident_head and descendant == _head():
            return original_probe(repo_root, ancestor, descendant)
        raise FaultDrillReceiptError("fault_drill_recovery_binding_ancestry_unavailable")

    monkeypatch.setattr(
        fault_drill_module,
        "_bounded_recovery_ancestry_probe",
        timeout_after_primary_edge,
    )
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_owner_marker_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_bounded_recovery_ancestry_probe_maps_git_timeout_to_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timed_out(*_args: Any, **_kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired("git", 5.0)

    monkeypatch.setattr(fault_drill_module.subprocess, "run", timed_out)
    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_ancestry_unavailable",
    ):
        fault_drill_module._bounded_recovery_ancestry_probe(
            Path.cwd(), "a" * 40, "b" * 40
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_head", "e" * 40),
        ("recovery_code_head", "e" * 40),
        ("runtime_root_sha256", "0" * 64),
    ),
)
def test_canonical_binding_rejects_cross_head_owner_marker_drift_before_output(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    incident_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=incident_head,
    )
    lock_path = runtime_root / ".btc_okx_demo_fault_drill_writer.lock"
    marker = json.loads(lock_path.read_text(encoding="utf-8"))
    marker[field] = value
    lock_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")

    with pytest.raises(
        FaultDrillReceiptError,
        match="fault_drill_recovery_binding_owner_marker_mismatch",
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=receipt_path,
            expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            runtime_root=runtime_root,
            binding_external_root=binding_root,
            **_canonical_runtime_hashes(runtime_root, source_head),
        )
    assert not list(binding_root.rglob("*.json"))


def test_runtime_preflight_accepts_only_bound_cross_head_owner_marker(
    tmp_path: Path,
) -> None:
    incident_head = "cf58b54b3f96cd0319e6aa321325a975f359e8f8"
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(
        tmp_path,
        source_head=incident_head,
        owner_marker_recovery_head=incident_head,
        run_id="51b9d434c0ffee1234567890abcdef12",
        receipt_run_id="cf58b54b-s1-post-response-loss-fixture",
        receipt_runtime_run_id="51b9d434c0ffee1234567890abcdef12",
        historical_run_ids=("20a8d165b75949759f4c8e7eee6d0c8d",),
    )
    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=receipt_path,
        expected_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        runtime_root=runtime_root,
        binding_external_root=binding_root,
        **_canonical_runtime_hashes(runtime_root, source_head),
    )
    controller = okx_demo_runtime_module.OkxDemoPaperRuntimeController(
        config=okx_demo_runtime_module.OkxDemoPaperRuntimeConfig(
            repo_root=Path.cwd(),
            data_db_path=tmp_path / "unused.sqlite",
            output_dir=runtime_root,
        ),
        credential_loader=lambda _service: (_ for _ in ()).throw(
            AssertionError("binding_preflight_must_not_load_credentials")
        ),
        start_worker=False,
    )
    authorization = binding.runtime_authorization(runtime_source_head=_head())

    assert controller._incident_recovery_binding_blockers(authorization) == []
    assert controller._client is None

    authorization["recovery_original_owner_marker_sha256"] = "0" * 64
    assert controller._incident_recovery_binding_blockers(authorization) == [
        "okx_demo_incident_recovery_binding_identity_mismatch"
    ]

    document = json.loads(binding.binding_path.read_text(encoding="utf-8"))
    document["ancestry_proof"]["merge_base"] = "0" * 40
    content = dict(document)
    content.pop("content_sha256")
    document["content_sha256"] = fault_drill_module._sha256(content)
    binding.binding_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    authorization = binding.runtime_authorization(runtime_source_head=_head())
    authorization["recovery_binding_sha256"] = hashlib.sha256(
        binding.binding_path.read_bytes()
    ).hexdigest()
    authorization["recovery_ancestry_proof"] = json.dumps(
        document["ancestry_proof"], sort_keys=True, separators=(",", ":")
    )
    assert controller._incident_recovery_binding_blockers(authorization) == [
        "okx_demo_incident_recovery_ancestry_invalid"
    ]


def test_canonical_binding_overwrite_is_rejected(tmp_path: Path) -> None:
    receipt_path, runtime_root, binding_root, source_head = _canonical_recovery_fixture(tmp_path)
    hash_kwargs = _canonical_runtime_hashes(runtime_root, source_head)
    kwargs = {
        "path": receipt_path,
        "expected_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "runtime_root": runtime_root,
        "current_head": source_head,
        "binding_external_root": binding_root,
        **hash_kwargs,
    }
    BtcOkxDemoFailedReceiptBinding.load(**kwargs)
    with pytest.raises(FaultDrillReceiptError, match="already_exists"):
        BtcOkxDemoFailedReceiptBinding.load(**kwargs)


def test_flat_receipt_binding_accepts_zero_post_superseding_receipt(
    tmp_path: Path,
) -> None:
    failed_receipt = {
        "schema_version": "btc_okx_demo_fault_drill_receipt_v1",
        "source_head": "a" * 40,
        "scenario": "held_position_disconnect",
        "run_id": "flat-superseding-receipt-1",
        "decision": "blocked_frozen_lifecycle_incomplete",
        "execution_requested": True,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
        "orders_posted": 1,
        "incident_recovery": {
            "opening_cl_ord_id": "btcDPfailed0001",
            "algo_cl_ord_id": "btcDPfailed0001A",
            "algo_id": "algo-1",
            "close_cl_ord_id": "btcDPrecover0002",
        },
        "post_snapshot": {
            "orders": [
                {
                    "order_id": "opening-order-1",
                    "clOrdId": "btcDPfailed0001",
                    "state": "filled",
                },
                {
                    "order_id": "close-order-1",
                    "clOrdId": "btcDPrecover0002",
                    "state": "filled",
                },
            ],
            "fills": [
                {
                    "fill_id": "opening-fill-1",
                    "clOrdId": "btcDPfailed0001",
                    "size": "0.01",
                },
                {
                    "fill_id": "close-fill-1",
                    "clOrdId": "btcDPrecover0002",
                    "size": "0.01",
                },
            ],
            "positions": [
                {
                    "instrument_id": "BTC-USDT-SWAP",
                    "position_side": "long",
                    "contracts": "0",
                }
            ],
            "pending_orders": [],
            "pending_algo_orders": [],
            "ledger_reconciliation": {
                "status": "reconciled",
                "current_state_exchange_snapshot_match": True,
            },
        },
    }
    raw = json.dumps(
        failed_receipt,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    path = (tmp_path / "flat-receipt.json").resolve()
    path.write_bytes(raw)

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=path,
        expected_sha256=__import__("hashlib").sha256(raw).hexdigest(),
        expected_opening_cl_ord_id="btcDPfailed0001",
        expected_algo_cl_ord_id="btcDPfailed0001A",
        expected_algo_id="algo-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )

    assert binding.recovery_mode == "already_flat"
    assert len(binding.flat_identity_sha256) == 64
    assert binding.opening_order_id == "opening-order-1"
    assert binding.opening_fill_id == "opening-fill-1"


def test_flat_receipt_missing_fill_order_ids_hashes_like_current_snapshot(
    tmp_path: Path,
) -> None:
    historical_snapshot = {
        "orders": [
            {
                "order_id": "opening-order-1",
                "clOrdId": "btcDPfailed0001",
                "state": "filled",
            },
            {
                "order_id": "close-order-1",
                "clOrdId": "btcDPrecover0002",
                "state": "filled",
            },
        ],
        "fills": [
            {
                "fill_id": "opening-fill-1",
                "clOrdId": "btcDPfailed0001",
                "size": "0.01",
            },
            {
                "fill_id": "close-fill-1",
                "clOrdId": "btcDPrecover0002",
                "size": "0.01",
            },
        ],
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0",
            }
        ],
        "pending_orders": [],
        "pending_algo_orders": [],
        "ledger_reconciliation": {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
        },
    }
    failed_receipt = {
        "schema_version": "btc_okx_demo_fault_drill_receipt_v1",
        "source_head": "a" * 40,
        "scenario": "held_position_disconnect",
        "run_id": "flat-fill-compat-receipt-1",
        "decision": "blocked_frozen_lifecycle_incomplete",
        "execution_requested": True,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
        "orders_posted": 1,
        "incident_recovery": {
            "opening_cl_ord_id": "btcDPfailed0001",
            "algo_cl_ord_id": "btcDPfailed0001A",
            "algo_id": "algo-1",
            "close_cl_ord_id": "btcDPrecover0002",
        },
        "post_snapshot": historical_snapshot,
    }
    raw = json.dumps(
        failed_receipt,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    path = (tmp_path / "flat-fill-compat-receipt.json").resolve()
    path.write_bytes(raw)

    binding = BtcOkxDemoFailedReceiptBinding.load(
        path=path,
        expected_sha256=__import__("hashlib").sha256(raw).hexdigest(),
        expected_opening_cl_ord_id="btcDPfailed0001",
        expected_algo_cl_ord_id="btcDPfailed0001A",
        expected_algo_id="algo-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )
    current_snapshot = json.loads(json.dumps(historical_snapshot))
    current_snapshot["fills"][0]["order_id"] = "opening-order-1"
    current_snapshot["fills"][1]["order_id"] = "close-order-1"
    owned_ids = ("btcDPfailed0001", "btcDPrecover0002")

    assert binding.flat_identity_sha256 == (
        okx_demo_runtime_module._incident_recovery_flat_identity_sha256(
            current_snapshot,
            owned_client_order_ids=owned_ids,
        )
    )
    assert fault_drill_module._flat_recovery_identity_projection(
        historical_snapshot,
        owned_client_order_ids=owned_ids,
    ) == okx_demo_runtime_module._incident_recovery_flat_identity_projection(
        current_snapshot,
        owned_client_order_ids=owned_ids,
    )


def test_flat_receipt_missing_fill_order_id_ambiguous_mapping_is_blocked(
    tmp_path: Path,
) -> None:
    historical_snapshot = {
        "orders": [
            {
                "order_id": "opening-order-1",
                "clOrdId": "btcDPfailed0001",
                "state": "filled",
            },
            {
                "order_id": "opening-order-duplicate",
                "clOrdId": "btcDPfailed0001",
                "state": "filled",
            },
            {
                "order_id": "close-order-1",
                "clOrdId": "btcDPrecover0002",
                "state": "filled",
            },
        ],
        "fills": [
            {
                "fill_id": "opening-fill-1",
                "clOrdId": "btcDPfailed0001",
                "size": "0.01",
            },
            {
                "fill_id": "close-fill-1",
                "clOrdId": "btcDPrecover0002",
                "size": "0.01",
            },
        ],
        "positions": [
            {
                "instrument_id": "BTC-USDT-SWAP",
                "position_side": "long",
                "contracts": "0",
            }
        ],
        "pending_orders": [],
        "pending_algo_orders": [],
        "ledger_reconciliation": {
            "status": "reconciled",
            "current_state_exchange_snapshot_match": True,
        },
    }
    failed_receipt = {
        "schema_version": "btc_okx_demo_fault_drill_receipt_v1",
        "source_head": "a" * 40,
        "scenario": "held_position_disconnect",
        "run_id": "flat-fill-ambiguous-receipt-1",
        "decision": "blocked_frozen_lifecycle_incomplete",
        "execution_requested": True,
        "environment": "OKX Demo",
        "instrument_id": "BTC-USDT-SWAP",
        "margin_mode": "isolated",
        "leverage": "3",
        "order_contracts": "0.01",
        "orders_posted": 1,
        "post_snapshot": historical_snapshot,
    }
    raw = json.dumps(
        failed_receipt,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    path = (tmp_path / "flat-fill-ambiguous-receipt.json").resolve()
    path.write_bytes(raw)

    with pytest.raises(
        FaultDrillReceiptError,
        match=(
            "fault_drill_flat_fill_order_id_mapping_ambiguous:"
            "btcDPfailed0001"
        ),
    ):
        BtcOkxDemoFailedReceiptBinding.load(
            path=path,
            expected_sha256=__import__("hashlib").sha256(raw).hexdigest(),
            expected_opening_cl_ord_id="btcDPfailed0001",
            expected_algo_cl_ord_id="btcDPfailed0001A",
            expected_algo_id="algo-1",
            expected_close_cl_ord_id="btcDPrecover0002",
        )


def test_incident_recovery_failure_writes_separate_immutable_blocked_receipt(
    tmp_path: Path,
) -> None:
    old_path = (tmp_path / "immutable-old-failed.json").resolve()
    old_bytes = b'{"immutable":"old-failed-receipt"}\n'
    old_path.write_bytes(old_bytes)
    binding = BtcOkxDemoFailedReceiptBinding(
        path=old_path,
        failed_receipt_sha256="a" * 64,
        failed_receipt_source_head="b" * 40,
        failed_receipt_scenario="post_response_loss",
        failed_receipt_run_id="failed-run-1",
        opening_cl_ord_id="btcDPfailed0001",
        opening_order_id="opening-order-1",
        opening_fill_id="opening-fill-1",
        algo_cl_ord_id="btcDPfailed0001A",
        algo_id="algo-incident-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )

    class BlockedRecoveryRuntime(FakeRuntime):
        attempted = False

        def fault_drill_snapshot(self) -> dict[str, Any]:
            snapshot = _snapshot()
            if self.attempted:
                snapshot["risk_control"]["incident_recovery_intents"] = {
                    "a" * 64: {
                        "post_attempted": True,
                        "retry_allowed": False,
                    }
                }
                snapshot["risk_control"]["incident_algo_cancel_intents"] = {
                    "btcDPfailed0001A": {
                        "post_attempted": True,
                        "retry_allowed": False,
                        "status": "intent_persisted",
                    }
                }
            return snapshot

        def recover_fault_drill_incident(
            self,
            *,
            authorization: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            assert authorization["failed_receipt_sha256"] == "a" * 64
            self.attempted = True
            raise RuntimeError("response_lost_after_side_effect")

    service = BtcOkxDemoFaultDrillService()
    config = _config(tmp_path, _head(), "post_response_loss", execute=True)
    receipt = service.run_incident_recovery(
        config,
        runtime=BlockedRecoveryRuntime(),
        binding=binding,
    )
    published = service.publish_terminal_receipt(
        config,
        receipt,
        lifecycle=_terminal_lifecycle(),
    )

    assert published["decision"] == "failed_postflight_frozen"
    assert published["orders_posted"] == 1
    outcome = published["incident_recovery_outcome"]
    assert outcome["close_post_attempted"] is True
    assert outcome["submit_outcome_unknown"] is True
    assert outcome["cancel_post_attempted"] is True
    assert outcome["cancel_outcome_unknown"] is True
    assert outcome["retry_allowed"] is False
    assert Path(receipt["receipt_path"]).is_file()
    persisted = json.loads(Path(receipt["receipt_path"]).read_text(encoding="utf-8"))
    assert persisted["incident_recovery_outcome"] == outcome
    assert Path(receipt["receipt_path"]).resolve() != old_path
    assert old_path.read_bytes() == old_bytes


def test_incident_recovery_historical_post_snapshot_is_not_a_current_post(
    tmp_path: Path,
) -> None:
    """Only the durable current recovery intent may count a recovery POST."""

    binding = BtcOkxDemoFailedReceiptBinding(
        path=(tmp_path / "immutable-failed.json").resolve(),
        failed_receipt_sha256="a" * 64,
        failed_receipt_source_head="b" * 40,
        failed_receipt_scenario="post_response_loss",
        failed_receipt_run_id="failed-run-1",
        opening_cl_ord_id="btcDPfailed0001",
        opening_order_id="opening-order-1",
        opening_fill_id="opening-fill-1",
        algo_cl_ord_id="btcDPfailed0001A",
        algo_id="algo-incident-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )
    binding.path.write_text('{"immutable":"failed"}\n', encoding="utf-8")

    class HistoricalPostSnapshotRuntime(FakeRuntime):
        attempted = False

        def fault_drill_snapshot(self) -> dict[str, Any]:
            snapshot = _snapshot()
            if self.attempted:
                snapshot["exchange"]["orders"] = [
                    {
                        "order_id": "historical-close-order",
                        "client_order_id": "btcDPrecover0002",
                        "state": "filled",
                    }
                ]
                snapshot["exchange"]["fills"] = [
                    {
                        "fill_id": "historical-close-fill",
                        "client_order_id": "btcDPrecover0002",
                        "size": "0.01",
                    }
                ]
                snapshot["risk_control"]["incident_recovery_intents"] = {
                    "a" * 64: {"post_attempted": False, "retry_allowed": False}
                }
                snapshot["risk_control"]["incident_algo_cancel_intents"] = {
                    "btcDPfailed0001A": {
                        "post_attempted": False,
                        "retry_allowed": False,
                    }
                }
            return snapshot

        def recover_fault_drill_incident(
            self,
            *,
            authorization: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            assert authorization["failed_receipt_sha256"] == "a" * 64
            self.attempted = True
            raise RuntimeError("read_only_recovery_blocked")

    receipt = BtcOkxDemoFaultDrillService().run_incident_recovery(
        _config(tmp_path, _head(), "post_response_loss", execute=True),
        runtime=HistoricalPostSnapshotRuntime(),
        binding=binding,
    )

    assert receipt["orders_posted"] == 0
    assert receipt["incident_recovery"]["orders_posted"] == 0
    assert receipt["incident_recovery_outcome"]["close_post_attempted"] is False
    assert receipt["incident_recovery_outcome"]["cancel_post_attempted"] is False


@pytest.mark.parametrize("final_proven", [True, False])
def test_incident_recovery_receipt_preserves_runtime_final_projection(
    tmp_path: Path,
    final_proven: bool,
) -> None:
    """The receipt projects verified runtime facts and never infers cleanup state."""

    binding = BtcOkxDemoFailedReceiptBinding(
        path=(tmp_path / "immutable-failed.json").resolve(),
        failed_receipt_sha256="a" * 64,
        failed_receipt_source_head="b" * 40,
        failed_receipt_scenario="post_response_loss",
        failed_receipt_run_id="failed-run-1",
        opening_cl_ord_id="btcDPfailed0001",
        opening_order_id="opening-order-1",
        opening_fill_id="opening-fill-1",
        algo_cl_ord_id="btcDPfailed0001A",
        algo_id="algo-incident-1",
        expected_close_cl_ord_id="btcDPrecover0002",
    )

    class ProjectionRuntime:
        posts: list[str] = []

        def fault_drill_snapshot(self) -> dict[str, Any]:
            return _snapshot()

        def recover_fault_drill_incident(
            self,
            *,
            authorization: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            assert authorization["opening_cl_ord_id"] == "btcDPfailed0001"
            return {
                "decision": "incident_recovery_completed_safe_flat",
                "orders_posted": 0,
                "no_order_or_cancel_post": True,
                "private_ws_reconciled": final_proven,
                "ledger_reconciled": final_proven,
                "final_flat": final_proven,
                "final_no_pending_orders": final_proven,
                "final_no_pending_algo_orders": final_proven,
                "final_no_unresolved_intents": final_proven,
                "final_ledger_reconciled": final_proven,
                "final_private_ws_reconciled": final_proven,
                "entry_order_id": "opening-order-1" if final_proven else "",
                "close_order_id": "close-order-1" if final_proven else "",
                "entry_fill_ids": ["opening-fill-1"] if final_proven else [],
                "close_fill_ids": ["close-fill-1"] if final_proven else [],
                "algo_id": "algo-incident-1" if final_proven else "",
                "ledger_reconciled": final_proven,
                "private_ws_reconciled": final_proven,
            }

    runtime = ProjectionRuntime()
    receipt = BtcOkxDemoFaultDrillService().run_incident_recovery(
        _config(tmp_path, _head(), "post_response_loss", execute=True),
        runtime=runtime,
        binding=binding,
    )

    for field in (
        "final_flat",
        "final_no_pending_orders",
        "final_no_pending_algo_orders",
        "final_no_unresolved_intents",
        "final_ledger_reconciled",
        "final_private_ws_reconciled",
    ):
        assert receipt[field] is final_proven
    assert receipt["orders_posted"] == 0
    assert receipt["entry_order_id"] == (
        "opening-order-1" if final_proven else ""
    )
    assert receipt["close_order_id"] == (
        "close-order-1" if final_proven else ""
    )
    assert receipt["algo_id"] == ("algo-incident-1" if final_proven else "")
    assert receipt["incident_recovery_outcome"]["ledger_reconciled"] is final_proven
    assert receipt["incident_recovery_outcome"]["private_ws_reconciled"] is final_proven
    assert runtime.posts == []


def test_partial_fill_incomplete_fixture_is_simulation_and_fail_closed(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        result={
            "decision": "completed_safe_flat",
            "orders_posted": 2,
            "entry_attempts": 1,
            "entry_retry_count": 0,
            "entry_fill_contracts": "0.01",
            "entry_order_type": "fok",
            "entry_fill_classification": "partial_fill",
            "discrepancy_classification": "expected_partial_fill_recovery",
            "broker_truth_verified": True,
            "disconnect_observed": True,
            "reconnect_bounded": True,
            "four_way_reconciliation": {"match": True},
            "operator_ack_required": True,
            "operator_acknowledged": True,
            "opening_allowed": False,
            "pre_reconciliation_sha256": "a" * 64,
            "post_reconciliation_sha256": "b" * 64,
        }
    )
    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "partial_fill_disconnect", execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert receipt["simulation_only"] is True
    assert "fault_drill_partial_fill_entry_order_type_not_ioc" in receipt["blockers"]
    assert "fault_drill_partial_fill_provenance_invalid:runtime_boundary" in receipt[
        "blockers"
    ]
    assert receipt["scenario_order_contract_cap"] == "0.03"
    assert receipt["continuous_order_contract_cap"] == "0.01"
    assert receipt["orders_posted"] == 2
    assert receipt["order_contracts"] == "0.03"
    assert receipt["max_notional_usdt"] == "25"
    assert runtime.run_calls == ["partial_fill_disconnect"]


def test_partial_fill_agent8_attack_shape_cannot_cross_receipt_boundary(
    tmp_path: Path,
) -> None:
    attack = {
        "decision": "completed_safe_flat",
        "simulation_only": False,
        "entry_order_type": "fok",
        "entry_fill_contracts": "0.03",
        "synthetic": True,
        "clOrdId": "",
        "algoClOrdId": "",
    }
    blockers = fault_drill_module._result_blockers(
        "partial_fill_disconnect",
        attack,
    )
    assert blockers
    assert "fault_drill_partial_fill_entry_order_type_not_ioc" in blockers
    assert "fault_drill_partial_fill_contracts_not_strict_partial" in blockers
    assert "fault_drill_partial_fill_synthetic_evidence_invalid" in blockers
    assert "fault_drill_partial_fill_opening_clordid_invalid" in blockers

    runtime = FakeRuntime(result=attack)
    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "partial_fill_disconnect", execute=True),
        runtime=runtime,
    )
    assert receipt["decision"] == "failed_postflight_frozen"
    assert receipt["simulation_only"] is True
    assert receipt["decision"] != "completed_safe_flat"
    assert receipt["live_allowed"] is False


def test_partial_fill_format_valid_foreign_authority_ids_are_blocked() -> None:
    source_head = _head()
    runtime_run_id = "runtime-1"
    namespace = "btcDPruntime-"
    projection = {
        "authority_version": "okx_demo_partial_fill_authority_v1",
        "runtime_boundary": (
            "OkxDemoPaperRuntimeController.run_fault_drill_scenario"
        ),
        "runtime_version": "okx_demo_paper_runtime_v1",
        "controller_type": "OkxDemoPaperRuntimeController",
        "source_head": source_head,
        "runtime_run_id": runtime_run_id,
        "identity_namespace": namespace,
        "clOrdId": namespace + "0001",
        "closeClOrdId": namespace + "0002",
        "algoClOrdId": namespace + "0001A",
        "entry_order_id": "order-authoritative",
        "close_order_id": "close-authoritative",
        "entry_fill_ids": ["fill-authoritative"],
        "close_fill_ids": ["close-fill-authoritative"],
        "entry_fill_order_ids": ["order-authoritative"],
        "close_fill_order_ids": ["close-authoritative"],
        "entry_fill_client_order_ids": [namespace + "0001"],
        "close_fill_client_order_ids": [namespace + "0002"],
        "entry_order_client_order_id": namespace + "0001",
        "close_order_client_order_id": namespace + "0002",
        "algo_id": "algo-authoritative",
        "algo_parent_cl_ord_id": namespace + "0001",
        "entry_fill_contracts": "0.01",
        "close_fill_contracts": "0.01",
        "pre_reconciliation_sha256": "a" * 64,
        "post_reconciliation_sha256": "b" * 64,
        "final_flat": True,
        "final_no_pending_orders": True,
        "final_no_pending_algo_orders": True,
        "final_ledger_reconciled": True,
        "final_private_ws_reconciled": True,
    }
    authority_hash = fault_drill_module._sha256(
        {
            "authority_version": "okx_demo_partial_fill_authority_v1",
            "identity_projection": projection,
        }
    )
    provenance = {
        "runtime_boundary": projection["runtime_boundary"],
        "runtime_version": projection["runtime_version"],
        "attestation_version": "okx_demo_partial_runtime_attestation_v1",
        "controller_type": projection["controller_type"],
        "environment": "OKX Demo",
        "source": "exchange_snapshot",
        "source_head": source_head,
        "real_exchange_observation": True,
        "fixture": False,
        "simulation": False,
        "synthetic": False,
        "simulation_only": False,
        "runtime_run_id": runtime_run_id,
        "authority_version": projection["authority_version"],
        "identity_namespace": namespace,
        "authoritative_receipt_sha256": authority_hash,
        "authoritative_identity_projection": projection,
    }
    result = {
        "entry_attempts": 1,
        "entry_retry_count": 0,
        "entry_fill_classification": "partial_fill",
        "discrepancy_classification": "expected_partial_fill_recovery",
        "entry_order_type": "ioc",
        "requested_contracts": "0.03",
        "entry_fill_contracts": "0.01",
        "entry_order_filled_contracts": "0.01",
        "entry_fill_sum_contracts": "0.01",
        "entry_position_contracts": "0.01",
        "close_fill_contracts": "0.01",
        "close_order_filled_contracts": "0.01",
        "broker_truth_verified": True,
        "simulation_only": False,
        "synthetic": False,
        "fixture": False,
        "simulation": False,
        "real_exchange_observation": True,
        "provenance": provenance,
        "_runtime_attestation": dict(provenance),
        "runtime_receipt_sha256": authority_hash,
        "authoritative_receipt_sha256": authority_hash,
        "identity_namespace": namespace,
        "authoritative_identity_projection": projection,
        "clOrdId": namespace + "0001",
        "closeClOrdId": namespace + "0002",
        "algoClOrdId": namespace + "0001A",
        "entry_order_id": "order-foreign",
        "close_order_id": "close-foreign",
        "entry_fill_ids": ["fill-foreign"],
        "close_fill_ids": ["close-fill-foreign"],
        "entry_fill_order_ids": ["order-foreign"],
        "close_fill_order_ids": ["close-foreign"],
        "entry_fill_client_order_ids": [namespace + "0001"],
        "close_fill_client_order_ids": [namespace + "0002"],
        "entry_order_client_order_id": namespace + "0001",
        "close_order_client_order_id": namespace + "0002",
        "algo_id": "algo-foreign",
        "algo_parent_cl_ord_id": namespace + "0001",
    }

    blockers = fault_drill_module._result_blockers(
        "partial_fill_disconnect",
        result,
        observed_runtime_run_ids=(runtime_run_id, runtime_run_id),
        expected_source_head=source_head,
    )

    assert "fault_drill_partial_fill_authoritative_identity_foreign_order_id" in blockers
    assert "fault_drill_partial_fill_authoritative_identity_foreign_algo_id" in blockers
    assert "fault_drill_partial_fill_authoritative_identity_foreign_fill_id" in blockers


def test_partial_fill_foreign_format_valid_receipt_stays_simulation_only(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(
        result={
            "orders_posted": 2,
            "entry_attempts": 1,
            "entry_retry_count": 0,
            "entry_order_type": "ioc",
            "requested_contracts": "0.03",
            "entry_fill_contracts": "0.01",
            "entry_order_filled_contracts": "0.01",
            "entry_fill_sum_contracts": "0.01",
            "entry_position_contracts": "0.01",
            "entry_fill_classification": "partial_fill",
            "discrepancy_classification": "expected_partial_fill_recovery",
            "broker_truth_verified": True,
            "synthetic": False,
            "fixture": False,
            "simulation": False,
            "real_exchange_observation": True,
            "clOrdId": "btcDPforeign0001",
            "closeClOrdId": "btcDPforeign0002",
            "algoClOrdId": "btcDPforeign0001A",
            "entry_order_id": "order-foreign",
            "close_order_id": "close-foreign",
            "entry_fill_ids": ["fill-foreign"],
            "close_fill_ids": ["close-fill-foreign"],
            "entry_fill_order_ids": ["order-foreign"],
            "close_fill_order_ids": ["close-foreign"],
            "entry_fill_client_order_ids": ["btcDPforeign0001"],
            "close_fill_client_order_ids": ["btcDPforeign0002"],
            "entry_order_client_order_id": "btcDPforeign0001",
            "close_order_client_order_id": "btcDPforeign0002",
            "algo_id": "algo-foreign",
            "algo_parent_cl_ord_id": "btcDPforeign0001",
            "close_fill_contracts": "0.01",
            "close_order_filled_contracts": "0.01",
            "four_way_reconciliation": {"match": True},
            "operator_ack_required": True,
            "operator_acknowledged": True,
            "opening_allowed": False,
            "decision": "completed_safe_flat",
            "pre_reconciliation_sha256": "a" * 64,
            "post_reconciliation_sha256": "b" * 64,
        }
    )
    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "partial_fill_disconnect", execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert receipt["simulation_only"] is True
    assert receipt["live_allowed"] is False
    assert (
        "fault_drill_partial_fill_authoritative_identity_projection_missing"
        in receipt["blockers"]
    )


def test_partial_fill_zero_or_full_fill_is_not_a_partial_pass() -> None:
    for classification in ("zero_fill", "full_fill"):
        blockers = fault_drill_module._result_blockers(
            "partial_fill_disconnect",
            {
                "entry_attempts": 1,
                "entry_retry_count": 0,
                "entry_fill_classification": classification,
                "broker_truth_verified": True,
                "disconnect_observed": False,
                "reconnect_bounded": False,
                "four_way_reconciliation": {"match": False},
                "operator_acknowledged": True,
                "opening_allowed": False,
                "orders_posted": 1,
                "pre_reconciliation_sha256": "a" * 64,
                "post_reconciliation_sha256": "b" * 64,
            },
        )
        assert "fault_drill_partial_fill_not_exchange_observed_partial" in blockers


@pytest.mark.parametrize("fill_contracts", ["0", "0.03", "-0.01", "NaN"])
def test_partial_fill_contract_boundary_is_strictly_decimal_partial(
    fill_contracts: str,
) -> None:
    blockers = fault_drill_module._result_blockers(
        "partial_fill_disconnect",
        {
            "entry_attempts": 1,
            "entry_retry_count": 0,
            "entry_fill_classification": "partial_fill",
            "discrepancy_classification": "expected_partial_fill_recovery",
            "entry_order_type": "ioc",
            "requested_contracts": "0.03",
            "entry_fill_contracts": fill_contracts,
            "broker_truth_verified": True,
        },
    )
    assert "fault_drill_partial_fill_contracts_not_strict_partial" in blockers


def test_partial_fill_cap_over_25_blocks_before_runtime(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    config = _config(tmp_path, _head(), "partial_fill_disconnect", execute=True)
    config = BtcOkxDemoFaultDrillConfig(
        **{
            **config.__dict__,
            "max_notional_usdt": "25.01",
        }
    )
    receipt = BtcOkxDemoFaultDrillService().run(config, runtime=runtime)
    assert receipt["decision"] == "blocked_preflight"
    assert runtime.run_calls == []


def test_terminal_receipt_persists_valid_dead_man_expiry_evidence(
    tmp_path: Path,
) -> None:
    service = BtcOkxDemoFaultDrillService()
    config = _config(tmp_path, _head(), "post_response_loss", execute=False)
    receipt = service.run(config, runtime=None)
    fingerprint = "c" * 64
    lifecycle = _terminal_lifecycle(
        dead_man_terminal_evidence={
            "prior_armed_state": True,
            "armed": False,
            "mode": "expired_timeout_readonly_evidence",
            "disarm_mode": "expired_timeout_readonly_evidence",
            "disarm_post_sent": False,
            "caa_post_count": 0,
            "last_ack_utc": "2026-08-06T00:00:00+00:00",
            "timeout_seconds": 10,
            "expiry_utc": "2026-08-06T00:00:10+00:00",
            "observed_server_time_utc": "2026-08-06T00:00:11+00:00",
            "elapsed_after_expiry_seconds": "1",
            "final_flat": True,
            "final_pending_order_count": 0,
            "final_pending_algo_order_count": 0,
            "exchange_snapshot_sha256": fingerprint,
            "ledger_snapshot_sha256": fingerprint,
            "private_ws_snapshot_sha256": fingerprint,
            "proof_method": (
                "exchange_server_time_plus_final_rest_ws_ledger_fingerprint"
            ),
        }
    )

    published = service.publish_terminal_receipt(
        config,
        receipt,
        lifecycle=lifecycle,
    )
    persisted = json.loads(
        Path(receipt["receipt_path"]).read_text(encoding="utf-8")
    )

    assert published["lifecycle"]["dead_man_disarmed"] is True
    assert (
        persisted["lifecycle"]["dead_man_terminal_evidence"]["caa_post_count"]
        == 0
    )


@pytest.mark.parametrize(
    ("field", "value", "remove"),
    [
        ("mode", None, True),
        ("disarm_mode", None, True),
        ("exchange_snapshot_sha256", None, True),
        ("armed", True, False),
    ],
)
def test_terminal_receipt_blocks_incomplete_dead_man_expiry_evidence(
    tmp_path: Path,
    field: str,
    value: Any,
    remove: bool,
) -> None:
    service = BtcOkxDemoFaultDrillService()
    config = _config(tmp_path, _head(), "post_response_loss", execute=False)
    receipt = service.run(config, runtime=None)
    fingerprint = "c" * 64
    evidence: dict[str, Any] = {
        "prior_armed_state": True,
        "armed": False,
        "mode": "expired_timeout_readonly_evidence",
        "disarm_mode": "expired_timeout_readonly_evidence",
        "disarm_post_sent": False,
        "caa_post_count": 0,
        "last_ack_utc": "2026-08-06T00:00:00+00:00",
        "timeout_seconds": 10,
        "expiry_utc": "2026-08-06T00:00:10+00:00",
        "observed_server_time_utc": "2026-08-06T00:00:11+00:00",
        "elapsed_after_expiry_seconds": "1",
        "final_flat": True,
        "final_pending_order_count": 0,
        "final_pending_algo_order_count": 0,
        "exchange_snapshot_sha256": fingerprint,
        "ledger_snapshot_sha256": fingerprint,
        "private_ws_snapshot_sha256": fingerprint,
        "proof_method": (
            "exchange_server_time_plus_final_rest_ws_ledger_fingerprint"
        ),
    }
    if remove:
        evidence.pop(field)
    else:
        evidence[field] = value

    published = service.publish_terminal_receipt(
        config,
        receipt,
        lifecycle=_terminal_lifecycle(
            dead_man_terminal_evidence=evidence,
        ),
    )

    assert published["decision"] == "blocked_frozen_lifecycle_incomplete"
    assert published["lifecycle"]["dead_man_disarmed"] is False
    assert (
        "fault_drill_lifecycle_dead_man_expiry_evidence_invalid"
        in published["blockers"]
    )


def test_terminal_receipt_blocks_armed_dead_man_without_expiry_markers(
    tmp_path: Path,
) -> None:
    service = BtcOkxDemoFaultDrillService()
    config = _config(tmp_path, _head(), "post_response_loss", execute=False)
    receipt = service.run(config, runtime=None)

    published = service.publish_terminal_receipt(
        config,
        receipt,
        lifecycle=_terminal_lifecycle(
            dead_man_terminal_evidence={"armed": True},
        ),
    )

    assert published["decision"] == "blocked_frozen_lifecycle_incomplete"
    assert published["lifecycle"]["dead_man_disarmed"] is False


def test_execute_requires_flat_pending_free_ledger_and_private_ws_reconciled(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.fault_drill_snapshot = lambda: _snapshot(contracts="0.01")  # type: ignore[method-assign]

    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "post_response_loss", execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "blocked_preflight"
    assert "fault_drill_preflight_position_not_flat" in receipt["blockers"]
    assert receipt["orders_posted"] == 0
    assert runtime.run_calls == []


def test_execute_receipt_is_sanitized_atomic_and_postflight_mismatch_freezes(tmp_path: Path) -> None:
    runtime = FakeRuntime(post=_snapshot(contracts="0.01"))
    service = BtcOkxDemoFaultDrillService()
    config = _config(tmp_path, _head(), "protection_creation_failure", execute=True)

    receipt = service.run(config, runtime=runtime)
    receipt_path = receipt["receipt_path"]
    assert Path(receipt_path).exists() is False
    receipt = service.publish_terminal_receipt(
        config,
        receipt,
        lifecycle=_terminal_lifecycle(),
    ) | {"receipt_path": receipt_path}

    assert receipt["decision"] == "failed_postflight_frozen"
    assert runtime.freeze_calls == ["fault_drill_postflight_not_safe"]
    assert receipt["clOrdId"] == "btcDPdrill0001"
    assert receipt["algoClOrdId"] == "btcDPdrill0001A"
    assert receipt["post_snapshot_sha256"] != receipt["pre_snapshot_sha256"]
    encoded = Path(receipt["receipt_path"]).read_text(encoding="utf-8").lower()
    for forbidden in ("api_key", "secret", "passphrase", "signature", "authorization_header"):
        assert forbidden not in encoded
    with pytest.raises(FaultDrillReceiptError, match="already_exists"):
        service.run(config, runtime=runtime)


def test_flat_postflight_with_orphan_algo_cannot_complete(tmp_path: Path) -> None:
    post = _snapshot()
    post["exchange"]["pending_algo_orders"] = [
        {
            "algo_id": "999",
            "algo_client_order_id": "unknownAlgo",
            "instrument_id": "BTC-USDT-SWAP",
            "state": "live",
        }
    ]
    runtime = FakeRuntime(post=post)

    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "held_position_disconnect", execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert "fault_drill_postflight_pending_algo_orders_present" in receipt["blockers"]


def test_nonterminal_durable_intent_cannot_complete(tmp_path: Path) -> None:
    post = _snapshot()
    post["risk_control"]["pending_order_intents"] = {
        "btcDPdrill0001": {"status": "accepted"}
    }
    runtime = FakeRuntime(post=post)

    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "post_response_loss", execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert "fault_drill_postflight_unresolved_order_intent" in receipt["blockers"]


def test_flat_thread_kill_without_external_child_evidence_cannot_pass(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        result={
            "decision": "worker_aborted_flat",
            "process_id": 0,
            "child_termination": {},
        }
    )

    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), "worker_kill", execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert "fault_drill_worker_kill_external_termination_not_proven" in receipt["blockers"]


def test_empty_reconnect_without_order_fill_position_protection_cannot_pass(tmp_path: Path) -> None:
    runtime = FakeRuntime(
        result={
            "decision": "reconnect_full_reconciliation_completed",
            "orders_posted": 0,
            "position_observed": False,
            "protection_verified": False,
            "pre_reconciliation_sha256": "",
            "post_reconciliation_sha256": "",
        }
    )

    receipt = BtcOkxDemoFaultDrillService().run(
        _config(
            tmp_path,
            _head(),
            "reconnect_full_reconciliation",
            execute=True,
        ),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert (
        "fault_drill_reconnect_full_reconciliation_real_position_evidence_missing"
        in receipt["blockers"]
    )


@pytest.mark.parametrize(
    ("scenario", "required_field", "expected_blocker"),
    (
        (
            "held_position_disconnect",
            "disconnect_observed",
            "fault_drill_held_position_disconnect_not_observed",
        ),
        (
            "post_response_loss",
            "post_response_loss_reconciled",
            "fault_drill_post_response_loss_not_reconciled",
        ),
    ),
)
def test_real_scenarios_require_their_specific_fault_evidence(
    tmp_path: Path,
    scenario: str,
    required_field: str,
    expected_blocker: str,
) -> None:
    runtime = FakeRuntime(
        result={
            "orders_posted": 2,
            "position_observed": True,
            "protection_verified": True,
            "pre_reconciliation_sha256": "a" * 64,
            "post_reconciliation_sha256": "b" * 64,
            required_field: False,
        }
    )

    receipt = BtcOkxDemoFaultDrillService().run(
        _config(tmp_path, _head(), scenario, execute=True),
        runtime=runtime,
    )

    assert receipt["decision"] == "failed_postflight_frozen"
    assert expected_blocker in receipt["blockers"]


class _FakeSpawnedProcess:
    pid = 43210

    def __init__(self) -> None:
        self.kill_calls = 0
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def kill(self) -> None:
        self.kill_calls += 1
        self._returncode = 1

    def wait(self, timeout: float) -> int:
        assert timeout == 15.0
        assert self._returncode is not None
        return self._returncode


class _AliveSpawnedProcess:
    pid = 43210
    returncode = None

    def poll(self) -> None:
        return None


def _worker_envelope(*, nonce: str = "nonce1", create_time: str = "123") -> dict[str, Any]:
    return {
        "process_id": 43210,
        "process_create_time": create_time,
        "worker_nonce": nonce,
        "result": {
            "process_id": 43210,
            "worker_ready_marker_persisted": True,
            "position_observed": True,
            "protection_verified": True,
        },
    }


@pytest.mark.parametrize(
    "envelope",
    (
        _worker_envelope(nonce="wrongnonce"),
        _worker_envelope(create_time="456"),
    ),
)
def test_worker_nonce_or_pid_reuse_mismatch_never_calls_kill(
    monkeypatch: pytest.MonkeyPatch,
    envelope: Mapping[str, Any],
) -> None:
    process = _FakeSpawnedProcess()
    monkeypatch.setattr(fault_drill_cli, "_process_create_time", lambda _pid: "123")

    with pytest.raises(RuntimeError, match="was not killed"):
        fault_drill_cli._kill_exact_spawned_child(
            process,
            envelope=envelope,
            expected_nonce="nonce1",
            expected_process_create_time="123",
            parent_readback={"verified": True},
        )

    assert process.kill_calls == 0


def test_only_exact_spawned_verified_child_is_killed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeSpawnedProcess()
    monkeypatch.setattr(fault_drill_cli, "_process_create_time", lambda _pid: "123")

    returncode = fault_drill_cli._kill_exact_spawned_child(
        process,
        envelope=_worker_envelope(),
        expected_nonce="nonce1",
        expected_process_create_time="123",
        parent_readback={"verified": True},
    )

    assert returncode == 1
    assert process.kill_calls == 1


def test_worker_ready_envelope_is_append_once_immutable(tmp_path: Path) -> None:
    marker = tmp_path / "worker-ready.json"
    first = {"worker_nonce": "nonce1", "process_id": 1}

    fault_drill_cli._write_worker_marker(marker, first)

    with pytest.raises(FileExistsError):
        fault_drill_cli._write_worker_marker(
            marker,
            {"worker_nonce": "nonce2", "process_id": 2},
        )
    assert json.loads(marker.read_text(encoding="utf-8")) == first


@pytest.mark.parametrize(
    "failure_mode",
    (
        "marker_timeout",
        "marker_bad_json",
        "create_time",
        "keyring",
        "get",
        "readback",
    ),
)
def test_worker_parent_failures_persist_visible_emergency_before_supervision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure_mode: str,
) -> None:
    runtime_output = tmp_path / "runtime"
    args = SimpleNamespace(
        runtime_output_dir=runtime_output,
        execute_demo=True,
        data_db_path=tmp_path / "unused.sqlite",
    )
    config = _config(tmp_path, _head(), "worker_kill", execute=True)
    process = _AliveSpawnedProcess()
    nonce = "fixednonce"
    marker = runtime_output / "fault_drill_worker_markers" / f"{config.run_id}.json"
    post_calls: list[str] = []

    class FailingVerifier:
        def verify_fault_drill_worker_ready(self, *_args: Any, **_kwargs: Any) -> None:
            if failure_mode == "get":
                raise RuntimeError("query_only_get_failed")
            if failure_mode == "readback":
                raise RuntimeError("query_only_readback_mismatch")
            raise AssertionError("verifier_should_not_be_called")

    def spawn(*_args: Any, **_kwargs: Any) -> _AliveSpawnedProcess:
        if failure_mode not in {"marker_timeout", "create_time"}:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                "{" if failure_mode == "marker_bad_json" else json.dumps(
                    {
                        **_worker_envelope(nonce=nonce),
                        "worker_ready_marker": {"marker": "ready"},
                    }
                ),
                encoding="utf-8",
            )
        return process

    monkeypatch.setattr(fault_drill_cli.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        fault_drill_cli.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=nonce),
    )
    if failure_mode == "create_time":
        monkeypatch.setattr(
            fault_drill_cli,
            "_process_create_time",
            lambda _pid: (_ for _ in ()).throw(OSError("create-time")),
        )
    else:
        monkeypatch.setattr(
            fault_drill_cli,
            "_process_create_time",
            lambda _pid: "123",
        )
    if failure_mode == "marker_timeout":
        ticks = iter((0.0, 181.0))
        monkeypatch.setattr(fault_drill_cli.time, "monotonic", lambda: next(ticks))
        monkeypatch.setattr(fault_drill_cli.time, "sleep", lambda _seconds: None)
    if failure_mode == "keyring":
        monkeypatch.setattr(
            fault_drill_cli,
            "_runtime",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("keyring_unavailable")),
        )
    elif failure_mode in {"get", "readback"}:
        monkeypatch.setattr(fault_drill_cli, "_runtime", lambda *_args: FailingVerifier())

    supervised: list[Path] = []

    def supervise(_process: Any) -> dict[str, Any]:
        receipts = list(
            tmp_path.glob("btc_okx_demo_fault_drill_emergency/**/*.json")
        )
        assert len(receipts) == 1
        supervised.append(receipts[0])
        return {
            "disposition": "exact_child_exited",
            "exact_child_exited": True,
            "persistent_supervisor_handoff_confirmed": False,
        }

    monkeypatch.setattr(fault_drill_cli, "_supervise_blocked_child", supervise)

    with pytest.raises(fault_drill_cli.WorkerParentEmergency):
        fault_drill_cli._run_worker_parent(args, config)

    assert len(supervised) == 1
    receipt = json.loads(supervised[0].read_text(encoding="utf-8"))
    assert receipt["decision"] == "blocked_fail_closed_worker_supervision_required"
    assert receipt["child"]["process_id"] == process.pid
    assert receipt["child"]["worker_nonce"] == nonce
    assert receipt["orders_retried"] == 0
    assert receipt["credentials_redacted"] is True
    assert post_calls == []
    stderr = capsys.readouterr().err
    assert "WORKER_PARENT_BLOCKED_FAIL_CLOSED" in stderr
    assert str(supervised[0].resolve()) in stderr
    assert f"child_pid={process.pid}" in stderr
    assert not list(tmp_path.glob("btc_okx_demo_fault_drill/**/*.json"))


def test_blocked_child_supervisor_has_fixed_deadline_and_does_not_swallow_ctrl_c() -> None:
    class InterruptOnceProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.wait_calls = 0

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float) -> int:
            assert 0 < timeout <= 5.0
            self.wait_calls += 1
            raise KeyboardInterrupt

    process = InterruptOnceProcess()

    with pytest.raises(KeyboardInterrupt):
        fault_drill_cli._supervise_blocked_child(
            process,
            deadline_seconds=0.01,
        )

    assert process.wait_calls == 1


def test_unverified_child_supervision_deadline_returns_explicit_untransferred_state() -> None:
    class NeverExits:
        pid = 43210

        def poll(self) -> None:
            return None

        def wait(self, timeout: float) -> int:
            raise subprocess.TimeoutExpired("worker", timeout)

    result = fault_drill_cli._supervise_blocked_child(
        NeverExits(),
        deadline_seconds=0.001,
    )

    assert result == {
        "disposition": "supervision_deadline_exceeded",
        "exact_child_exited": False,
        "persistent_supervisor_handoff_confirmed": False,
    }


def test_ordinary_fault_drill_cli_second_writer_fails_before_runtime_mutation(
    tmp_path: Path,
) -> None:
    runtime_output = tmp_path / "runtime"
    spec = btc_strategy_registry.get("long_short_donchian_top5")
    args = SimpleNamespace(
        data_db_path=tmp_path / "missing.sqlite",
        runtime_output_dir=runtime_output,
        strategy_id=spec.strategy_id,
        candidate_id=spec.candidate_id,
        strategy_version=spec.strategy_version,
    )
    config = _config(
        tmp_path,
        _head(),
        "held_position_disconnect",
        execute=True,
    )
    writer = fault_drill_cli._runtime(args, config)
    writer.acquire_fault_drill_process_lock(nonce="ordinarycliwriter")
    contender = fault_drill_cli._runtime(args, config)
    credential_calls: list[str] = []
    client_factory_calls: list[str] = []
    contender._credential_loader = credential_calls.append
    contender._client_factory = lambda *_args: client_factory_calls.append(
        "private_or_order_transport_constructed"
    )

    with pytest.raises(
        RuntimeError,
        match="runtime_root_writer_lock_unavailable",
    ):
        fault_drill_cli._start_runtime(contender, args)

    assert contender.fault_drill_snapshot()["events"] == []
    assert not (runtime_output / "events.jsonl").exists()
    assert not (runtime_output / "state.json").exists()
    assert contender._fault_drill_lock_handle is None
    assert credential_calls == []
    assert client_factory_calls == []
    writer.release_fault_drill_process_lock()


def test_execute_demo_cli_defaults_match_registry_identity_without_endpoint_access(
    tmp_path: Path,
) -> None:
    head = _head()
    args = fault_drill_cli.build_parser().parse_args(
        [
            "--scenario",
            "held_position_disconnect",
            "--run-id",
            "default-identity",
            "--source-head",
            head,
            "--receipt-external-root",
            str(tmp_path.resolve()),
            "--environment",
            "OKX Demo",
            "--instrument-id",
            "BTC-USDT-SWAP",
            "--margin-mode",
            "isolated",
            "--leverage",
            "3",
            "--order-contracts",
            "0.01",
            "--max-notional-usdt",
            "10",
            "--confirm-dedicated-demo-account",
            "--execute-demo",
            "--data-db-path",
            str(tmp_path / "unused.sqlite"),
            "--runtime-output-dir",
            str(tmp_path / "runtime"),
        ]
    )
    captured: list[Mapping[str, Any]] = []
    runtime = SimpleNamespace(start=lambda payload: captured.append(dict(payload)))

    fault_drill_cli._start_runtime(runtime, args)

    spec = btc_strategy_registry.get(args.strategy_id, args.candidate_id)
    assert args.strategy_version == spec.strategy_version
    assert OkxDemoPaperStartRequest.from_mapping(captured[0]).validate() == []


def test_cli_stop_failure_writes_one_terminal_blocked_receipt_and_exits_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv = _native_cli_args(tmp_path)
    argv[argv.index("--strategy-id") + 1] = "long_short_donchian_top5"
    for flag in (
        "--okx-native-shared-manifest-git-spec",
        "--okx-native-shared-data-root",
        "--okx-native-expected-dataset-id",
    ):
        index = argv.index(flag)
        del argv[index : index + 2]

    class StopFailRuntime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__(
                result={
                    "orders_posted": 2,
                    "position_observed": True,
                    "protection_verified": True,
                    "pre_reconciliation_sha256": "a" * 64,
                    "post_reconciliation_sha256": "b" * 64,
                    "disconnect_observed": True,
                }
            )
            self._fault_drill_lock_handle: object | None = object()

        def start(self, _payload: Mapping[str, Any]) -> None:
            return None

        def stop(self, _payload: Mapping[str, Any]) -> None:
            raise RuntimeError("stop_failed")

        def release_fault_drill_process_lock(self) -> None:
            self._fault_drill_lock_handle = None

        def status(self) -> dict[str, Any]:
            status = _snapshot()
            status["runtime"].update(
                {"active": False, "worker_alive": False, "status": "frozen"}
            )
            status["risk_control"]["dead_man"] = {
                "armed": False,
                "heartbeat_thread_alive": False,
            }
            status["private_ws"]["listener_alive"] = False
            return status

    runtime = StopFailRuntime()
    monkeypatch.setattr(fault_drill_cli, "_runtime", lambda *_args: runtime)
    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *argv])

    assert fault_drill_cli.main() == 2

    receipts = list(tmp_path.glob("btc_okx_demo_fault_drill/**/*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["decision"] == "blocked_frozen_lifecycle_incomplete"
    assert receipt["lifecycle"]["writer_lock_released"] is True
    assert receipt["lifecycle"]["runtime_clean_stop"] is False
    assert "fault_drill_cli_stop_failed:RuntimeError" in receipt["blockers"]


def test_cli_startup_failure_writes_one_immutable_fail_closed_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    argv = _native_cli_args(tmp_path)
    argv[argv.index("--strategy-id") + 1] = "long_short_donchian_top5"
    for flag in (
        "--okx-native-shared-manifest-git-spec",
        "--okx-native-shared-data-root",
        "--okx-native-expected-dataset-id",
    ):
        index = argv.index(flag)
        del argv[index : index + 2]

    class StartupFailRuntime:
        _fault_drill_lock_handle = None

        def start(self, _payload: Mapping[str, Any]) -> None:
            raise RuntimeError("startup_after_resource_construction_failed")

        def freeze_fault_drill(self, _reason: str) -> None:
            return None

        def release_fault_drill_process_lock(self) -> None:
            return None

        def status(self) -> dict[str, Any]:
            status = _snapshot()
            status["runtime"].update(
                {
                    "active": False,
                    "worker_alive": False,
                    "status": "start_blocked_fail_closed",
                }
            )
            status["risk_control"]["dead_man"] = {
                "armed": False,
                "heartbeat_thread_alive": False,
            }
            status["private_ws"]["listener_alive"] = False
            return status

    runtime = StartupFailRuntime()
    monkeypatch.setattr(fault_drill_cli, "_runtime", lambda *_args: runtime)
    monkeypatch.setattr(fault_drill_cli.sys, "argv", ["fault-drill", *argv])

    assert fault_drill_cli.main() == 2

    receipts = list(tmp_path.glob("btc_okx_demo_fault_drill/**/*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["decision"] == "startup_failed_fail_closed"
    assert receipt["lifecycle"]["startup_failed"] is True
    assert receipt["lifecycle"]["cleanup_complete"] is True
    assert receipt["orders_posted"] == 0
