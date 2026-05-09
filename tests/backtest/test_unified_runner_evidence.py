from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from quant_us.backtest.corporate_actions_ledger import LedgerAdjustment, LedgerAdjustmentLog
from quant_us.backtest.engine import EventDrivenBacktestEngine
from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestRunner
from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar, Signal
from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class AlwaysLongStrategy(Strategy):
    strategy_id: str = "always_long_fixture"
    version: str = "1.2.3"
    strength: float = 1.0

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        return [
            Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=self.strength,
                horizon="1b",
                reason="fixture_long",
            )
        ]


def _bars() -> list[Bar]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    prices = [100.0, 101.0, 100.5, 102.0, 103.0]
    return [
        Bar(
            timestamp_utc=start + timedelta(minutes=i),
            symbol="AAPL",
            open=price - 0.25,
            high=price + 0.5,
            low=price - 0.75,
            close=price,
            volume=100_000.0,
        )
        for i, price in enumerate(prices)
    ]


def _multisymbol_split_bars() -> list[Bar]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    rows: list[Bar] = []
    aapl_prices = [100.0, 50.0, 50.0, 100.0]
    msft_prices = [200.0, 200.0, 100.0, 100.0]
    for idx, price in enumerate(aapl_prices):
        rows.append(
            Bar(
                timestamp_utc=start + timedelta(minutes=idx),
                symbol="AAPL",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=100_000.0,
            )
        )
    for idx, price in enumerate(msft_prices):
        rows.append(
            Bar(
                timestamp_utc=start + timedelta(minutes=idx),
                symbol="MSFT",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=100_000.0,
            )
        )
    return sorted(rows, key=lambda bar: (bar.timestamp_utc, bar.symbol))


def _runner(tmp_path, run_id: str = "ubt_evidence_fixture") -> UnifiedBacktestRunner:
    config = UnifiedBacktestConfig(
        run_id=run_id,
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_bps=2.0,
    )
    runner = UnifiedBacktestRunner(config=config)
    runner.manifest_store = DataManifestStore(tmp_path)
    return runner


def _write_data_manifest(
    tmp_path,
    *,
    data_version: str,
    source: str = "yfinance",
    symbol: str = "AAPL",
    interval: str = "1d",
    asset_class: str = "equity",
    checksum: str = "abc123checksum",
    fingerprint: str = "abc123checksum",
    coverage_pct: float = 100.0,
    quality_score: float = 95.0,
) -> None:
    DataManifestStore(tmp_path).write(
        DataManifest(
            data_version=data_version,
            source=source,
            symbol=symbol,
            interval=interval,
            asset_class=asset_class,
            timezone="UTC",
            start="2024-01-02T14:30:00+00:00",
            end="2024-01-02T14:34:00+00:00",
            row_count=5,
            expected_rows=5,
            coverage_pct=coverage_pct,
            fingerprint=fingerprint,
            checksum=checksum,
            quality_score=quality_score,
            raw_path="/tmp/raw/AAPL.parquet",
            cleaned_path="/tmp/clean/AAPL.parquet",
        )
    )


