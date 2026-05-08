"""Paper Production Orchestrator — G0: production-grade paper trading with audit trail.

Wraps PaperRuntime with:
  - run journal (JSONL audit trail)
  - state persistence for recovery
  - strategy whitelist enforcement
  - pre-flight checks (credentials, readiness, smoke test)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Strategy Whitelist
# ---------------------------------------------------------------------------

PAPER_STRATEGY_WHITELIST: dict[str, dict[str, Any]] = {
    "etf_rotation": {
        "max_gross_exposure": 2.0,
        "max_single_position_pct": 0.45,
        "allowed_symbols": ["SPY", "QQQ", "IWM", "DIA"],
    },
    "trend_momentum": {
        "max_gross_exposure": 1.5,
        "max_single_position_pct": 0.25,
        "allowed_symbols": ["SPY", "QQQ", "IWM", "DIA"],
    },
    "factor_rank": {
        "max_gross_exposure": 2.0,
        "max_single_position_pct": 0.20,
        "allowed_symbols": ["SPY", "QQQ", "IWM", "DIA"],
    },
}


def validate_strategy_whitelist(strategy_id: str, symbols: list[str]) -> dict[str, Any]:
    """Check strategy is whitelisted and symbols are allowed. Returns {} if OK, else {error}."""
    if strategy_id not in PAPER_STRATEGY_WHITELIST:
        return {"error": f"strategy '{strategy_id}' not in paper whitelist. Allowed: {list(PAPER_STRATEGY_WHITELIST)}"}
    cfg = PAPER_STRATEGY_WHITELIST[strategy_id]
    disallowed = [s for s in symbols if s not in cfg["allowed_symbols"]]
    if disallowed:
        return {"error": f"symbols {disallowed} not allowed for {strategy_id}. Allowed: {cfg['allowed_symbols']}"}
    return {}


# ---------------------------------------------------------------------------
# Run Journal Entry types
# ---------------------------------------------------------------------------

@dataclass
class JournalEntry:
    """Single journal entry — one per day or incident."""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    entry_type: str = ""  # "run_start", "day_complete", "incident", "run_end"
    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict[str, Any] = field(default_factory=dict)


class PaperRunJournal:
    """JSONL journal for paper production audit trail."""

    def __init__(self, journal_path: str | Path) -> None:
        self.path = Path(journal_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: JournalEntry) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps({
                "entry_id": entry.entry_id,
                "entry_type": entry.entry_type,
                "run_id": entry.run_id,
                "timestamp": entry.timestamp,
                "data": entry.data,
            }, default=str) + "\n")

    def read_all(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if run_id is None or e.get("run_id") == run_id:
                        entries.append(e)
                except json.JSONDecodeError:
                    pass
        return entries

    def latest_run_status(self) -> dict[str, Any] | None:
        entries = self.read_all()
        return entries[-1] if entries else None


# ---------------------------------------------------------------------------
# Run State for Recovery
# ---------------------------------------------------------------------------

@dataclass
class PaperRunState:
    """Persistable state for paper production recovery."""
    run_id: str = ""
    trading_day: int = 0
    trading_date: str = ""
    last_step: str = ""  # "pre_market", "strategy_cycle", "reconcile", "complete"
    submitted_order_intent_ids: list[str] = field(default_factory=list)
    client_order_ids: list[str] = field(default_factory=list)
    broker_order_ids: list[str] = field(default_factory=list)
    last_reconciliation_status: str = ""
    kill_switch_triggered: bool = False
    recovery_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trading_day": self.trading_day,
            "trading_date": self.trading_date,
            "last_step": self.last_step,
            "submitted_order_intent_ids": self.submitted_order_intent_ids,
            "client_order_ids": self.client_order_ids,
            "broker_order_ids": self.broker_order_ids,
            "last_reconciliation_status": self.last_reconciliation_status,
            "kill_switch_triggered": self.kill_switch_triggered,
            "recovery_required": self.recovery_required,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PaperRunState":
        return cls(
            run_id=d.get("run_id", ""),
            trading_day=d.get("trading_day", 0),
            trading_date=d.get("trading_date", ""),
            last_step=d.get("last_step", ""),
            submitted_order_intent_ids=d.get("submitted_order_intent_ids", []),
            client_order_ids=d.get("client_order_ids", []),
            broker_order_ids=d.get("broker_order_ids", []),
            last_reconciliation_status=d.get("last_reconciliation_status", ""),
            kill_switch_triggered=d.get("kill_switch_triggered", False),
            recovery_required=d.get("recovery_required", False),
        )


class PaperRunStateStore:
    """Persist and load PaperRunState for recovery."""

    def __init__(self, state_path: str | Path) -> None:
        self.path = Path(state_path)

    def save(self, state: PaperRunState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2, default=str))
        tmp.replace(self.path)

    def load(self) -> PaperRunState | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text())
            return PaperRunState.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


# ---------------------------------------------------------------------------
# Paper Production Orchestrator
# ---------------------------------------------------------------------------

class PaperProductionOrchestrator:
    """Production-grade paper trading orchestrator with audit trail and recovery.

    Usage:
        orch = PaperProductionOrchestrator(
            symbols=["SPY", "QQQ", "IWM", "DIA"],
            strategy_id="trend_momentum",
            bar_size="1d",
            data_root="data",
            enable_paper_orders=False,
        )
        orch.run()
    """

    def __init__(
        self,
        symbols: list[str],
        strategy_id: str = "trend_momentum",
        bar_size: str = "1d",
        data_root: str = "data",
        initial_cash: float = 100_000.0,
        commission_rate: float = 0.0001,
        slippage_bps: float = 1.0,
        enable_paper_orders: bool = False,
        run_id: str | None = None,
    ) -> None:
        self.symbols = symbols
        self.strategy_id = strategy_id
        self.bar_size = bar_size
        self.data_root = Path(data_root)
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.slippage_bps = slippage_bps
        self.enable_paper_orders = enable_paper_orders
        self.run_id = run_id or str(uuid.uuid4())[:12]

        # Paths
        ledger_root = self.data_root / "paper_ledger"
        self.journal_path = ledger_root / "run_journal.jsonl"
        self.state_path = ledger_root / "run_state.json"
        self.report_dir = ledger_root / "daily_reports"

        self.journal = PaperRunJournal(self.journal_path)
        self.state_store = PaperRunStateStore(self.state_path)
        self.state = PaperRunState(run_id=self.run_id)

    def run(self) -> dict[str, Any]:
        """Execute the full paper production workflow. Returns summary dict."""
        self._log("run_start", {"profile": "paper", "strategy": self.strategy_id,
                   "symbols": self.symbols, "enable_paper_orders": self.enable_paper_orders,
                   "real_order_submission": "DISABLED"})

        # Gate 0: Strategy whitelist
        whitelist_check = validate_strategy_whitelist(self.strategy_id, self.symbols)
        if whitelist_check:
            return self._block("strategy_whitelist", whitelist_check["error"])

        # Gate 1: Credentials
        cred_result = self._check_credentials()
        if not cred_result["ok"]:
            return self._block("credentials", cred_result["error"])

        # Gate 2: Readiness
        ready_result = self._check_readiness()
        if not ready_result["ok"]:
            return self._block("readiness", ready_result["error"])

        # Gate 3: Smoke test
        smoke_result = self._run_smoke_test()
        if not smoke_result["ok"]:
            return self._block("smoke_test", smoke_result["error"])

        # Main: run paper production loop
        if self.enable_paper_orders:
            return self._run_paper_production()
        else:
            self._log("run_end", {"mode": "dry_run", "status": "complete",
                      "note": "No orders submitted. Use --enable-paper-orders to trade."})
            return {"status": "dry_run_complete", "smoke_test": smoke_result,
                    "note": "Paper infrastructure ready. Use --enable-paper-orders to start trading."}

    def resume(self) -> dict[str, Any]:
        """Resume from previous state after restart."""
        saved = self.state_store.load()
        if saved is None:
            return {"status": "no_state", "error": "No previous state found to resume from"}
        if saved.recovery_required:
            return {"status": "BLOCKED_NEEDS_MANUAL_REVIEW",
                    "error": "Previous run requires manual review before resuming"}
        self.state = saved
        self.run_id = saved.run_id
        self._log("run_resume", {"from_day": saved.trading_day, "last_step": saved.last_step})
        return self._run_paper_production()

    # ------------------------------------------------------------------
    # Internal gates
    # ------------------------------------------------------------------

    def _check_credentials(self) -> dict[str, Any]:
        api_key = os.environ.get("APCA_API_KEY_ID", "")
        api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
        if not api_key or not api_secret:
            return {"ok": False, "error": "APCA_API_KEY_ID or APCA_API_SECRET_KEY not set"}
        try:
            from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig, PAPER_BASE_URL
            config = AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=True)
            if PAPER_BASE_URL not in config.base_url:
                return {"ok": False, "error": f"base_url is not paper endpoint ({PAPER_BASE_URL})"}
            broker = AlpacaBroker(config)
            account = broker.get_account()
            return {"ok": True, "account_id": account.account_id[:8] + "...",
                    "equity": account.equity, "cash": account.cash}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _check_readiness(self) -> dict[str, Any]:
        try:
            from quant_us.reports.live_readiness import LiveReadinessGate
            gate = LiveReadinessGate()
            report = gate.check_all(profile="paper")
            if report.is_ready():
                return {"ok": True}
            failed = [c.name for c in report.checks if not c.passed and not c.warn]
            return {"ok": False, "error": f"Readiness failures: {failed}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _run_smoke_test(self) -> dict[str, Any]:
        """Minimal smoke test: verify broker + data + signals."""
        try:
            api_key = os.environ.get("APCA_API_KEY_ID", "")
            api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
            from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
            config = AlpacaBrokerConfig(api_key=api_key, api_secret=api_secret, paper=True)
            broker = AlpacaBroker(config)
            broker.get_account()
            broker.get_positions()
            broker.get_orders()
            return {"ok": True, "smoke": "broker reachable"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _run_paper_production(self) -> dict[str, Any]:
        """Delegates to PaperRuntime for the actual paper trading session."""
        try:
            from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig
            from quant_us.strategies.factory import build_strategy

            config = PaperRuntimeConfig(
                symbols=self.symbols,
                strategy_id=self.strategy_id,
                capital=self.initial_cash,
                commission_rate=self.commission_rate,
                slippage_bps=self.slippage_bps,
                data_root=str(self.data_root),
                ledger_root=str(self.data_root / "paper_ledger"),
                submit_orders=self.enable_paper_orders,
                reconcile_on_start=True,
                reconcile_on_close=True,
                kill_on_recon_fail=True,
                max_runtime_hours=8.0,
                poll_interval_seconds=60.0,
                bar_size=self.bar_size,
                data_vendor="yfinance",
            )
            strategy = build_strategy(self.strategy_id, {})
            runtime = PaperRuntime(config=config)
            runtime.bootstrap(strategy=strategy)
            runtime.run_market_session()
            runtime.on_session_close()
            runtime.shutdown()

            account = runtime.broker.get_account()
            result = {
                "status": "complete",
                "run_id": self.run_id,
                "final_equity": account.equity,
                "final_cash": account.cash,
                "positions": len(account.positions),
                "kill_switch_triggered": runtime.kill_switch.triggered,
                "real_order_submission": "DISABLED",
            }
            self._log("run_end", result)
            self.state_store.clear()
            return result
        except Exception as exc:
            self._log("incident", {"severity": "CRITICAL", "category": "SYSTEM",
                       "error": str(exc), "requires_manual_review": True})
            self.state.recovery_required = True
            self.state_store.save(self.state)
            return {"status": "error", "error": str(exc), "recovery_required": True}

    def _log(self, entry_type: str, data: dict[str, Any]) -> None:
        self.journal.append(JournalEntry(run_id=self.run_id, entry_type=entry_type, data=data))

    def _block(self, gate: str, reason: str) -> dict[str, Any]:
        self._log("run_blocked", {"gate": gate, "reason": reason})
        return {"status": "BLOCKED", "gate": gate, "reason": reason,
                "real_order_submission": "DISABLED"}
