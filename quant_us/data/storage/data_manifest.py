from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quant_us.core.clock import utc_now


PROMOTION_SOURCES = {"yfinance", "alpaca", "sqlite"}
ACCEPTED_ADJUSTMENT_POLICIES = frozenset(
    {
        "raw",
        "split_adjusted",
        "dividend_adjusted",
        "split_dividend_adjusted",
        "total_return",
        "unknown",
        "implicit",
    }
)
ACCEPTED_SURVIVORSHIP_BIAS_RISKS = frozenset({"clean", "prone", "mixed", "unknown"})


@dataclass(frozen=True)
class DataManifest:
    data_version: str
    source: str
    symbol: str
    interval: str
    asset_class: str = "equity"
    timezone: str = "UTC"
    adjustment: str = "raw"
    adjustment_policy: str = ""
    corporate_action_adjustment: str = ""
    start: str = ""
    end: str = ""
    row_count: int = 0
    expected_rows: int = 0
    coverage_pct: float = 0.0
    fingerprint: str = ""
    checksum: str = ""
    quality_score: float = 0.0
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    fields: list[str] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)
    cleaning: dict[str, int] = field(default_factory=dict)
    raw_path: str = ""
    cleaned_path: str = ""
    git_commit: str = ""
    universe_id: str = ""
    universe_source: str = ""
    survivorship_bias_risk: str = "unknown"

    @property
    def is_usable(self) -> bool:
        return self.coverage_pct >= 90.0 and self.quality_score >= 80.0

    @property
    def manifest_id(self) -> str:
        payload = f"{self.source}:{self.symbol}:{self.interval}:{self.start}:{self.end}:{self.row_count}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def effective_checksum(self) -> str:
        return self.checksum or self.fingerprint


@dataclass(frozen=True)
class DataManifestValidation:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class DataManifestStore:
    def __init__(self, root: str | Path = "data/manifests") -> None:
        self.root = Path(root)

    def write(self, manifest: DataManifest) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path_for(manifest)
        payload = _manifest_to_dict(manifest)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def read(self, data_version: str) -> DataManifest | None:
        path = self.root / f"{data_version}.json"
        if not path.exists():
            return None
        if _is_backtest_run_manifest_path(path):
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not _looks_like_data_manifest(data):
            return None
        return _dict_to_manifest(data)

    def read_latest(self, source: str, symbol: str, interval: str) -> DataManifest | None:
        candidates = sorted(self.root.glob(f"qs-{source}-{symbol.upper()}-{interval}-*.json"), reverse=True)
        for path in candidates:
            if _is_backtest_run_manifest_path(path):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if _looks_like_data_manifest(data):
                return _dict_to_manifest(data)
        return None

    def list_manifests(
        self, source: str | None = None, symbol: str | None = None, interval: str | None = None
    ) -> list[DataManifest]:
        results: list[DataManifest] = []
        if not self.root.exists():
            return results
        for path in sorted(self.root.glob("*.json")):
            if _is_backtest_run_manifest_path(path):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not _looks_like_data_manifest(data):
                continue
            manifest = _dict_to_manifest(data)
            if source and manifest.source != source:
                continue
            if symbol and manifest.symbol.upper() != symbol.upper():
                continue
            if interval and manifest.interval != interval:
                continue
            results.append(manifest)
        return results

    def _path_for(self, manifest: DataManifest) -> Path:
        return self.root / f"{manifest.data_version}.json"


def _manifest_to_dict(manifest: DataManifest) -> dict[str, Any]:
    result = asdict(manifest)
    if not result.get("checksum"):
        result["checksum"] = manifest.fingerprint
    policy = _resolve_adjustment_policy(
        manifest.adjustment_policy,
        manifest.corporate_action_adjustment,
        manifest.adjustment,
    )
    result["adjustment_policy"] = policy
    result["corporate_action_adjustment"] = policy
    return result


