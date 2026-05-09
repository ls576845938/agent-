from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, SignalDirection, TimeInForce
from quant_us.core.types import AccountState, Bar, Order, OrderIntent, Position, Signal
from quant_us.live.alpaca_paper_adapter import AlpacaPaperBrokerAdapter
from quant_us.live.fake_alpaca_paper_adapter import FakeAlpacaPaperBrokerAdapter
from quant_us.live.modes import RuntimeMode
from quant_us.live.paper_adapter_contract import (
    audit_apca_paper_credentials,
    evaluate_paper_adapter_contract,
)
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig, PaperSessionMetrics
from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
from quant_us.live.runtime import LiveRuntime
from quant_us.live.runtime_config import LiveRuntimeConfig


UTC = timezone.utc


def _intent(
    side: OrderSide = OrderSide.BUY,
    quantity: float = 10.0,
    client_order_id: str = "runtime_worker_001",
) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        strategy_id="test_strategy",
        symbol="SPY",
        side=side,
        quantity=quantity,
        client_order_id=client_order_id,
    )


def _account(quantity: float = 0.0) -> AccountState:
    positions = {}
    if abs(quantity) > 1e-9:
        positions["SPY"] = Position(symbol="SPY", quantity=quantity, market_price=500.0)
    return AccountState(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        account_id="paper",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
        positions=positions,
    )


def _approving_oms() -> MagicMock:
    decision = MagicMock()
    decision.approved = True
    order = MagicMock()
    order.order_id = "paper_order_001"
    result = MagicMock()
    result.risk_decision = decision
    result.order = order
    oms = MagicMock()
    oms.handle_intent.return_value = result
    return oms


def _write_review(
    review_path: Path,
    *,
    status: str = "APPROVED_FOR_PAPER_ONLY",
    reviewer: str = "risk-reviewer",
) -> None:
    review_path.write_text(
        json.dumps(
            {
                "paper_review_id": "paper_review_test",
                "status": status,
                "reviewer": reviewer,
            }
        ),
        encoding="utf-8",
    )


def _startup_sync_artifact(ledger_root: Path) -> dict[str, object]:
    return json.loads(
        (ledger_root / "audit" / "paper_broker_adapter_startup_sync.json").read_text(encoding="utf-8")
    )


class RecordingSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> MagicMock:
        self.requests.append({"method": method, "url": url, "kwargs": kwargs})
        response = MagicMock()
        response.status_code = 200
        if url.endswith("/v2/account"):
            response.json.return_value = {
                "id": "paper_test_account",
                "cash": "100000",
                "equity": "100000",
                "buying_power": "100000",
            }
        elif url.endswith("/v2/positions"):
            response.json.return_value = []
        elif url.endswith("/v2/orders"):
            response.json.return_value = []
        elif url.endswith("/v2/account/activities"):
            response.json.return_value = []
        else:
            response.json.return_value = {}
        return response


class FakeAdapterPaperRuntime(PaperRuntime):
    @staticmethod
    def _alpaca_paper_adapter_enabled() -> bool:
        return True

    @staticmethod
    def _alpaca_paper_adapter_factory_present() -> bool:
        return True

    @staticmethod
    def _alpaca_paper_adapter_capabilities() -> dict[str, bool]:
        return FakeAlpacaPaperBrokerAdapter.contract_capabilities()

    def _create_alpaca_paper_broker(self) -> FakeAlpacaPaperBrokerAdapter:
        return FakeAlpacaPaperBrokerAdapter(initial_cash=self.config.capital)


class FailingSyncFakeAdapterPaperRuntime(FakeAdapterPaperRuntime):
    def __init__(self, *args, fail_on_call: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fail_on_call = fail_on_call

    def _create_alpaca_paper_broker(self) -> FakeAlpacaPaperBrokerAdapter:
        return FakeAlpacaPaperBrokerAdapter(
            initial_cash=self.config.capital,
            fail_on_call=self._fail_on_call,
        )


def test_alpaca_paper_runtime_blocks_without_apca_credentials(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit" / "paper_runtime_audit.jsonl"
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            audit_log_path=str(audit_path),
            data_vendor="alpaca",
            paper_broker="alpaca",
            paper_review_path=str(tmp_path / "missing_review.json"),
            reconcile_on_start=False,
        )
    )

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="apca_paper_credentials_missing"):
            runtime.bootstrap()

    entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert entries[-1]["event"] == "paper_runtime_entry_gate"
    assert entries[-1]["paper_broker"] == "alpaca"
    assert entries[-1]["broker_backend"] == "simulated"
    assert "apca_paper_credentials_missing" in entries[-1]["details"]["reasons"]
    assert entries[-1]["details"]["checks"]["paper_adapter_contract"]["fail_closed"] is True
    assert entries[-1]["details"]["checks"]["paper_credential_audit"]["endpoint_kind"] == "unset"


