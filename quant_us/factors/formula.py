"""Generated formula factors for automated research.

Generated factors are persisted as a safe declarative DSL.  The research
engine can combine them and backtest them without executing arbitrary Python
or letting generated strategy logic reach the broker path.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.factors.definition import FactorDefinition, FactorLibrary


@dataclass(frozen=True)
class GeneratedFactorSpec:
    factor_id: str
    name: str
    formula_type: str
    components: list[str]
    weights: list[float] = field(default_factory=list)
    formula: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    category: str = "quality"
    lookback: int = 20
    required_fields: list[str] = field(default_factory=lambda: ["close"])
    winsorize_pct: float = 0.01
    zscore: bool = True
    rank_method: str = "percentile"
    generation_family: str = "generated_formula"
    signature: str = ""
    complexity_score: int = 0
    version: str = "v1"
    created_at: str = field(default_factory=lambda: utc_now().isoformat())

    def to_definition(self) -> FactorDefinition:
        return FactorDefinition(
            factor_id=self.factor_id,
            name=self.name,
            category=self.category,
            lookback=self.lookback,
            formula=self.formula,
            required_fields=list(self.required_fields),
            neutralization="none",
            winsorize_pct=self.winsorize_pct,
            zscore=self.zscore,
            rank_method=self.rank_method,
            version=self.version,
            created_at=self.created_at,
        )


class GeneratedFactorLibrary:
    """Persistent registry for formula factors under ``data/research``."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = Path(data_root)
        self.path = self.data_root / "research" / "generated_factors" / "factors.json"
        self._builtin = FactorLibrary()

    def list_specs(self) -> list[GeneratedFactorSpec]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload.get("factors", payload if isinstance(payload, list) else [])
        return [GeneratedFactorSpec(**dict(item)) for item in items]

    def factor_ids(self) -> list[str]:
        return [spec.factor_id for spec in self.list_specs()]

    def get(self, factor_id: str) -> GeneratedFactorSpec:
        for spec in self.list_specs():
            if spec.factor_id == factor_id:
                return spec
        raise KeyError(f"Unknown generated factor: '{factor_id}'")

    def definition(self, factor_id: str) -> FactorDefinition:
        return self.get(factor_id).to_definition()

    def save_specs(self, specs: list[GeneratedFactorSpec]) -> list[GeneratedFactorSpec]:
        existing = {spec.factor_id: spec for spec in self.list_specs()}
        for spec in specs:
            existing[spec.factor_id] = spec
        ordered = [existing[key] for key in sorted(existing)]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "version": "generated_factor_library_v1",
                    "updated_at": utc_now().isoformat(),
                    "factors": [asdict(spec) for spec in ordered],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return ordered

    def generate_and_register(
        self,
        *,
        seed_factor_ids: list[str] | None = None,
        max_specs: int = 24,
        max_complexity: int = 6,
    ) -> list[GeneratedFactorSpec]:
        specs = generate_candidate_formula_specs(
            seed_factor_ids=seed_factor_ids or self._builtin.factor_ids(),
            max_specs=max_specs,
            max_complexity=max_complexity,
            library=self._builtin,
        )
        self.save_specs(specs)
        return specs