def _dict_to_manifest(data: dict[str, Any]) -> DataManifest:
    adjustment = str(data.get("adjustment", "raw"))
    adjustment_policy = _resolve_adjustment_policy(
        data.get("adjustment_policy"),
        data.get("corporate_action_adjustment"),
        adjustment,
    )
    return DataManifest(
        data_version=str(data.get("data_version", "")),
        source=str(data.get("source", "")),
        symbol=str(data.get("symbol", "")),
        interval=str(data.get("interval", "")),
        asset_class=str(data.get("asset_class", "equity")),
        timezone=str(data.get("timezone", "UTC")),
        adjustment=adjustment,
        adjustment_policy=adjustment_policy,
        corporate_action_adjustment=adjustment_policy,
        start=str(data.get("start", "")),
        end=str(data.get("end", "")),
        row_count=int(data.get("row_count", 0)),
        expected_rows=int(data.get("expected_rows", 0)),
        coverage_pct=float(data.get("coverage_pct", 0.0)),
        fingerprint=str(data.get("fingerprint", "")),
        checksum=str(data.get("checksum", data.get("fingerprint", ""))),
        quality_score=float(data.get("quality_score", 0.0)),
        created_at=str(data.get("created_at", "")),
        fields=[str(f) for f in data.get("fields", [])],
        issues=[dict(item) for item in data.get("issues", [])],
        cleaning={str(k): int(v) for k, v in data.get("cleaning", {}).items()},
        raw_path=str(data.get("raw_path", "")),
        cleaned_path=str(data.get("cleaned_path", "")),
        git_commit=str(data.get("git_commit", "")),
        universe_id=str(data.get("universe_id", "")),
        universe_source=str(data.get("universe_source", "")),
        survivorship_bias_risk=_normalize_survivorship_bias_risk(data.get("survivorship_bias_risk")),
    )


def _is_backtest_run_manifest_path(path: Path) -> bool:
    return path.suffix == ".json" and path.stem.startswith("run_")


def _looks_like_data_manifest(data: dict[str, Any]) -> bool:
    return all(data.get(key) for key in ("data_version", "source", "symbol", "interval"))


def _safe_get(quality: dict[str, Any], key: str, default: Any) -> Any:
    """Return quality[key] if present and not None, otherwise default."""
    val = quality.get(key)
    return val if val is not None else default


def build_manifest_from_quality(
    quality: dict[str, Any],
    source: str,
    symbol: str,
    interval: str,
    asset_class: str = "equity",
    timezone_name: str = "UTC",
    adjustment: str = "raw",
    adjustment_policy: str = "",
    raw_path: str = "",
    cleaned_path: str = "",
    git_commit: str = "",
    universe_id: str = "",
    universe_source: str = "",
    survivorship_bias_risk: str = "unknown",
) -> DataManifest:
    fingerprint = str(_safe_get(quality, "fingerprint", ""))
    normalized_adjustment_policy = _resolve_adjustment_policy(
        adjustment_policy,
        quality.get("corporate_action_adjustment"),
        adjustment,
    )
    return DataManifest(
        data_version=str(_safe_get(quality, "data_version", "")),
        source=str(_safe_get(quality, "actual_source", source)),
        symbol=symbol.upper(),
        interval=interval,
        asset_class=asset_class,
        timezone=timezone_name,
        adjustment=adjustment,
        adjustment_policy=normalized_adjustment_policy,
        corporate_action_adjustment=normalized_adjustment_policy,
        start=str(_safe_get(quality, "first_timestamp", "")),
        end=str(_safe_get(quality, "last_timestamp", "")),
        row_count=int(_safe_get(quality, "row_count", 0)),
        expected_rows=int(_safe_get(quality, "expected_rows", 0)),
        coverage_pct=float(_safe_get(quality, "coverage_pct", 0.0)),
        fingerprint=fingerprint,
        checksum=fingerprint,
        quality_score=float(_safe_get(quality, "quality_score", 0.0)),
        created_at=utc_now().isoformat(),
        fields=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"],
        issues=[dict(item) for item in _safe_get(quality, "issues", [])],
        cleaning={
            "duplicate_timestamps_removed": int(_safe_get(quality, "duplicate_timestamps", 0)),
            "invalid_ohlc_removed": int(_safe_get(quality, "invalid_ohlc", 0)),
            "non_positive_prices_removed": int(_safe_get(quality, "non_positive_prices", 0)),
            "cleaning_loss_rows": int(_safe_get(quality, "cleaning_loss_rows", 0)),
            "missing_bars": int(_safe_get(quality, "missing_bars", 0)),
        },
        raw_path=raw_path,
        cleaned_path=cleaned_path,
        git_commit=git_commit,
        universe_id=universe_id,
        universe_source=universe_source,
        survivorship_bias_risk=_normalize_survivorship_bias_risk(survivorship_bias_risk),
    )