def test_event_driven_evidence_and_manifest_are_promotion_grade(tmp_path):
    _write_data_manifest(tmp_path, data_version="qs-yfinance-AAPL-1d-test")
    runner = _runner(tmp_path)
    result = runner.run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=_bars(),
        data_version="qs-yfinance-AAPL-1d-test",
        strategy_version="always_long_v1",
    )

    evidence = result.evidence
    assert evidence["engine"] == "event_driven"
    assert evidence["canonical_for_promotion"] is True
    assert evidence["approximate_scan_engine"] is False
    assert evidence["data_version"] == "qs-yfinance-AAPL-1d-test"
    assert evidence["data_manifest_exists"] is True
    assert evidence["missing_data_manifest"] is False
    assert evidence["data_scope"]["promotion_scope_ok"] is True
    assert evidence["strategy"]["strategy_version"] == "always_long_v1"
    assert evidence["strategy"]["strategies"][0]["params"]["strength"] == 1.0
    assert evidence["commit_hash"]
    assert evidence["data_manifest"]["data_manifest_id"]
    assert evidence["data_manifest"]["path"] == str(tmp_path / "qs-yfinance-AAPL-1d-test.json")
    assert evidence["data_manifest"]["checksum"] == "abc123checksum"
    assert evidence["data_manifest"]["fingerprint"] == "abc123checksum"
    assert evidence["data_manifest"]["source"] == "yfinance"
    assert evidence["data_manifest"]["asset_class"] == "equity"
    assert evidence["data_manifest"]["symbol"] == "AAPL"
    assert evidence["data_manifest"]["interval"] == "1d"
    assert evidence["data_manifest"]["coverage"]["coverage_pct"] == 100.0
    assert evidence["data_manifest"]["quality"]["quality_score"] == 95.0
    assert evidence["data_manifest"]["data_version_matches_requested"] is True
    assert evidence["generated_at"] == evidence["as_of_utc"]
    assert evidence["ledger_artifact_hash"] == evidence["ledger_artifact"]["artifact_hash"]
    assert Path(evidence["ledger_artifact_path"]).exists()
    artifact_file = json.loads(Path(evidence["ledger_artifact_path"]).read_text(encoding="utf-8"))
    assert artifact_file == evidence["ledger_artifact"]
    assert evidence["ledger_hash"] == evidence["ledger_artifact"]["hashes"]["ledger_hash"]
    assert evidence["fills_hash"] == evidence["ledger_artifact"]["hashes"]["fills_hash"]
    assert evidence["orders_hash"] == evidence["ledger_artifact"]["hashes"]["orders_hash"]
    assert evidence["portfolio_snapshots_hash"] == evidence["ledger_artifact"]["hashes"]["portfolio_snapshots_hash"]

    assert evidence["orders"]["count"] > 0
    assert evidence["orders"]["all_orders_created_by_oms"] is True
    assert evidence["orders"]["all_orders_have_risk_check_id"] is True
    assert evidence["orders"]["orders_hash"] == evidence["orders_hash"]
    assert evidence["fills"]["count"] > 0
    assert evidence["fills"]["all_fills_match_orders"] is True
    assert evidence["fills"]["fills_hash"] == evidence["fills_hash"]
    assert evidence["fills"]["effective_fills_hash"] == evidence["ledger_artifact"]["hashes"]["effective_fills_hash"]
    assert evidence["risk"]["risk_check_count"] >= evidence["orders"]["count"]

    assert evidence["cash"]["cash_consistent"] is True
    assert evidence["positions"]["position_count"] == 1
    assert evidence["fees"]["fees_from_fills"] is True
    assert evidence["fees"]["total_commission"] > 0
    assert evidence["pnl"]["source"] == "ledger_fills"
    assert evidence["equity"]["consistent"] is True
    assert evidence["reconciliation"]["summary"]["passed"] is True
    assert evidence["reconciliation"]["summary"]["snapshot_count"] == len(result.snapshots)
    assert evidence["reconciliation"]["snapshots"][-1]["diff"] == {"cash": 0.0, "equity": 0.0}
    assert evidence["corporate_actions"]["summary"]["adjustment_count"] == 0
    assert evidence["completeness"]["ledger_evidence_complete"] is True
    assert evidence["completeness"]["data_manifest_bound"] is True
    assert evidence["completeness"]["promotion_evidence_complete"] is True

    manifest_path = tmp_path / f"run_{result.run_id}.json"
    assert result.manifest_path == str(manifest_path)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["engine"] == "event_driven"
    assert manifest["generated_at"] == evidence["generated_at"]
    assert manifest["data_version"] == "qs-yfinance-AAPL-1d-test"
    assert manifest["ledger_artifact_hash"] == evidence["ledger_artifact_hash"]
    assert manifest["ledger_artifact_path"] == evidence["ledger_artifact_path"]
    assert manifest["ledger_hash"] == evidence["ledger_hash"]
    assert manifest["fills_hash"] == evidence["fills_hash"]
    assert manifest["cost_model"]
    assert manifest["commission_model"]
    assert manifest["slippage_model"]
    assert manifest["data_manifest_exists"] is True
    assert manifest["missing_data_manifest"] is False
    assert manifest["data_manifest"]["path"] == str(tmp_path / "qs-yfinance-AAPL-1d-test.json")
    assert manifest["data_manifest"]["checksum"] == "abc123checksum"
    assert manifest["evidence"]["data_manifest"]["data_version_matches_requested"] is True
    assert manifest["reconciliation"]["passed"] is True
    assert manifest["ledger_artifact"]["artifact_hash"] == evidence["ledger_artifact_hash"]
    assert json.loads(Path(manifest["ledger_artifact_path"]).read_text(encoding="utf-8")) == manifest["ledger_artifact"]
    assert manifest["ledger_artifact"]["reconciliation"]["summary"] == manifest["reconciliation"]
    assert manifest["corporate_actions"]["adjustment_count"] == 0


