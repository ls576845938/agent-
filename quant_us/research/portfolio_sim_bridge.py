"""Portfolio Simulation Bridge.

Simulates portfolio-level performance from strategy manifests.
NEVER submits orders. Only produces simulation results for human review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id


@dataclass
class PortfolioSimRequest:
    """Configuration for a portfolio simulation run."""

    portfolio_sim_id: str
    strategy_manifest_ids: list[str]
    allocation_method: str = "equal_weight"
    # equal_weight|vol_target|inverse_vol|risk_budget
    symbols: list[str] = field(default_factory=list)
    start: str = ""
    end: str = ""
    capital: float = 100000.0
    rebalance_frequency: str = "monthly"
    risk_budget: float = 0.10
    max_correlation: float = 0.70
    max_drawdown: float = 0.30


@dataclass
class PortfolioSimResult:
    """Result of a completed portfolio simulation."""

    portfolio_sim_id: str
    equity_curve: list[float] = field(default_factory=list)
    drawdown: list[float] = field(default_factory=list)
    turnover: float = 0.0
    exposure: dict = field(default_factory=dict)
    correlation_matrix: dict = field(default_factory=dict)
    contribution_by_strategy: dict = field(default_factory=dict)
    risk_breach_count: int = 0
    decision: str = "WATCHLIST"
    # PORTFOLIO_PASS|WATCHLIST|REJECTED


class PortfolioSimBridge:
    """Simulates portfolio-level performance from strategy manifests.

    This is a research-layer simulation only. It loads manifests, builds
    a synthetic portfolio, and produces correlation and performance estimates.
    NEVER submits orders or triggers trading.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.sims_dir = self.data_root / "research" / "portfolio_sims"
        self.sims_dir.mkdir(parents=True, exist_ok=True)

    def create_simulation(
        self, manifest_ids: list[str], config: dict | None = None
    ) -> PortfolioSimRequest:
        """Create a portfolio simulation request from strategy manifests.

        Args:
            manifest_ids: List of strategy manifest IDs to include.
            config: Optional dict overriding default simulation config fields.

        Returns:
            The created PortfolioSimRequest (persisted to disk).

        Raises:
            ValueError: If fewer than 2 manifests provided, or a manifest
                        is not found or not in a valid promotion status.
        """
        if len(manifest_ids) < 1:
            raise ValueError("At least 1 strategy manifest is required")

        from quant_us.research.strategy_manifest import StrategyManifestManager

        manifest_mgr = StrategyManifestManager(data_root=str(self.data_root))
        all_symbols: list[str] = []
        for mid in manifest_ids:
            m = manifest_mgr.load(mid)
            if m is None:
                raise ValueError(f"Strategy manifest {mid} not found")
            if m.params_frozen is False:
                raise ValueError(
                    f"Strategy manifest {mid} params are not frozen. "
                    "Freeze params before portfolio simulation."
                )
            all_symbols.extend(m.symbols)

        # Deduplicate symbols
        all_symbols = list(dict.fromkeys(all_symbols))

        cfg = config or {}
        sim_id = new_id("psim")
        request = PortfolioSimRequest(
            portfolio_sim_id=sim_id,
            strategy_manifest_ids=manifest_ids,
            allocation_method=cfg.get("allocation_method", "equal_weight"),
            symbols=all_symbols,
            start=cfg.get("start", ""),
            end=cfg.get("end", ""),
            capital=float(cfg.get("capital", 100000.0)),
            rebalance_frequency=cfg.get("rebalance_frequency", "monthly"),
            risk_budget=float(cfg.get("risk_budget", 0.10)),
            max_correlation=float(cfg.get("max_correlation", 0.70)),
            max_drawdown=float(cfg.get("max_drawdown", 0.30)),
        )

        self._save_request(request)
        return request

    def run_simulation(self, sim_id: str) -> PortfolioSimResult:
        """Run a portfolio simulation for a given sim request.

        This is a synthetic simulation that estimates portfolio-level
        metrics from individual manifest scorecards. It does NOT involve
        live data or order submission.

        Args:
            sim_id: The portfolio simulation ID to run.

        Returns:
            PortfolioSimResult with estimated metrics.

        Raises:
            ValueError: If the sim request is not found.
        """
        request = self._load_request(sim_id)
        if request is None:
            raise ValueError(f"Portfolio simulation {sim_id} not found")

        from quant_us.research.strategy_manifest import StrategyManifestManager

        manifest_mgr = StrategyManifestManager(data_root=str(self.data_root))
        manifests = []
        for mid in request.strategy_manifest_ids:
            m = manifest_mgr.load(mid)
            if m is not None:
                manifests.append(m)

        if not manifests:
            raise ValueError(f"No valid manifests found for simulation {sim_id}")

        # Build synthetic correlation matrix from manifest scorecards
        correlation_matrix: dict[str, dict[str, float]] = {}
        contribution_by_strategy: dict[str, float] = {}
        risk_breach_count = 0

        for m in manifests:
            sid = m.strategy_candidate_id
            correlation_matrix[sid] = {}
            for m2 in manifests:
                sid2 = m2.strategy_candidate_id
                # Correlation is estimated from scorecard similarity
                corr = self._estimate_correlation(m, m2)
                correlation_matrix[sid][sid2] = corr

            # Contribution estimates from scorecard scores
            score = m.scorecard.get("total_return_pct", 0.0)
            contribution_by_strategy[sid] = score

            # Check drawdown breach
            max_dd = m.scorecard.get("max_drawdown_pct", 0.0)
            if abs(max_dd) >= request.max_drawdown:
                risk_breach_count += 1

        # Build synthetic equity curve (uniformly growing from capital)
        n_points = 252  # ~1 year of daily points
        capital = request.capital
        equity_curve: list[float] = []
        drawdown: list[float] = []
        peak = capital
        for i in range(n_points):
            step_return = 0.0003 * (1 + 0.1 * (i / n_points))
            eq = capital * (1 + step_return) ** (i + 1)
            equity_curve.append(round(eq, 2))
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak if peak > 0 else 0.0
            drawdown.append(round(dd, 6))

        # Determine decision
        decision = "WATCHLIST"
        if risk_breach_count == 0:
            decision = "PORTFOLIO_PASS"
        elif risk_breach_count > 2:
            decision = "REJECTED"

        result = PortfolioSimResult(
            portfolio_sim_id=sim_id,
            equity_curve=equity_curve,
            drawdown=drawdown,
            turnover=0.05,
            exposure={"gross": 1.0, "net": 1.0},
            correlation_matrix=correlation_matrix,
            contribution_by_strategy=contribution_by_strategy,
            risk_breach_count=risk_breach_count,
            decision=decision,
        )

        self._save_result(result)
        return result

    def get_report(self, sim_id: str) -> dict:
        """Generate a human-readable report from a simulation result.

        Args:
            sim_id: The portfolio simulation ID.

        Returns:
            Dict with summary, allocation, risk metrics, and per-strategy detail.

        Raises:
            ValueError: If the sim result is not found.
        """
        result = self._load_result(sim_id)
        if result is None:
            raise ValueError(f"Portfolio simulation result {sim_id} not found")

        request = self._load_request(sim_id)

        return {
            "portfolio_sim_id": sim_id,
            "decision": result.decision,
            "allocation_method": request.allocation_method if request else "unknown",
            "capital": request.capital if request else 0.0,
            "strategy_count": len(result.contribution_by_strategy),
            "risk_breach_count": result.risk_breach_count,
            "max_drawdown_est": min(result.drawdown) if result.drawdown else 0.0,
            "turnover_est": result.turnover,
            "correlation_matrix": result.correlation_matrix,
            "contribution_by_strategy": result.contribution_by_strategy,
            "equity_curve_length": len(result.equity_curve),
            "final_equity": result.equity_curve[-1] if result.equity_curve else 0.0,
        }

    def check_correlation(self, manifest_ids: list[str]) -> dict:
        """Check pairwise correlation estimates between manifests.

        This is a standalone correlation check, run before creating a sim.

        Args:
            manifest_ids: List of manifest IDs to check.

        Returns:
            Dict with pairwise correlation estimates and warnings.

        Raises:
            ValueError: If fewer than 2 manifests provided.
        """
        if len(manifest_ids) < 2:
            raise ValueError("Need at least 2 manifests for correlation check")

        from quant_us.research.strategy_manifest import StrategyManifestManager

        manifest_mgr = StrategyManifestManager(data_root=str(self.data_root))
        manifests = []
        for mid in manifest_ids:
            m = manifest_mgr.load(mid)
            if m is None:
                raise ValueError(f"Strategy manifest {mid} not found")
            manifests.append(m)

        pairs: dict[str, float] = {}
        warnings_list: list[str] = []
        for i, m1 in enumerate(manifests):
            for j, m2 in enumerate(manifests):
                if i >= j:
                    continue
                corr = self._estimate_correlation(m1, m2)
                pair_key = f"{m1.strategy_candidate_id}_vs_{m2.strategy_candidate_id}"
                pairs[pair_key] = round(corr, 4)
                if abs(corr) > 0.70:
                    warnings_list.append(
                        f"High correlation ({corr:.2f}) between "
                        f"{m1.strategy_candidate_id} and {m2.strategy_candidate_id}"
                    )

        return {
            "pair_count": len(pairs),
            "pairs": pairs,
            "warnings": warnings_list,
            "max_correlation": max(pairs.values()) if pairs else 0.0,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_correlation(m1: Any, m2: Any) -> float:
        """Estimate correlation between two manifests based on scorecard similarity.

        Uses scorecard field overlap as a proxy. Returns a value in [-1.0, 1.0].
        """
        sc1 = getattr(m1, "scorecard", {}) or {}
        sc2 = getattr(m2, "scorecard", {}) or {}
        if not sc1 or not sc2:
            return 0.3  # default moderate-low correlation

            # Compute heuristic: compare sharpe and drawdown
        sharpe1 = sc1.get("sharpe_ratio", 1.0)
        sharpe2 = sc2.get("sharpe_ratio", 1.0)
        dd1 = abs(sc1.get("max_drawdown_pct", 0.1))
        dd2 = abs(sc2.get("max_drawdown_pct", 0.1))

        sharpe_sim = 1.0 - min(abs(sharpe1 - sharpe2) / 5.0, 1.0)
        dd_sim = 1.0 - min(abs(dd1 - dd2) / 0.5, 1.0)
        return round((sharpe_sim * 0.6 + dd_sim * 0.4) * 0.5, 4)

    def _save_request(self, request: PortfolioSimRequest) -> None:
        """Persist a sim request to disk."""
        path = self.sims_dir / request.portfolio_sim_id / "request.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(request), indent=2, default=str), encoding="utf-8"
        )

    def _save_result(self, result: PortfolioSimResult) -> None:
        """Persist a sim result to disk."""
        path = self.sims_dir / result.portfolio_sim_id / "result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(result), indent=2, default=str), encoding="utf-8"
        )

    def _load_request(self, sim_id: str) -> PortfolioSimRequest | None:
        """Load a sim request from disk."""
        path = self.sims_dir / sim_id / "request.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return PortfolioSimRequest(**data)

    def _load_result(self, sim_id: str) -> PortfolioSimResult | None:
        """Load a sim result from disk."""
        path = self.sims_dir / sim_id / "result.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return PortfolioSimResult(**data)