def validate_manifest_for_promotion(
    manifest: DataManifest,
    *,
    now: datetime | None = None,
    allow_sources: set[str] | None = None,
    min_coverage_pct: float = 90.0,
    min_quality_score: float = 80.0,
) -> DataManifestValidation:
    reasons: list[str] = []
    warnings: list[str] = []
    sources = allow_sources or PROMOTION_SOURCES
    timestamp_now = now or utc_now()
    if timestamp_now.tzinfo is None:
        timestamp_now = timestamp_now.replace(tzinfo=timezone.utc)

    source = manifest.source.lower()
    asset_class = manifest.asset_class.lower()
    adjustment_policy = _resolve_adjustment_policy(
        manifest.adjustment_policy,
        manifest.corporate_action_adjustment,
        manifest.adjustment,
    )
    survivorship_bias_risk = _normalize_survivorship_bias_risk(manifest.survivorship_bias_risk)
    if not manifest.data_version:
        reasons.append("missing_data_version")
    if source == "fixture":
        reasons.append("fixture_data_not_allowed")
    if source not in sources:
        reasons.append(f"unsupported_data_source:{source or 'unknown'}")
    if asset_class != "equity":
        reasons.append(f"asset_class_not_allowed:{asset_class or 'unknown'}")
    if not manifest.effective_checksum:
        reasons.append("missing_checksum")
    if manifest.row_count <= 0:
        reasons.append("empty_dataset")
    if manifest.coverage_pct < min_coverage_pct:
        reasons.append(f"coverage_below_threshold:{manifest.coverage_pct:.2f}")
    if manifest.quality_score < min_quality_score:
        reasons.append(f"quality_below_threshold:{manifest.quality_score:.2f}")
    if manifest.timezone.upper() != "UTC":
        reasons.append(f"timezone_not_utc:{manifest.timezone}")
    if not manifest.universe_id:
        warnings.append("universe_id_missing")
    if not manifest.universe_source:
        warnings.append("universe_source_missing")
    if survivorship_bias_risk == "unknown":
        warnings.append("survivorship_bias_risk_unmarked")
    elif survivorship_bias_risk in {"prone", "mixed"}:
        warnings.append(f"survivorship_bias_risk:{survivorship_bias_risk}")
    if adjustment_policy in {"unknown", "implicit"}:
        warnings.append(f"adjustment_policy:{adjustment_policy}")

    duplicate_count = int(manifest.cleaning.get("duplicate_timestamps_removed", 0))
    invalid_ohlc = int(manifest.cleaning.get("invalid_ohlc_removed", 0))
    non_positive = int(manifest.cleaning.get("non_positive_prices_removed", 0))
    missing_bars = int(manifest.cleaning.get("missing_bars", 0))
    if duplicate_count > 0:
        reasons.append(f"duplicate_timestamps:{duplicate_count}")
    if invalid_ohlc > 0:
        reasons.append(f"invalid_ohlc:{invalid_ohlc}")
    if non_positive > 0:
        reasons.append(f"non_positive_prices:{non_positive}")
    if missing_bars > 0:
        warnings.append(f"missing_bars:{missing_bars}")

    parsed_end = _parse_manifest_datetime(manifest.end)
    if parsed_end and parsed_end > timestamp_now + timedelta(minutes=1):
        reasons.append(f"future_timestamp:{parsed_end.isoformat()}")

    return DataManifestValidation(
        ok=not reasons,
        reasons=reasons,
        warnings=warnings,
        metrics={
            "data_version": manifest.data_version,
            "source": manifest.source,
            "symbol": manifest.symbol,
            "interval": manifest.interval,
            "asset_class": manifest.asset_class,
            "universe_id": manifest.universe_id,
            "universe_source": manifest.universe_source,
            "survivorship_bias_risk": survivorship_bias_risk,
            "adjustment_policy": adjustment_policy,
            "coverage_pct": manifest.coverage_pct,
            "quality_score": manifest.quality_score,
            "row_count": manifest.row_count,
            "expected_rows": manifest.expected_rows,
            "checksum": manifest.effective_checksum,
        },
    )


def _parse_manifest_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_adjustment_policy(*values: Any) -> str:
    for value in values:
        normalized = _normalize_adjustment_policy(value)
        if normalized != "implicit":
            return normalized
    return "implicit"


def _normalize_adjustment_policy(value: Any) -> str:
    if value is None:
        return "implicit"
    text = str(value).strip().lower()
    if not text:
        return "implicit"
    aliases = {
        "none": "raw",
        "unadjusted": "raw",
        "split_and_dividend_adjusted": "split_dividend_adjusted",
        "split+dividend_adjusted": "split_dividend_adjusted",
        "fully_adjusted": "split_dividend_adjusted",
        "adjusted": "split_dividend_adjusted",
    }
    normalized = aliases.get(text, text)
    if normalized in ACCEPTED_ADJUSTMENT_POLICIES:
        return normalized
    return "unknown"


def _normalize_survivorship_bias_risk(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    if text in ACCEPTED_SURVIVORSHIP_BIAS_RISKS:
        return text
    return "unknown"


validate_data_manifest_for_promotion = validate_manifest_for_promotion