def test_alpaca_paper_runtime_blocks_without_apca_base_url(tmp_path: Path) -> None:
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(tmp_path / "missing_review.json"),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {"APCA_API_KEY_ID": "paper_key", "APCA_API_SECRET_KEY": "paper_secret"},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="apca_base_url_missing"):
            runtime.bootstrap()

    checks = runtime.audit_events[-1]["details"]["checks"]
    assert checks["paper_credential_audit"]["endpoint_kind"] == "unset"
    assert checks["paper_credential_audit"]["base_url_valid"] is False
    assert checks["paper_credential_audit"]["allowed_base_url"] == "https://paper-api.alpaca.markets"
    assert checks["paper_adapter_contract"]["base_url_valid"] is False


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_alpaca_paper_runtime_requires_approved_paper_review(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "paper_review_id": "prev_test",
                "status": "PENDING_HUMAN_REVIEW",
                "reviewer": "",
            }
        ),
        encoding="utf-8",
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            data_vendor="alpaca",
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {"APCA_API_KEY_ID": "paper_key", "APCA_API_SECRET_KEY": "paper_secret"},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="paper_review_not_approved"):
            runtime.bootstrap()


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_data_vendor_alpaca_with_simulated_broker_audits_simulated_backend(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            data_vendor="alpaca",
            paper_broker="simulated",
            reconcile_on_start=False,
        )
    )

    with patch.dict("os.environ", {}, clear=True):
        runtime.bootstrap()

    assert runtime._bootstrapped is True
    assert runtime.audit_events[0]["event"] == "paper_runtime_entry_gate"
    assert runtime.audit_events[0]["broker_backend"] == "simulated"
    assert runtime.audit_events[0]["details"]["checks"]["broker_backend"] == "simulated"
    assert runtime.audit_events[0]["details"]["checks"]["alpaca_paper_requested"] is False
    assert any(event["event"] == "paper_oms_idempotency_recovered" for event in runtime.audit_events)
    runtime.shutdown()


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_alpaca_paper_broker_blocks_when_adapter_is_not_wired(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "paper_review_id": "prev_test",
                "status": "APPROVED_FOR_PAPER_ONLY",
                "reviewer": "risk-reviewer",
            }
        ),
        encoding="utf-8",
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {"APCA_API_KEY_ID": "paper_key", "APCA_API_SECRET_KEY": "paper_secret"},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="alpaca_paper_broker_adapter_not_configured"):
            runtime.bootstrap()

    assert runtime.audit_events[-1]["broker_backend"] == "simulated"
    assert runtime.audit_events[-1]["details"]["checks"]["alpaca_paper_adapter_enabled"] is False
    assert runtime.audit_events[-1]["details"]["checks"]["paper_adapter_contract"]["effective_backend"] == "simulated"


def test_alpaca_paper_adapter_contract_requires_factory_even_when_env_requests() -> None:
    contract = evaluate_paper_adapter_contract(
        "alpaca",
        adapter_enabled=True,
        adapter_factory_present=False,
        env_requested=True,
        endpoint_kind="paper",
        base_url_valid=True,
    )

    assert contract.fail_closed is True
    assert contract.submit_capable is False
    assert contract.effective_backend == "simulated"
    assert contract.reason == "alpaca_paper_broker_adapter_not_configured"
    assert contract.env_requested is True
    assert contract.endpoint_kind == "paper"
    assert contract.base_url_valid is True
    assert contract.allowed_base_urls == ["https://paper-api.alpaca.markets"]


def test_alpaca_paper_adapter_contract_requires_full_sync_surface() -> None:
    capabilities = FakeAlpacaPaperBrokerAdapter.contract_capabilities()
    capabilities["sync_positions"] = False

    contract = evaluate_paper_adapter_contract(
        "alpaca",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=True,
        endpoint_kind="paper_lookalike",
        base_url_valid=False,
    )

    assert contract.fail_closed is True
    assert contract.submit_capable is False
    assert "sync_positions" in contract.reason
    assert contract.capabilities["sync_positions"] is False
    assert contract.endpoint_kind == "paper_lookalike"
    assert contract.base_url_valid is False