def generate_candidate_formula_specs(
    *,
    seed_factor_ids: list[str],
    max_specs: int = 24,
    max_complexity: int = 6,
    library: FactorLibrary | None = None,
) -> list[GeneratedFactorSpec]:
    """Generate deterministic formula-factor candidates from known primitives."""
    builtin = library or FactorLibrary()
    available = [factor_id for factor_id in _dedupe(seed_factor_ids) if _is_builtin(factor_id, builtin)]
    momentum = [item for item in available if item.startswith("momentum_")]
    risk = [item for item in available if item.startswith("volatility_")]
    liquidity = [item for item in available if item.startswith(("liquidity_", "volume_"))]
    reversal = [item for item in available if item.startswith("reversal_")]

    specs: list[GeneratedFactorSpec] = []
    seen_signatures: set[str] = set()

    def append_spec(spec: GeneratedFactorSpec) -> bool:
        if spec.complexity_score > max_complexity:
            return False
        if spec.signature in seen_signatures:
            return False
        seen_signatures.add(spec.signature)
        specs.append(spec)
        return len(specs) >= max_specs

    for signal in momentum + reversal:
        if append_spec(
            _make_spec(
                formula_type="signed_power",
                components=[signal],
                weights=[1.0],
                formula=f"sign(z({signal})) * abs(z({signal}))^1.5",
                params={"power": 1.5},
                category="trend",
                generation_family="nonlinear_signal",
                library=builtin,
            )
        ):
            return specs[:max_specs]

    for signal in momentum + reversal:
        for risk_factor in risk:
            if append_spec(
                _make_spec(
                    formula_type="linear_combo",
                    components=[signal, risk_factor],
                    weights=[1.0, -0.5],
                    formula=f"z({signal}) - 0.5 * z({risk_factor})",
                    category="trend",
                    generation_family="risk_adjusted_signal",
                    library=builtin,
                )
            ):
                return specs[:max_specs]
            if append_spec(
                _make_spec(
                    formula_type="ratio",
                    components=[signal, risk_factor],
                    weights=[1.0, 1.0],
                    formula=f"z({signal}) / (abs(z({risk_factor})) + 1e-6)",
                    category="quality",
                    generation_family="risk_normalized_signal",
                    library=builtin,
                )
            ):
                return specs[:max_specs]
            if append_spec(
                _make_spec(
                    formula_type="gated_combo",
                    components=[signal, risk_factor],
                    weights=[1.0, 1.0],
                    formula=f"z({signal}) * (1 - tanh(abs(z({risk_factor}))))",
                    params={"gate_scale": 1.0},
                    category="quality",
                    generation_family="risk_gated_signal",
                    library=builtin,
                )
            ):
                return specs[:max_specs]

    for signal in momentum + reversal:
        for flow in liquidity:
            if append_spec(
                _make_spec(
                    formula_type="interaction",
                    components=[signal, flow],
                    weights=[1.0, 1.0],
                    formula=f"z({signal}) * z({flow})",
                    category="quality",
                    generation_family="flow_interaction",
                    library=builtin,
                )
            ):
                return specs[:max_specs]
            if append_spec(
                _make_spec(
                    formula_type="linear_combo",
                    components=[signal, flow],
                    weights=[0.7, 0.3],
                    formula=f"0.7 * z({signal}) + 0.3 * z({flow})",
                    category="trend",
                    generation_family="signal_with_flow",
                    library=builtin,
                )
            ):
                return specs[:max_specs]
            if append_spec(
                _make_spec(
                    formula_type="minmax_spread",
                    components=[signal, flow],
                    weights=[1.0, 1.0],
                    formula=f"max(z({signal}), z({flow})) - min(z({signal}), z({flow}))",
                    category="quality",
                    generation_family="cross_factor_dispersion",
                    library=builtin,
                )
            ):
                return specs[:max_specs]

    for signal in momentum:
        for flow in liquidity:
            for risk_factor in risk:
                if append_spec(
                    _make_spec(
                        formula_type="linear_combo",
                        components=[signal, flow, risk_factor],
                        weights=[0.6, 0.3, -0.4],
                        formula=f"0.6 * z({signal}) + 0.3 * z({flow}) - 0.4 * z({risk_factor})",
                        category="quality",
                        generation_family="tri_factor_blend",
                        library=builtin,
                    )
                ):
                    return specs[:max_specs]
                if append_spec(
                    _make_spec(
                        formula_type="gated_combo",
                        components=[signal, flow, risk_factor],
                        weights=[0.75, 0.25, 1.0],
                        formula=(
                            f"(0.75 * z({signal}) + 0.25 * z({flow})) "
                            f"* (1 - tanh(abs(z({risk_factor}))))"
                        ),
                        params={"gate_scale": 1.0},
                        category="quality",
                        generation_family="tri_factor_risk_gated",
                        library=builtin,
                    )
                ):
                    return specs[:max_specs]

    return specs[:max_specs]


