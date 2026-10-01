from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math


class FactoryError(ValueError):
    pass


SAFETY = {key: False for key in (
    "promotion", "paper", "live", "private", "order", "real_order", "transfer",
    "withdraw", "execution_permission", "runtime_observed")}
STAGES = ("data", "generate", "evaluate", "train", "screen", "nominate")
REAL_ACCEPTANCE_PROFILE = "btc_real_candidate_offline_20260930_v1"
REAL_ACCEPTANCE_PRIMITIVES = (
    "momentum_20d", "momentum_60d", "momentum_120d", "volatility_20d",
    "volatility_60d", "liquidity_20d", "reversal_1d", "volume_20d",
)
REAL_ACCEPTANCE_FIT_LIMIT = 5
UNARY = ("clip", "tanh", "sign", "rolling_z", "signed_power")
BINARY = ("add", "sub", "mul", "safe_ratio", "gate")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def validate_expression(node: dict, primitives: set[str], *, depth=1) -> int:
    """Bounded JSON AST; never execute supplied Python, import paths or Qlib code."""
    if not isinstance(node, dict) or depth > 4:
        raise FactoryError("expression_depth_or_type_invalid")
    if set(node) - {"op", "args", "primitive", "value", "window"}:
        raise FactoryError("expression_unknown_field")
    op = node.get("op")
    args = node.get("args", [])
    if not isinstance(args, list):
        raise FactoryError("expression_args_invalid")
    if op == "primitive":
        if node.get("primitive") not in primitives or args:
            raise FactoryError("primitive_unavailable:" + str(node.get("primitive")))
    elif op == "const":
        value = node.get("value")
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or abs(value) > 10 or args:
            raise FactoryError("constant_invalid")
    elif op in UNARY + BINARY:
        if len(args) != (1 if op in UNARY else 2):
            raise FactoryError("expression_arity_invalid")
        if op == "rolling_z" and (type(node.get("window")) is not int or not 2 <= node["window"] <= 120):
            raise FactoryError("rolling_window_invalid")
    else:
        raise FactoryError("expression_operator_not_allowed:" + str(op))
    size = 1 + sum(validate_expression(child, primitives, depth=depth + 1) for child in args)
    if size > 15:
        raise FactoryError("expression_complexity_exceeded")
    return size


@dataclass(frozen=True)
class FactorSpec:
    expression: dict
    origin: str
    name: str
    provenance: dict = field(default_factory=dict)

    @property
    def factor_id(self) -> str:
        return "af_" + digest(self.expression)[:20]

    def to_dict(self):
        return {**asdict(self), "factor_id": self.factor_id, "expression_hash": digest(self.expression)}


def validate_budget(request: dict) -> dict:
    allowed = {"profile_id", "run_id", "seed", "population", "generations", "max_features", "model_trials", "generators",
        "acceptance_profile"}
    if not isinstance(request, dict) or set(request) - allowed:
        raise FactoryError("factory_request_unknown_field_or_permission_override")
    result = dict(request)
    for key, default, low, high in (("seed", 17, 0, 2147483647), ("population", 12, 4, 32),
        ("generations", 2, 1, 4), ("max_features", 6, 1, 12), ("model_trials", 2, 1, 3)):
        value = request.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise FactoryError("budget_out_of_bounds:" + key)
        result[key] = value
    generators = request.get("generators", ["registered", "template", "genetic"])
    if not isinstance(generators, list) or not generators or any(not isinstance(x, str) for x in generators):
        raise FactoryError("invalid_generators")
    if len(set(generators)) != len(generators) or any(item not in {"registered", "template", "genetic"} for item in generators):
        raise FactoryError("invalid_generators")
    result["generators"] = generators
    acceptance = request.get("acceptance_profile")
    if acceptance is not None:
        if acceptance != REAL_ACCEPTANCE_PROFILE or request.get("profile_id") != "okx_btc_trend_1h":
            raise FactoryError("factory_acceptance_profile_invalid")
        fixed = {"seed": 17, "max_features": 6, "model_trials": 1, "generators": ["registered"]}
        for key, value in fixed.items():
            if key in request and request[key] != value:
                raise FactoryError("factory_acceptance_fixed_budget_mismatch:" + key)
            result[key] = value
        result["acceptance_profile"] = acceptance
    return result