def test_alpaca_paper_adapter_contract_requires_paper_endpoint_credentials_and_evidence() -> None:
    capabilities = FakeAlpacaPaperBrokerAdapter.contract_capabilities()
    live_endpoint_contract = evaluate_paper_adapter_contract(
        "alpaca",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=True,
        endpoint_kind="live",
        base_url_valid=False,
        credentials_present=True,
        approved_evidence=True,
    )
    missing_credential_contract = evaluate_paper_adapter_contract(
        "alpaca",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=True,
        endpoint_kind="paper",
        base_url_valid=True,
        credentials_present=False,
        credential_reason="apca_paper_credentials_missing",
        approved_evidence=True,
    )
    missing_evidence_contract = evaluate_paper_adapter_contract(
        "alpaca",
        adapter_enabled=True,
        adapter_factory_present=True,
        adapter_capabilities=capabilities,
        env_requested=True,
        endpoint_kind="paper",
        base_url_valid=True,
        credentials_present=True,
        approved_evidence=False,
        evidence_reason="paper_review_not_approved: PENDING_HUMAN_REVIEW",
    )

    assert live_endpoint_contract.fail_closed is True
    assert live_endpoint_contract.reason == "apca_base_url_not_allowed"
    assert live_endpoint_contract.effective_backend == "simulated"
    assert live_endpoint_contract.adapter_ready is False
    assert missing_credential_contract.reason == "apca_paper_credentials_missing"
    assert missing_credential_contract.credentials_present is False
    assert missing_evidence_contract.reason == "paper_review_not_approved: PENDING_HUMAN_REVIEW"
    assert missing_evidence_contract.approved_evidence is False


def test_apca_paper_credential_audit_classifies_only_exact_paper_endpoint() -> None:
    paper = audit_apca_paper_credentials(
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets/",
        }
    )
    live = audit_apca_paper_credentials(
        {
            "APCA_API_KEY_ID": "live_key",
            "APCA_API_SECRET_KEY": "live_secret",
            "APCA_API_BASE_URL": "https://api.alpaca.markets",
        }
    )
    lookalike = audit_apca_paper_credentials(
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets.evil.example",
        }
    )

    assert paper["endpoint_kind"] == "paper"
    assert paper["base_url_valid"] is True
    assert paper["normalized_base_url"] == "https://paper-api.alpaca.markets"
    assert live["endpoint_kind"] == "live"
    assert live["base_url_valid"] is False
    assert lookalike["endpoint_kind"] == "paper_lookalike"
    assert lookalike["base_url_valid"] is False


def test_real_alpaca_paper_adapter_blocks_missing_credentials_and_live_endpoint() -> None:
    with pytest.raises(RuntimeError, match="apca_paper_credentials_missing"):
        AlpacaPaperBrokerAdapter.from_env(
            {
                "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
                "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
            },
            session=RecordingSession(),
        )

    with pytest.raises(RuntimeError, match="apca_base_url_not_allowed"):
        AlpacaPaperBrokerAdapter.from_env(
            {
                "APCA_API_KEY_ID": "key",
                "APCA_API_SECRET_KEY": "secret",
                "APCA_API_BASE_URL": "https://api.alpaca.markets",
                "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
            },
            session=RecordingSession(),
        )


def test_real_alpaca_paper_adapter_default_submit_is_fail_closed_without_network() -> None:
    session = RecordingSession()
    adapter = AlpacaPaperBrokerAdapter.from_env(
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        session=session,
    )
    order = Order(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        strategy_id="test",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id="paper_submit_blocked",
    )

    with pytest.raises(RuntimeError, match="alpaca_paper_network_submit_disabled_fail_closed"):
        adapter.submit_order(order)

    assert session.requests == []
    assert adapter.readiness_report()["network_submit_enabled"] is False