def test_fixed_fixture_repeated_runs_have_identical_summary_and_evidence(tmp_path):
    _write_data_manifest(tmp_path, data_version="qs-yfinance-AAPL-1d-test")
    first = _runner(tmp_path, run_id="ubt_determinism_fixture").run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=_bars(),
        data_version="qs-yfinance-AAPL-1d-test",
        strategy_version="always_long_v1",
    )
    second = _runner(tmp_path, run_id="ubt_determinism_fixture").run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=_bars(),
        data_version="qs-yfinance-AAPL-1d-test",
        strategy_version="always_long_v1",
    )

    assert first.summary == second.summary
    assert first.evidence == second.evidence
    assert first.evidence["ledger_artifact"] == second.evidence["ledger_artifact"]


def test_manifest_write_failure_is_not_silent(tmp_path):
    root_file = tmp_path / "not_a_directory"
    root_file.write_text("occupied", encoding="utf-8")
    runner = _runner(root_file, run_id="ubt_manifest_failure")

    with pytest.raises(
        RuntimeError,
        match="Unable to write (backtest run manifest|ledger reconciliation artifact)",
    ):
        runner.run(
            strategies=[AlwaysLongStrategy(strength=1.0)],
            bars_override=_bars(),
            data_version="fixture_bars_v1",
            strategy_version="always_long_v1",
        )


def test_missing_data_manifest_blocks_promotion_completeness_but_not_ledger_completeness(tmp_path):
    runner = _runner(tmp_path, run_id="ubt_missing_data_manifest")
    result = runner.run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=_bars(),
        data_version="qs-yfinance-AAPL-1d-missing",
        strategy_version="always_long_v1",
    )

    assert result.evidence["data_manifest_exists"] is False
    assert result.evidence["missing_data_manifest"] is True
    assert result.evidence["data_manifest"]["path"] == str(tmp_path / "qs-yfinance-AAPL-1d-missing.json")
    assert result.evidence["data_manifest"]["checksum"] == ""
    assert result.evidence["completeness"]["ledger_evidence_complete"] is True
    assert result.evidence["completeness"]["data_manifest_bound"] is False
    assert result.evidence["completeness"]["promotion_evidence_complete"] is False


def test_snapshot_reconciliation_failure_blocks_promotion_evidence(tmp_path):
    _write_data_manifest(tmp_path, data_version="qs-yfinance-AAPL-1d-reconciliation-fail")
    runner = _runner(tmp_path, run_id="ubt_reconciliation_failure")
    original_run = EventDrivenBacktestEngine.run

    def run_with_bad_snapshot(self, bars):
        result = original_run(self, bars)
        object.__setattr__(result.snapshots[-1], "equity", result.snapshots[-1].equity + 500.0)
        return result

    with patch.object(EventDrivenBacktestEngine, "run", new=run_with_bad_snapshot):
        result = runner.run(
            strategies=[AlwaysLongStrategy(strength=1.0)],
            bars_override=_bars(),
            data_version="qs-yfinance-AAPL-1d-reconciliation-fail",
            strategy_version="always_long_v1",
        )

    assert result.equity_consistent is False
    assert result.evidence["reconciliation"]["summary"]["passed"] is False
    assert result.evidence["reconciliation"]["snapshots"][-1]["passed"] is False
    assert result.evidence["completeness"]["ledger_evidence_complete"] is False
    assert result.evidence["completeness"]["promotion_evidence_complete"] is False


def test_fixture_data_version_is_not_marked_promotion_complete(tmp_path):
    _write_data_manifest(
        tmp_path,
        data_version="qs-fixture-AAPL-1d-test",
        source="fixture",
        checksum="fixturechecksum",
        fingerprint="fixturechecksum",
    )
    runner = _runner(tmp_path, run_id="ubt_fixture_scope")
    result = runner.run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=_bars(),
        data_version="qs-fixture-AAPL-1d-test",
        strategy_version="always_long_v1",
    )

    assert result.evidence["data_manifest_exists"] is True
    assert result.evidence["data_manifest"]["data_version_matches_requested"] is True
    assert result.evidence["completeness"]["ledger_evidence_complete"] is True
    assert result.evidence["completeness"]["data_manifest_bound"] is True
    assert result.evidence["completeness"]["promotion_evidence_complete"] is False
    assert result.evidence["data_scope"]["fixture_like_data_version"] is True
    assert result.evidence["data_scope"]["scope_rejections"] == ["fixture_data_version"]


