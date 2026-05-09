"""Factor definition schema and registry.

Provides FactorDefinition (the metadata schema for a computable factor)
and FactorLibrary (the registry that enumerates all known factors).

Usage:
    lib = FactorLibrary()
    mom = lib.get("momentum_60d")
    for f in lib.list_by_category("volatility"):
        print(f.factor_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field

FACTOR_CATEGORIES = [
    "momentum",
    "reversal",
    "volatility",
    "liquidity",
    "volume",
    "trend",
    "quality",
    "macro",
]

_VALID_NEUTRALIZATIONS = {"none", "sector", "size"}
_VALID_RANK_METHODS = {"percentile", "zscore", "raw"}


@dataclass
class FactorDefinition:
    """Metadata for a single computable factor.

    Attributes:
        factor_id: Unique identifier (e.g. ``"momentum_60d"``).
        name: Human-readable display name.
        category: One of FACTOR_CATEGORIES.
        lookback: Maximum lookback window in days needed for computation.
        formula: Short mathematical description of the formula.
        required_fields: OHLCV fields the factor needs (e.g. ``["close"]``).
        neutralization: Cross-sectional adjustment — ``"none"``, ``"sector"``, or ``"size"``.
        winsorize_pct: Fraction to winsorize at each tail before z-score.
        zscore: Whether to z-score standardize the cross-section.
        rank_method: ``"percentile"``, ``"zscore"``, or ``"raw"`` output.
        version: Version string for the factor definition (default ``"v1"``).
        created_at: ISO-8601 timestamp of when this definition was created.
    """

    factor_id: str
    name: str
    category: str
    lookback: int = 20
    formula: str = ""
    required_fields: list[str] = field(default_factory=lambda: ["close"])
    neutralization: str = "none"
    winsorize_pct: float = 0.01
    zscore: bool = True
    rank_method: str = "percentile"
    version: str = "v1"
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.category not in FACTOR_CATEGORIES:
            raise ValueError(
                f"Unknown category '{self.category}'. "
                f"Valid: {', '.join(FACTOR_CATEGORIES)}"
            )
        if self.neutralization not in _VALID_NEUTRALIZATIONS:
            raise ValueError(
                f"Invalid neutralization '{self.neutralization}'. "
                f"Valid: {', '.join(_VALID_NEUTRALIZATIONS)}"
            )
        if self.rank_method not in _VALID_RANK_METHODS:
            raise ValueError(
                f"Invalid rank_method '{self.rank_method}'. "
                f"Valid: {', '.join(_VALID_RANK_METHODS)}"
            )


class FactorLibrary:
    """Registry of defined factors.

    Built-in factors are registered automatically on construction.
    Callers can also register custom factors at runtime.
    """

    def __init__(self) -> None:
        self._registry: dict[str, FactorDefinition] = {}
        self._register_defaults()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, factor: FactorDefinition, version: str | None = None) -> None:
        """Register a factor definition. Overwrites if already exists.

        If *version* is provided, it overrides the ``version`` field
        on the factor before registration.
        """
        if version is not None:
            factor.version = version
        self._registry[factor.factor_id] = factor

    def get(self, factor_id: str) -> FactorDefinition:
        """Return a single factor definition. Raises KeyError if missing."""
        if factor_id not in self._registry:
            raise KeyError(f"Unknown factor: '{factor_id}'")
        return self._registry[factor_id]

    def list_by_category(self, category: str) -> list[FactorDefinition]:
        """Return all factors belonging to *category*."""
        return [f for f in self._registry.values() if f.category == category]

    def list_all(self) -> list[FactorDefinition]:
        """Return every registered factor definition."""
        return list(self._registry.values())

    def factor_ids(self) -> list[str]:
        """Return all registered factor IDs."""
        return list(self._registry.keys())

    # ------------------------------------------------------------------
    # Built-in factor registration
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        builtins = [
            FactorDefinition(
                factor_id="momentum_60d",
                name="60-Day Momentum",
                category="momentum",
                lookback=60,
                formula="(roc(20) + roc(60)) / 2",
                required_fields=["close"],
                neutralization="sector",
            ),
            FactorDefinition(
                factor_id="momentum_20d",
                name="20-Day Momentum",
                category="momentum",
                lookback=20,
                formula="roc(20)",
                required_fields=["close"],
                neutralization="sector",
            ),
            FactorDefinition(
                factor_id="momentum_120d",
                name="120-Day Momentum",
                category="momentum",
                lookback=120,
                formula="(roc(20) + roc(60) + roc(120)) / 3",
                required_fields=["close"],
                neutralization="sector",
            ),
            FactorDefinition(
                factor_id="volatility_20d",
                name="20-Day Realized Volatility",
                category="volatility",
                lookback=20,
                formula="std(pct_return, 20) * sqrt(252)",
                required_fields=["close"],
                neutralization="none",
            ),
            FactorDefinition(
                factor_id="volatility_60d",
                name="60-Day Realized Volatility",
                category="volatility",
                lookback=60,
                formula="std(pct_return, 60) * sqrt(252)",
                required_fields=["close"],
                neutralization="none",
            ),
            FactorDefinition(
                factor_id="liquidity_20d",
                name="20-Day Average Dollar Volume",
                category="liquidity",
                lookback=20,
                formula="avg(close * volume, 20)",
                required_fields=["close", "volume"],
                neutralization="none",
                zscore=False,
                rank_method="percentile",
            ),
            FactorDefinition(
                factor_id="reversal_1d",
                name="1-Day Reversal (short-term reversal)",
                category="reversal",
                lookback=1,
                formula="-roc(1)",
                required_fields=["close"],
                neutralization="sector",
            ),
            FactorDefinition(
                factor_id="volume_20d",
                name="20-Day Volume Trend",
                category="volume",
                lookback=20,
                formula="avg(volume, 20) / avg(volume, 60)",
                required_fields=["volume"],
                neutralization="none",
                zscore=False,
                rank_method="percentile",
            ),
        ]
        for f in builtins:
            self._registry[f.factor_id] = f