def test_alpaca_paper_runtime_contract_stays_fail_closed_when_env_requests(
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "paper_review_id": "prev_test",
                "status": "APPROVED_FOR_PAPER_ONLY",
                "reviewer": "risk-reviewer",
            }
        ),
        encoding="utf-8",
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="alpaca_paper_broker_adapter_not_configured"):
            runtime.bootstrap()

    contract = runtime.audit_events[-1]["details"]["checks"]["paper_adapter_contract"]
    assert contract["env_requested"] is True
    assert contract["adapter_factory_present"] is False
    assert contract["submit_capable"] is False
    assert contract["fail_closed"] is True


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_fake_alpaca_paper_adapter_contract_surface_works_without_network(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        runtime.bootstrap()

    assert isinstance(runtime.broker, FakeAlpacaPaperBrokerAdapter)
    assert runtime._paper_broker_backend() == "alpaca_paper"
    assert any(event["event"] == "paper_broker_adapter_activated" for event in runtime.audit_events)

    bar = Bar(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        symbol="SPY",
        open=500.0,
        high=501.0,
        low=499.0,
        close=500.0,
        volume=10_000.0,
        source="test",
    )
    runtime.broker.update_market(bar)

    order = Order(
        timestamp_utc=bar.timestamp_utc,
        strategy_id="test",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=2.0,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id="fake_adapter_submit_001",
    )
    submitted = runtime.broker.submit_order(order)
    polled = runtime.broker.poll_orders()
    fills = runtime.broker.sync_fills(submitted.order_id)
    account = runtime.broker.sync_account()
    positions = runtime.broker.sync_positions()
    submitted_status = submitted.status
    canceled = runtime.broker.cancel_order(submitted.order_id)

    assert submitted_status == OrderStatus.FILLED
    assert len(polled) == 1
    assert len(fills) == 1
    assert account.account_id == "alpaca_paper_fake"
    assert positions["SPY"].quantity == pytest.approx(2.0)
    assert canceled.status == OrderStatus.CANCELLED


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_fake_adapter_does_not_bypass_paper_review_gate(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path, status="PENDING_HUMAN_REVIEW", reviewer="")
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="paper_review_not_approved"):
            runtime.bootstrap()

    checks = runtime.audit_events[-1]["details"]["checks"]
    assert checks["paper_adapter_contract"]["adapter_factory_present"] is True
    assert checks["paper_review_or_promotion_evidence"] is False


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_fake_adapter_does_not_bypass_paper_credential_gate(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="apca_paper_credentials_missing"):
            runtime.bootstrap()

    checks = runtime.audit_events[-1]["details"]["checks"]
    assert checks["paper_adapter_contract"]["adapter_factory_present"] is True
    assert checks["paper_credentials_present"] is False