def test_realized_commission_and_slippage_are_ledger_exact(tmp_path):
    _write_data_manifest(tmp_path, data_version="qs-yfinance-AAPL-1d-cost-fixture")
    config = UnifiedBacktestConfig(
        run_id="ubt_cost_fixture",
        initial_cash=100_000.0,
        commission_rate=0.001,
        slippage_bps=10.0,
    )
    runner = UnifiedBacktestRunner(config=config)
    runner.manifest_store = DataManifestStore(tmp_path)

    result = runner.run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=_bars()[:1],
        data_version="qs-yfinance-AAPL-1d-cost-fixture",
        strategy_version="always_long_v1",
    )

    fill = result.fills[0]
    assert fill.quantity == pytest.approx(100.0)
    assert fill.price == pytest.approx(100.1)
    assert fill.commission == pytest.approx(10.01)
    assert result.ledger_curve.points[-1].cumulative_slippage_cost == pytest.approx(10.0)
    assert result.evidence["commission"]["realized_total"] == pytest.approx(10.01)
    assert result.evidence["slippage"]["realized_total"] == pytest.approx(10.0)
    assert result.evidence["fees"]["ledger_total_fees"] == pytest.approx(10.01)
    assert result.evidence["pnl"]["final_equity"] == pytest.approx(99_979.99)


def test_split_adjustments_are_deterministic_across_symbols_and_bars(tmp_path):
    bars = _multisymbol_split_bars()
    start = bars[0].timestamp_utc
    config = UnifiedBacktestConfig(
        run_id="ubt_multisymbol_split_fixture",
        initial_cash=100_000.0,
        commission_rate=0.0,
        slippage_bps=0.0,
        adjustment_log=LedgerAdjustmentLog(
            adjustments=[
                LedgerAdjustment(
                    timestamp_utc=start + timedelta(minutes=1),
                    symbol="AAPL",
                    adjustment_type="split",
                    amount=0.0,
                    quantity_multiplier=2.0,
                    description="AAPL 2:1 split",
                ),
                LedgerAdjustment(
                    timestamp_utc=start + timedelta(minutes=2),
                    symbol="MSFT",
                    adjustment_type="split",
                    amount=0.0,
                    quantity_multiplier=2.0,
                    description="MSFT 2:1 split",
                ),
                LedgerAdjustment(
                    timestamp_utc=start + timedelta(minutes=3),
                    symbol="AAPL",
                    adjustment_type="split",
                    amount=0.0,
                    quantity_multiplier=0.5,
                    description="AAPL 1:2 reverse split",
                ),
            ]
        ),
    )

    first_runner = UnifiedBacktestRunner(config=config)
    first_runner.manifest_store = DataManifestStore(tmp_path)
    first = first_runner.run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=bars,
        data_version="qs-yfinance-multisymbol-splits",
        strategy_version="always_long_v1",
    )

    second_runner = UnifiedBacktestRunner(config=config)
    second_runner.manifest_store = DataManifestStore(tmp_path)
    second = second_runner.run(
        strategies=[AlwaysLongStrategy(strength=1.0)],
        bars_override=bars,
        data_version="qs-yfinance-multisymbol-splits",
        strategy_version="always_long_v1",
    )

    assert first.equity_consistent is True
    assert first.evidence["positions"]["final_positions"] == {"AAPL": 100.0, "MSFT": 100.0}
    assert first.evidence["cash"]["ledger_cash_at_final_snapshot"] == pytest.approx(80_000.0)
    assert first.evidence["pnl"]["final_equity"] == pytest.approx(100_000.0)
    assert first.evidence["reconciliation"]["summary"]["passed"] is True
    assert first.evidence["corporate_actions"]["summary"]["adjustment_count"] == 3
    assert first.evidence["corporate_actions"]["summary"]["split_event_count"] == 3
    assert first.evidence["corporate_actions"]["adjustments"][0]["symbol"] == "AAPL"
    assert first.summary == second.summary
    assert first.evidence == second.evidence
    assert [(snap.timestamp_utc, snap.cash, snap.equity) for snap in first.snapshots] == [
        (snap.timestamp_utc, snap.cash, snap.equity) for snap in second.snapshots
    ]
    assert [(fill.symbol, fill.quantity, fill.price) for fill in first.fills] == [
        (fill.symbol, fill.quantity, fill.price) for fill in second.fills
    ]
