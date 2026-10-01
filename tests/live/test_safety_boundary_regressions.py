from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_us.core.enums import OrderSide
from quant_us.core.types import AccountState, OrderIntent
from quant_us.execution.oms import OrderManagementSystem
from quant_us.execution.paper_broker import PaperBroker
from quant_us.live.modes import RuntimeMode
from quant_us.live.runtime import LiveRuntime
from quant_us.live.runtime_config import LiveRuntimeConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine


UTC = timezone.utc


class CountingPaperBroker(PaperBroker):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.submit_calls = 0

    def submit_order(self, order):  # type: ignore[no-untyped-def]
        self.submit_calls += 1
        return super().submit_order(order)


def _intent(client_order_id: str = "safety_boundary_001") -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
        strategy_id="boundary_test",
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1.0,
        client_order_id=client_order_id,
    )


def _account() -> AccountState:
    return AccountState(
        timestamp_utc=datetime(2026, 5, 11, 14, 30, tzinfo=UTC),
        account_id="paper",
        cash=100_000.0,
        equity=100_000.0,
        buying_power=100_000.0,
    )


def _oms(broker: PaperBroker, idempotency_path: Path) -> OrderManagementSystem:
    return OrderManagementSystem(
        broker=broker,
        risk_engine=PreTradeRiskEngine(
            PreTradeRiskConfig(skip_session_check=True),
        ),
        idempotency_path=idempotency_path,
    )


def test_strategy_modules_do_not_import_or_call_broker_execution_surfaces() -> None:
    banned_import_prefixes = (
        "quant_us.execution",
        "quant_us.live",
        "alpaca",
        "ib_insync",
        "requests",
    )
    banned_names = {
        "AlpacaBroker",
        "AlpacaPaperBrokerAdapter",
        "BrokerBase",
        "OrderManagementSystem",
        "PaperBroker",
        "ReadOnlyLiveBrokerProxy",
    }
    banned_method_calls = {
        "cancel_order",
        "close_all_positions",
        "close_position",
        "replace_order",
        "submit_order",
    }

    violations: list[str] = []
    for path in sorted(Path("quant_us/strategies").glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(banned_import_prefixes):
                        violations.append(f"{path}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(banned_import_prefixes):
                    violations.append(f"{path}: imports from {module}")
                for alias in node.names:
                    if alias.name in banned_names:
                        violations.append(f"{path}: imports {alias.name}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in banned_names:
                    violations.append(f"{path}: constructs {func.id}")
                elif isinstance(func, ast.Attribute) and func.attr in banned_method_calls:
                    violations.append(f"{path}: calls .{func.attr}()")

    assert violations == []


def test_shadow_live_oms_is_never_wired_to_real_broker() -> None:
    path = Path("quant_us/live/shadow_live.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    paper_broker_wiring_seen = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "OrderManagementSystem"):
            continue
        for keyword in node.keywords:
            if keyword.arg != "broker":
                continue
            value = keyword.value
            if isinstance(value, ast.Attribute) and value.attr == "paper_broker":
                paper_broker_wiring_seen = True
            elif isinstance(value, ast.Attribute) and value.attr == "real_broker":
                violations.append(f"{path}: shadow_live OMS broker wired to real_broker")

    assert paper_broker_wiring_seen is True
    assert violations == []


def test_paper_runtime_reconciliation_break_blocks_before_oms(tmp_path: Path) -> None:
    broker = CountingPaperBroker()
    runtime = LiveRuntime(
        LiveRuntimeConfig(
            mode=RuntimeMode.PAPER,
            submit_orders=True,
            ledger_root=str(tmp_path / "ledger"),
        )
    )
    runtime.bootstrap()
    runtime.oms = _oms(broker, tmp_path / "ledger" / ".idempotency.json")

    result = runtime.submit_orders(
        [_intent()],
        account=_account(),
        market_price=500.0,
        reconciliation_clean=False,
    )

    assert result["submitted"] == []
    assert result["rejected"][0]["reason"] == "reconciliation_not_clean"
    assert broker.submit_calls == 0
    assert not (tmp_path / "ledger" / ".idempotency.json").exists()


def test_paper_runtime_kill_switch_blocks_before_oms(tmp_path: Path) -> None:
    broker = CountingPaperBroker()
    runtime = LiveRuntime(
        LiveRuntimeConfig(
            mode=RuntimeMode.PAPER,
            submit_orders=True,
            ledger_root=str(tmp_path / "ledger"),
        )
    )
    runtime.bootstrap()
    runtime.oms = _oms(broker, tmp_path / "ledger" / ".idempotency.json")

    result = runtime.submit_orders(
        [_intent()],
        account=_account(),
        market_price=500.0,
        kill_switch_triggered=True,
    )

    assert result["submitted"] == []
    assert result["rejected"][0]["reason"] == "kill_switch_active"
    assert broker.submit_calls == 0
    assert not (tmp_path / "ledger" / ".idempotency.json").exists()


def test_live_runtime_paper_mode_requires_explicit_submit_orders_before_oms(
    tmp_path: Path,
) -> None:
    broker = CountingPaperBroker()
    runtime = LiveRuntime(
        LiveRuntimeConfig(
            mode=RuntimeMode.PAPER,
            submit_orders=False,
            ledger_root=str(tmp_path / "ledger"),
        )
    )
    runtime.bootstrap()
    runtime.oms = _oms(broker, tmp_path / "ledger" / ".idempotency.json")

    result = runtime.submit_orders(
        [_intent("paper_submit_disabled_guard")],
        account=_account(),
        market_price=500.0,
    )

    assert result["submitted"] == []
    assert result["rejected"][0]["reason"] == "paper_order_submission_disabled"
    assert result["audit_events"][0]["event"] == "paper_order_rejected_submission_disabled"
    assert broker.submit_calls == 0
    assert broker.get_orders() == []
    assert not (tmp_path / "ledger" / ".idempotency.json").exists()


def test_runtime_restart_does_not_duplicate_previously_submitted_order(
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledger"
    idempotency_path = ledger_root / ".idempotency.json"
    broker = CountingPaperBroker()

    first_runtime = LiveRuntime(
        LiveRuntimeConfig(
            mode=RuntimeMode.PAPER,
            submit_orders=True,
            ledger_root=str(ledger_root),
        )
    )
    first_runtime.bootstrap()
    first_runtime.oms = _oms(broker, idempotency_path)
    first_result = first_runtime.submit_orders(
        [_intent("restart_duplicate_guard")],
        account=_account(),
        market_price=500.0,
    )

    restarted_oms = _oms(broker, idempotency_path)
    assert restarted_oms.load_idempotency() == 1
    second_runtime = LiveRuntime(
        LiveRuntimeConfig(
            mode=RuntimeMode.PAPER,
            submit_orders=True,
            ledger_root=str(ledger_root),
        )
    )
    second_runtime.bootstrap()
    second_runtime.oms = restarted_oms
    second_result = second_runtime.submit_orders(
        [_intent("restart_duplicate_guard")],
        account=_account(),
        market_price=500.0,
    )

    assert len(first_result["submitted"]) == 1
    assert second_result["submitted"] == []
    assert second_result["rejected"][0]["reason"] == "duplicate_client_order_id"
    assert broker.submit_calls == 1
    assert len(broker.get_orders()) == 1
    assert json.loads(idempotency_path.read_text(encoding="utf-8")) == [
        "restart_duplicate_guard"
    ]
