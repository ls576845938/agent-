"""Event-driven CN backtest bound to G06 OMS, ledger, and replay contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import math

from quant_cn.application.closed_loop import build_decision_chain
from quant_cn.backtest.costs import CostScenario
from quant_cn.backtest.events import BacktestEvent
from quant_cn.backtest.evidence import AnnualAttribution, ScenarioMetrics
from quant_cn.compat.shared_adapter import canonical_cn_payload_hash
from quant_cn.execution.oms import OfflineOMS
from quant_cn.execution.simulator import SimulationSnapshot, simulate
from quant_cn.ledger.accounting import (
    derive_account_state,
    post_fill,
    post_mark,
    post_opening_cash,
    sellable_quantity,
)
from quant_cn.ledger.reconciliation import ReconciliationResult, reconcile
from quant_cn.ledger.store import InMemoryLedgerStore
from quant_cn.portfolio.risk import (
    RiskInputs,
    TargetPosition as RiskTargetPosition,
    build_order_intent,
    evaluate_target,
)
from quant_cn.replay.engine import ReplayInput, run_replay
from quant_cn.strategy.contracts import ForecastModel, Strategy, TargetBuilder


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal
    position_quantity: int


@dataclass(frozen=True)
class BacktestScenarioResult:
    scenario: CostScenario
    metrics: ScenarioMetrics
    orders: tuple[object, ...]
    fills: tuple[object, ...]
    ledger_hash: str
    replay_hash: str
    reconciliation: ReconciliationResult
    audit_events: tuple[dict[str, str], ...]
    blockers: tuple[str, ...]


class EventDrivenBacktest:
    def __init__(
        self,
        *,
        strategy: Strategy,
        forecast_model: ForecastModel,
        target_builder: TargetBuilder,
        settlement_sessions: int = 1,
    ) -> None:
        if settlement_sessions < 0:
            raise ValueError("settlement_sessions_must_be_non_negative")
        self.strategy = strategy
        self.forecast_model = forecast_model
        self.target_builder = target_builder
        self.settlement_sessions = settlement_sessions

    def run(
        self,
        *,
        run_id: str,
        events: tuple[BacktestEvent, ...],
        initial_cash: Decimal,
        scenario: CostScenario,
        fixed_clock: datetime,
        seed: int,
    ) -> BacktestScenarioResult:
        if not events:
            raise ValueError("backtest_events_required")
        ordered = tuple(sorted(events, key=lambda item: (item.decision_time, item.event_id)))
        if len({item.event_id for item in ordered}) != len(ordered):
            raise ValueError("backtest_event_id_duplicate")
        if any(item.execution_time > fixed_clock for item in ordered):
            raise ValueError("backtest_event_after_fixed_clock")
        oms = OfflineOMS()
        ledger = InMemoryLedgerStore()
        post_opening_cash(
            ledger,
            record_id=f"opening:{run_id}:{scenario.name}",
            amount=initial_cash,
            occurred_at=ordered[0].event_time,
            source_hash=ordered[0].data_version,
        )
        fills: list[object] = []
        audits: list[dict[str, str]] = []
        blockers: list[str] = []
        equity_curve: list[EquityPoint] = []
        fee_policy = scenario.fee_policy()
        turnover_notional = Decimal("0")
        slippage_paid = Decimal("0")
        impact_paid = Decimal("0")
        holding_sessions = 0
        exposed_sessions = 0
        annual_start: dict[int, Decimal] = {}
        annual_end: dict[int, Decimal] = {}

        for index, event in enumerate(ordered):
            pre_state = derive_account_state(ledger)
            year = event.execution_time.year
            annual_start.setdefault(year, pre_state.equity)
            current_quantity = dict(pre_state.positions).get(event.stable_security_id, 0)
            effective_capacity = int(
                Decimal(event.capacity_quantity) * scenario.capacity_fraction
            )
            chain = build_decision_chain(
                strategy=self.strategy,
                forecast_model=self.forecast_model,
                target_builder=self.target_builder,
                snapshot=event.decision_snapshot(),
                current_quantity=current_quantity,
                capacity_quantity=effective_capacity,
            )
            target_quantity = chain.target.target_quantity
            if target_quantity != current_quantity:
                side = "buy" if target_quantity > current_quantity else "sell"
                quantity = abs(target_quantity - current_quantity)
                sellable = sellable_quantity(
                    ledger,
                    stable_security_id=event.stable_security_id,
                    current_session_sequence=event.session_sequence,
                    settlement_sessions=self.settlement_sessions,
                )
                estimated_notional = event.reference_price * quantity
                estimated_fee = fee_policy.total_charge(
                    side=side, notional=estimated_notional
                )
                risk_inputs = RiskInputs(
                    preflight=event.preflight,
                    board_lot_policy=event.board_lot_policy,
                    rule_versions=event.rule_versions,
                    limit_price=event.reference_price,
                    available_cash=pre_state.cash,
                    sellable_quantity=sellable,
                    estimated_fee=estimated_fee,
                    max_order_notional=max(
                        event.reference_price * max(effective_capacity, 1),
                        event.reference_price,
                    ),
                    session_sequence=event.session_sequence,
                )
                risk_target = RiskTargetPosition(
                    target_id=chain.target.target_id,
                    run_id=run_id,
                    stable_security_id=event.stable_security_id,
                    target_quantity=target_quantity,
                    current_quantity=current_quantity,
                    decision_time=event.decision_time,
                    evidence_hash=canonical_cn_payload_hash(
                        {
                            "forecast_id": chain.forecast.forecast_id,
                            "signal_id": chain.signal.signal_id,
                            "snapshot_id": chain.snapshot.snapshot_id,
                            "target_id": chain.target.target_id,
                        }
                    ),
                )
                risk = evaluate_target(
                    risk_target,
                    risk_inputs,
                    decision_id=f"risk-{scenario.name}-{index}",
                )
                if risk.approved:
                    intent = build_order_intent(
                        risk_target,
                        risk,
                        risk_inputs,
                        order_id=f"order-{scenario.name}-{index}",
                        client_order_id=f"client-{run_id}-{scenario.name}-{index}",
                        created_at=event.order_created_time,
                    )
                    oms.submit(intent)
                    execution_price = scenario.execution_price(
                        side=side,
                        reference_price=event.reference_price,
                        tick_size=event.tick_size,
                    )
                    result = simulate(
                        intent,
                        preflight=event.preflight,
                        snapshot=SimulationSnapshot(
                            snapshot_id=f"execution-{event.event_id}",
                            as_of=event.execution_time,
                            phase=event.phase,
                            accepts_orders=event.accepts_orders,
                            suspended=event.suspended,
                            lower_limit_price=event.lower_limit_price,
                            upper_limit_price=event.upper_limit_price,
                            tick_size=event.tick_size,
                            available_liquidity=event.available_liquidity,
                            available_cash=pre_state.cash,
                            current_position=current_quantity,
                            sellable_quantity=sellable,
                            execution_price=execution_price,
                            rule_source_versions=event.rule_versions,
                        ),
                        board_lot_policy=event.board_lot_policy,
                        fee_policy=fee_policy,
                        fill_id=f"fill-{scenario.name}-{index}",
                        received_at=event.execution_time,
                    )
                    if result.fills:
                        for fill in result.fills:
                            oms.apply_fill(fill)
                            post_fill(ledger, fill)
                            fills.append(fill)
                            turnover_notional += fill.notional
                            slippage_paid += (
                                event.reference_price
                                * fill.quantity
                                * scenario.slippage_bps
                                / Decimal("10000")
                            )
                            impact_paid += (
                                event.reference_price
                                * fill.quantity
                                * scenario.market_impact_bps
                                / Decimal("10000")
                            )
                    else:
                        oms.reject(intent.order_id, result.blockers)
                        blockers.extend(result.blockers)
                else:
                    blockers.extend(risk.blockers)
                audits.append(
                    {
                        "data_version": event.data_version,
                        "decision_time": event.decision_time.isoformat(),
                        "error_code": "" if risk.approved else ",".join(risk.blockers),
                        "fill_id": f"fill-{scenario.name}-{index}" if risk.approved else "",
                        "forecast_id": chain.forecast.forecast_id,
                        "order_id": f"order-{scenario.name}-{index}" if risk.approved else "",
                        "risk_decision_id": risk.decision_id,
                        "run_id": run_id,
                        "signal_id": chain.signal.signal_id,
                        "strategy_id": chain.signal.strategy_id,
                        "target_position": str(chain.target.target_quantity),
                    }
                )
            post_mark(
                ledger,
                record_id=f"mark:{scenario.name}:{event.event_id}",
                stable_security_id=event.stable_security_id,
                price=event.mark_price,
                occurred_at=event.execution_time,
                source_hash=event.data_version,
            )
            state = derive_account_state(ledger)
            position = dict(state.positions).get(event.stable_security_id, 0)
            if position:
                holding_sessions += 1
                exposed_sessions += 1
            point = EquityPoint(event.execution_time, state.equity, position)
            equity_curve.append(point)
            annual_end[year] = state.equity

        final_state = derive_account_state(ledger)
        reconciliation = reconcile(
            orders=oms.states(), ledger=ledger, opening_cash=initial_cash
        )
        blockers.extend(reconciliation.blockers)
        replay = run_replay(
            ReplayInput(
                replay_id=f"{run_id}-{scenario.name}",
                source_mode="injected_history",
                source_ref=f"immutable-{ordered[0].data_version}",
                fixed_clock=fixed_clock,
                seed=seed,
                opening_cash=initial_cash,
                orders=tuple(item.intent for item in oms.states()),
                fills=tuple(fills),
                expected_cash=final_state.cash,
                expected_positions=final_state.positions,
            )
        )
        blockers.extend(replay.blockers)
        ledger_hash = sha256(
            json.dumps(
                tuple((item.record_id, item.fingerprint) for item in ledger.records()),
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        metrics = _metrics(
            initial_cash=initial_cash,
            final_equity=final_state.equity,
            equity_curve=tuple(equity_curve),
            turnover_notional=turnover_notional,
            fee_paid=sum((fill.total_fee for fill in fills), Decimal("0")),
            slippage_paid=slippage_paid,
            impact_paid=impact_paid,
            holding_sessions=holding_sessions,
            exposed_sessions=exposed_sessions,
            number_of_bets=len(oms.states()),
            capacity_proxy=min(
                (
                    event.reference_price
                    * int(Decimal(event.capacity_quantity) * scenario.capacity_fraction)
                    for event in ordered
                ),
                default=Decimal("0"),
            ),
            annual_start=annual_start,
            annual_end=annual_end,
        )
        return BacktestScenarioResult(
            scenario=scenario,
            metrics=metrics,
            orders=oms.states(),
            fills=tuple(fills),
            ledger_hash=ledger_hash,
            replay_hash=replay.replay_hash,
            reconciliation=reconciliation,
            audit_events=tuple(audits),
            blockers=tuple(sorted(set(blockers))),
        )


def _metrics(
    *,
    initial_cash: Decimal,
    final_equity: Decimal,
    equity_curve: tuple[EquityPoint, ...],
    turnover_notional: Decimal,
    fee_paid: Decimal,
    slippage_paid: Decimal,
    impact_paid: Decimal,
    holding_sessions: int,
    exposed_sessions: int,
    number_of_bets: int,
    capacity_proxy: Decimal,
    annual_start: dict[int, Decimal],
    annual_end: dict[int, Decimal],
) -> ScenarioMetrics:
    total_return = (
        (final_equity - initial_cash) / initial_cash
        if initial_cash
        else Decimal("0")
    )
    returns: list[float] = []
    prior = initial_cash
    peaks: list[Decimal] = []
    peak = initial_cash
    drawdowns: list[Decimal] = []
    for point in equity_curve:
        if prior:
            returns.append(float((point.equity - prior) / prior))
        prior = point.equity
        peak = max(peak, point.equity)
        peaks.append(peak)
        drawdowns.append(
            (peak - point.equity) / peak if peak else Decimal("0")
        )
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = (
        sum((item - mean) ** 2 for item in returns) / max(len(returns) - 1, 1)
        if returns
        else 0.0
    )
    annualized_volatility = Decimal(str(math.sqrt(variance) * math.sqrt(252)))
    annualized_return = Decimal(str(mean * 252))
    sharpe = (
        annualized_return / annualized_volatility
        if annualized_volatility
        else Decimal("0")
    )
    yearly_pnl = {
        year: annual_end[year] - annual_start[year] for year in annual_end
    }
    total_abs_yearly = sum((abs(value) for value in yearly_pnl.values()), Decimal("0"))
    attribution = tuple(
        AnnualAttribution(
            year=year,
            pnl=pnl,
            return_fraction=pnl / annual_start[year] if annual_start[year] else Decimal("0"),
            contribution_share=abs(pnl) / total_abs_yearly if total_abs_yearly else Decimal("0"),
        )
        for year, pnl in sorted(yearly_pnl.items())
    )
    return ScenarioMetrics(
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe=sharpe,
        max_drawdown=max(drawdowns, default=Decimal("0")),
        turnover=turnover_notional / initial_cash if initial_cash else Decimal("0"),
        average_holding_sessions=(
            Decimal(holding_sessions) / max(number_of_bets, 1)
        ),
        exposure_ratio=(
            Decimal(exposed_sessions) / len(equity_curve)
            if equity_curve
            else Decimal("0")
        ),
        number_of_bets=number_of_bets,
        fee_paid=fee_paid,
        slippage_paid=slippage_paid,
        market_impact_paid=impact_paid,
        best_year_contribution_share=max(
            (item.contribution_share for item in attribution), default=Decimal("0")
        ),
        worst_year=(
            min(yearly_pnl, key=yearly_pnl.get) if yearly_pnl else None
        ),
        capacity_proxy=capacity_proxy,
        annual_attribution=attribution,
    )