def test_alpaca_paper_runtime_audits_non_paper_base_url(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit" / "paper_runtime_audit.jsonl"
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            audit_log_path=str(audit_path),
            paper_broker="alpaca",
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://api.alpaca.markets",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="apca_base_url_not_allowed"):
            runtime.bootstrap()

    entry = runtime.audit_events[-1]
    assert entry["details"]["checks"]["paper_credential_audit"]["endpoint_kind"] == "live"
    assert entry["details"]["checks"]["paper_credential_audit"]["base_url_valid"] is False
    assert "apca_base_url_not_allowed" in entry["details"]["reasons"]


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_fake_adapter_does_not_bypass_paper_endpoint_gate(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="apca_base_url_not_allowed"):
            runtime.bootstrap()

    checks = runtime.audit_events[-1]["details"]["checks"]
    assert checks["paper_adapter_contract"]["adapter_factory_present"] is True
    assert checks["paper_credential_audit"]["endpoint_kind"] == "live"
    assert checks["paper_credential_audit"]["base_url_valid"] is False


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_fake_adapter_does_not_bypass_pseudo_paper_endpoint_gate(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets.evil.example",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="apca_base_url_not_allowed"):
            runtime.bootstrap()

    checks = runtime.audit_events[-1]["details"]["checks"]
    assert checks["paper_adapter_contract"]["adapter_factory_present"] is True
    assert checks["paper_credential_audit"]["endpoint_kind"] == "paper_lookalike"
    assert checks["paper_credential_audit"]["base_url_valid"] is False


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_fake_adapter_accepts_exact_paper_endpoint_with_trailing_slash(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets/",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        runtime.bootstrap()

    checks = runtime.audit_events[0]["details"]["checks"]
    assert checks["paper_credential_audit"]["base_url_valid"] is True
    assert checks["paper_credential_audit"]["normalized_base_url"] == "https://paper-api.alpaca.markets"
    assert checks["paper_adapter_contract"]["endpoint_kind"] == "paper"
    assert runtime.broker.sync_call_log == [
        "poll_orders",
        "sync_fills",
        "sync_account",
        "sync_positions",
    ]
    assert runtime.broker.submit_call_count == 0
    assert runtime.audit_events[-1]["event"] == "paper_broker_adapter_startup_sync_complete"
    artifact = _startup_sync_artifact(Path(runtime.config.ledger_root))
    assert artifact["status"] == "ok"
    assert artifact["backend"] == "alpaca_paper"
    assert artifact["contract_version"] == "paper_adapter_contract_v4"
    assert artifact["sync"]["poll_orders"]["call_count"] == 1
    assert artifact["sync"]["poll_orders"]["order_count"] == 0
    assert artifact["sync"]["sync_fills"]["call_count"] == 1
    assert artifact["sync"]["sync_fills"]["fill_count"] == 0
    assert artifact["sync"]["sync_account"]["call_count"] == 1
    assert artifact["sync"]["sync_account"]["account_id"] == "alpaca_paper_fake"
    assert artifact["sync"]["sync_positions"]["call_count"] == 1
    assert artifact["sync"]["sync_positions"]["symbols"] == []
    assert runtime.audit_events[-1]["details"]["artifact_path"].endswith(
        "audit/paper_broker_adapter_startup_sync.json"
    )


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_fake_adapter_startup_sync_failure_blocks_bootstrap(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FailingSyncFakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
        ),
        fail_on_call="sync_positions",
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="alpaca_paper_startup_sync_failed"):
            runtime.bootstrap()

    assert runtime.oms.reduce_only is True
    assert runtime.kill_switch.triggered is True
    assert runtime.broker.sync_call_log == [
        "poll_orders",
        "sync_fills",
        "sync_account",
        "sync_positions",
    ]
    assert runtime.broker.submit_call_count == 0
    assert runtime.audit_events[-1]["event"] == "paper_broker_adapter_startup_sync_failed"
    artifact = _startup_sync_artifact(Path(runtime.config.ledger_root))
    assert artifact["status"] == "failed"
    assert artifact["backend"] == "alpaca_paper"
    assert artifact["contract_version"] == "paper_adapter_contract_v4"
    assert artifact["error"] == "sync_positions_failed"
    assert artifact["reduce_only"] is True
    assert artifact["halt_reconciliation"] is True
    assert artifact["sync"]["poll_orders"]["call_count"] == 1
    assert artifact["sync"]["sync_fills"]["call_count"] == 1
    assert artifact["sync"]["sync_account"]["call_count"] == 1
    assert artifact["sync"]["sync_account"]["account_id"] == "alpaca_paper_fake"
    assert artifact["sync"]["sync_positions"]["call_count"] == 1
    assert runtime.audit_events[-1]["details"]["artifact_path"].endswith(
        "audit/paper_broker_adapter_startup_sync.json"
    )


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_runtime_kill_switch_blocks_adapter_submit(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            strategy_id="kill_switch_fixture",
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
            submit_orders=True,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        runtime.bootstrap()

    submit_spy = MagicMock(wraps=runtime.broker.submit_order)
    runtime.broker.submit_order = submit_spy  # type: ignore[method-assign]
    runtime.kill_switch.trip("manual_test")
    runtime._handle_signal(
        Signal(
            timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
            strategy_id="kill_switch_fixture",
            symbol="SPY",
            direction=SignalDirection.LONG,
            strength=1.0,
            horizon="1d",
        ),
        _account(),
        {"SPY": 500.0},
        Bar(
            timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
            symbol="SPY",
            open=500.0,
            high=501.0,
            low=499.0,
            close=500.0,
            volume=10_000.0,
            source="test",
        ),
        PaperSessionMetrics(),
    )

    submit_spy.assert_not_called()
    assert runtime.audit_events[-1]["event"] == "paper_order_rejected_kill_switch"


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_runtime_reduce_only_blocks_adapter_submit(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    review_path = tmp_path / "review.json"
    _write_review(review_path)
    runtime = FakeAdapterPaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            strategy_id="reduce_only_fixture",
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            reconcile_on_start=False,
            submit_orders=True,
            reduce_only=True,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        runtime.bootstrap()

    submit_spy = MagicMock(wraps=runtime.broker.submit_order)
    runtime.broker.submit_order = submit_spy  # type: ignore[method-assign]
    runtime._handle_signal(
        Signal(
            timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
            strategy_id="reduce_only_fixture",
            symbol="SPY",
            direction=SignalDirection.LONG,
            strength=1.0,
            horizon="1d",
        ),
        _account(),
        {"SPY": 500.0},
        Bar(
            timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
            symbol="SPY",
            open=500.0,
            high=501.0,
            low=499.0,
            close=500.0,
            volume=10_000.0,
            source="test",
        ),
        PaperSessionMetrics(),
    )

    submit_spy.assert_not_called()
    assert runtime.audit_events[-1]["event"] == "paper_order_rejected_reduce_only"


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_runtime_bootstrap_loads_idempotency_before_orders(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger"
    ledger_root.mkdir()
    (ledger_root / ".idempotency.json").write_text(
        json.dumps(["existing-client-id"]),
        encoding="utf-8",
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(ledger_root),
            reconcile_on_start=False,
        )
    )

    runtime.bootstrap()
    duplicate = runtime.oms.handle_intent(
        _intent(client_order_id="existing-client-id"),
        _account(),
        market_price=500.0,
    )

    assert duplicate.risk_decision.approved is False
    assert duplicate.risk_decision.reason == "duplicate_client_order_id"
    assert runtime.audit_events[-1]["event"] == "paper_oms_idempotency_recovered"
    assert runtime.audit_events[-1]["details"]["idempotency_loaded_count"] == 1
    runtime.shutdown()


@patch("quant_us.live.paper_runtime.MarketDataLoop")
def test_paper_runtime_malformed_order_ledger_fails_closed(
    _mock_loop: MagicMock,
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger"
    ledger_root.mkdir()
    (ledger_root / "orders.jsonl").write_text('{"order_id": "missing-client"}\n', encoding="utf-8")
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            ledger_root=str(ledger_root),
            reconcile_on_start=False,
        )
    )

    with pytest.raises(RuntimeError, match="paper_oms_idempotency_recovery_failed"):
        runtime.bootstrap()

    assert runtime.oms.reduce_only is True
    assert runtime._halt_reconciliation is True
    assert runtime.audit_events[-1]["event"] == "paper_oms_idempotency_recovery_failed"
    assert "missing client_order_id" in runtime.audit_events[-1]["details"]["error"]


def test_runtime_reduce_only_blocks_new_and_reversing_exposure() -> None:
    runtime = LiveRuntime(LiveRuntimeConfig(mode=RuntimeMode.PAPER, submit_orders=True))
    runtime.bootstrap()
    runtime.oms = _approving_oms()

    buy_result = runtime.submit_orders(
        [_intent(OrderSide.BUY, 1.0, "reduce_buy")],
        account=_account(quantity=10.0),
        market_price=500.0,
        reduce_only=True,
    )
    reverse_result = runtime.submit_orders(
        [_intent(OrderSide.SELL, 20.0, "reduce_reverse")],
        account=_account(quantity=10.0),
        market_price=500.0,
        reduce_only=True,
    )
    reduce_result = runtime.submit_orders(
        [_intent(OrderSide.SELL, 5.0, "reduce_ok")],
        account=_account(quantity=10.0),
        market_price=500.0,
        reduce_only=True,
    )

    assert buy_result["submitted"] == []
    assert "reduce_only_would_increase_or_reverse_long" in buy_result["rejected"][0]["reason"]
    assert reverse_result["submitted"] == []
    assert "reduce_only_would_increase_or_reverse_long" in reverse_result["rejected"][0]["reason"]
    assert len(reduce_result["submitted"]) == 1
    assert runtime.oms.handle_intent.call_count == 1


def test_runtime_reduce_only_blocks_batch_aggregate_reversal() -> None:
    runtime = LiveRuntime(LiveRuntimeConfig(mode=RuntimeMode.PAPER, submit_orders=True))
    runtime.bootstrap()
    runtime.oms = _approving_oms()

    result = runtime.submit_orders(
        [
            _intent(OrderSide.SELL, 6.0, "reduce_batch_first"),
            _intent(OrderSide.SELL, 6.0, "reduce_batch_second"),
        ],
        account=_account(quantity=10.0),
        market_price=500.0,
        reduce_only=True,
    )

    assert len(result["submitted"]) == 1
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["intent_id"] == "reduce_batch_second"
    assert "reduce_only_would_increase_or_reverse_long" in result["rejected"][0]["reason"]
    assert runtime.oms.handle_intent.call_count == 1


def test_runtime_reduce_only_blocks_short_increase_and_short_reverse() -> None:
    runtime = LiveRuntime(LiveRuntimeConfig(mode=RuntimeMode.PAPER, submit_orders=True))
    runtime.bootstrap()
    runtime.oms = _approving_oms()

    increase_result = runtime.submit_orders(
        [_intent(OrderSide.SELL, 1.0, "reduce_short_increase")],
        account=_account(quantity=-10.0),
        market_price=500.0,
        reduce_only=True,
    )
    reverse_result = runtime.submit_orders(
        [_intent(OrderSide.BUY, 20.0, "reduce_short_reverse")],
        account=_account(quantity=-10.0),
        market_price=500.0,
        reduce_only=True,
    )
    reduce_result = runtime.submit_orders(
        [_intent(OrderSide.BUY, 5.0, "reduce_short_ok")],
        account=_account(quantity=-10.0),
        market_price=500.0,
        reduce_only=True,
    )

    assert increase_result["submitted"] == []
    assert "reduce_only_would_increase_or_reverse_short" in increase_result["rejected"][0]["reason"]
    assert reverse_result["submitted"] == []
    assert "reduce_only_would_increase_or_reverse_short" in reverse_result["rejected"][0]["reason"]
    assert len(reduce_result["submitted"]) == 1
    assert runtime.oms.handle_intent.call_count == 1


def test_paper_runtime_reduce_only_blocks_second_same_bar_exit_signal() -> None:
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            strategy_id="reduce_only_fixture",
            reduce_only=True,
            submit_orders=True,
        )
    )
    approved = MagicMock()
    approved.approved = True
    result = MagicMock()
    result.risk_decision = approved
    result.order = None
    result.fills = []
    runtime.oms = MagicMock()
    runtime.oms.handle_intent.return_value = result
    runtime.ledger = MagicMock()

    account = _account(quantity=10.0)
    prices = {"SPY": 500.0}
    bar = Bar(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        symbol="SPY",
        open=500.0,
        high=500.0,
        low=500.0,
        close=500.0,
        volume=100_000.0,
    )
    signal = Signal(
        timestamp_utc=bar.timestamp_utc,
        strategy_id="reduce_only_fixture",
        symbol="SPY",
        direction=SignalDirection.FLAT,
        strength=1.0,
        horizon="1b",
        reason="exit_duplicate",
    )
    metrics = PaperSessionMetrics()
    projection = runtime._reduce_only_projected_positions(account)

    runtime._handle_signal(signal, account, prices, bar, metrics, reduce_only_projection=projection)
    runtime._handle_signal(signal, account, prices, bar, metrics, reduce_only_projection=projection)

    assert metrics.intents_created == 2
    assert metrics.intents_submitted == 1
    assert metrics.intents_rejected == 1
    assert runtime.oms.handle_intent.call_count == 1
    assert runtime.audit_events[-1]["event"] == "paper_order_rejected_reduce_only"
    assert runtime.audit_events[-1]["details"]["reason"] == "reduce_only_no_existing_position"


def test_readonly_live_broker_writes_forbidden_call_audit(tmp_path: Path) -> None:
    inner = MagicMock()
    inner.broker_name = "alpaca_live"
    proxy = ReadOnlyLiveBrokerProxy(inner, audit_log_path=str(tmp_path / "readonly_audit.jsonl"))
    order = Order(
        timestamp_utc=datetime(2026, 5, 9, 14, 30, tzinfo=UTC),
        strategy_id="test",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id="readonly_forbidden",
    )

    with pytest.raises(RuntimeError, match="FORBIDDEN"):
        proxy.submit_order(order)

    entries = [json.loads(line) for line in (tmp_path / "readonly_audit.jsonl").read_text().splitlines()]
    assert entries[-1]["event"] == "readonly_live_broker_forbidden_call"
    assert entries[-1]["method"] == "submit_order"
    assert entries[-1]["real_submit"] is False
    assert entries[-1]["readonly"] is True
    assert entries[-1]["credential_audit"]["readonly_expected"] is True