def _make_spec(
    *,
    formula_type: str,
    components: list[str],
    weights: list[float],
    formula: str,
    params: dict[str, Any] | None = None,
    category: str,
    generation_family: str,
    library: FactorLibrary,
) -> GeneratedFactorSpec:
    normalized_components, normalized_weights = _canonical_components_and_weights(
        formula_type=formula_type,
        components=components,
        weights=weights,
    )
    normalized_params = _normalize_params(params or {})
    signature = _signature_for(
        formula_type=formula_type,
        components=normalized_components,
        weights=normalized_weights,
        params=normalized_params,
    )
    suffix = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:10]
    factor_id = f"gf_{formula_type}_{_component_stem(normalized_components)}_{suffix}"
    definitions = [library.get(component) for component in components]
    required_fields = sorted({field for definition in definitions for field in definition.required_fields})
    lookback = max(definition.lookback for definition in definitions)
    label = generation_family.replace("_", " ").title()
    return GeneratedFactorSpec(
        factor_id=factor_id,
        name=f"{label}: {', '.join(_short_component(component) for component in normalized_components)}",
        formula_type=formula_type,
        components=list(normalized_components),
        weights=list(normalized_weights),
        formula=formula,
        params=normalized_params,
        category=category,
        lookback=lookback,
        required_fields=required_fields,
        generation_family=generation_family,
        signature=signature,
        complexity_score=_formula_complexity(
            formula_type=formula_type,
            components=normalized_components,
            params=normalized_params,
        ),
    )


def _short_component(component: str) -> str:
    aliases = {
        "momentum": "mom",
        "volatility": "vol",
        "liquidity": "liq",
        "reversal": "rev",
        "volume": "volume",
    }
    text = component
    for prefix, alias in aliases.items():
        text = text.replace(prefix, alias)
    return re.sub(r"[^a-zA-Z0-9]+", "", text)[:16].lower() or "factor"


def _component_stem(components: list[str]) -> str:
    stems = [_short_component(component) for component in components[:3]]
    if len(components) > 3:
        stems.append(f"x{len(components)}")
    return "_".join(stems)[:48] or "factor"


def _canonical_components_and_weights(
    *,
    formula_type: str,
    components: list[str],
    weights: list[float],
) -> tuple[list[str], list[float]]:
    weights = list(weights or [1.0] * len(components))
    if len(weights) < len(components):
        weights.extend([1.0] * (len(components) - len(weights)))
    paired = [(str(component), float(weight)) for component, weight in zip(components, weights)]
    if formula_type == "linear_combo":
        collapsed: dict[str, float] = {}
        for component, weight in paired:
            collapsed[component] = collapsed.get(component, 0.0) + weight
        ordered = sorted((component, weight) for component, weight in collapsed.items() if abs(weight) > 1e-12)
    elif formula_type in {"interaction", "minmax_spread"}:
        ordered = sorted((component, 1.0) for component, _ in paired)
    else:
        ordered = paired
    normalized_components = [component for component, _ in ordered]
    normalized_weights = [_normalize_float(weight) for _, weight in ordered]
    return normalized_components, normalized_weights


def _normalize_float(value: float) -> float:
    return round(float(value), 8)


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in sorted(params.items()):
        if isinstance(value, float):
            normalized[key] = _normalize_float(value)
        else:
            normalized[key] = value
    return normalized


def _signature_for(
    *,
    formula_type: str,
    components: list[str],
    weights: list[float],
    params: dict[str, Any],
) -> str:
    payload = {
        "dsl_version": "generated_formula_v2",
        "formula_type": formula_type,
        "components": list(components),
        "weights": list(weights),
        "params": dict(params),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _formula_complexity(
    *,
    formula_type: str,
    components: list[str],
    params: dict[str, Any],
) -> int:
    nonlinear_penalty = 0
    if formula_type in {"signed_power", "ratio", "interaction", "minmax_spread"}:
        nonlinear_penalty = 1
    elif formula_type == "gated_combo":
        nonlinear_penalty = 2
    param_penalty = len(params)
    return len(components) + nonlinear_penalty + param_penalty


def _is_builtin(factor_id: str, library: FactorLibrary) -> bool:
    try:
        library.get(factor_id)
    except KeyError:
        return False
    return True


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
