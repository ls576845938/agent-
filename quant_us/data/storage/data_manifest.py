from __future__ import annotations

import hashlib
import json
import re
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
    quality_summary: dict[str, int] = field(default_factory=dict)
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
        candidates: list[tuple[tuple[float, float, str], DataManifest]] = []
        paths = sorted(self.root.glob(f"qs-{source}-{symbol.upper()}-{interval}-*.json"))
        for path in paths:
            if _is_backtest_run_manifest_path(path):
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if _looks_like_data_manifest(data):
                manifest = _dict_to_manifest(data)
                candidates.append((_latest_manifest_sort_key(path, manifest), manifest))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

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
    result["quality_summary"] = _normalize_quality_summary(
        result.get("quality_summary"),
        issues=manifest.issues,
        cleaning=manifest.cleaning,
    )
    return result


def _dict_to_manifest(data: dict[str, Any]) -> DataManifest:
    adjustment = str(data.get("adjustment", "raw"))
    issues = [dict(item) for item in data.get("issues", [])]
    cleaning = {str(k): int(v) for k, v in data.get("cleaning", {}).items()}
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
        issues=issues,
        cleaning=cleaning,
        quality_summary=_normalize_quality_summary(
            data.get("quality_summary"),
            issues=issues,
            cleaning=cleaning,
        ),
        raw_path=str(data.get("raw_path", "")),
        cleaned_path=str(data.get("cleaned_path", "")),
        git_commit=str(data.get("git_commit", "")),
        universe_id=str(data.get("universe_id", "")),
        universe_source=str(data.get("universe_source", "")),
        survivorship_bias_risk=_normalize_survivorship_bias_risk(data.get("survivorship_bias_risk")),
    )


def _is_backtest_run_manifest_path(path: Path) -> bool:
    return path.suffix == ".json" and path.stem.startswith("run_")


def _latest_manifest_sort_key(path: Path, manifest: DataManifest) -> tuple[float, float, str]:
    created_at_ts = 0.0
    if manifest.created_at:
        try:
            created_at_ts = datetime.fromisoformat(manifest.created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            created_at_ts = 0.0
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return created_at_ts, mtime, manifest.data_version


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
    requested_start: str = "",
    requested_end: str = "",
    universe_id: str = "",
    universe_source: str = "",
    survivorship_bias_risk: str = "unknown",
) -> DataManifest:
    fingerprint = str(_safe_get(quality, "fingerprint", ""))
    resolved_source = str(_safe_get(quality, "actual_source", source))
    resolved_symbol = symbol.upper()
    resolved_start = str(_safe_get(quality, "first_timestamp", requested_start))
    resolved_end = str(_safe_get(quality, "last_timestamp", requested_end))
    resolved_timezone = _resolve_text_field(timezone_name, quality.get("timezone"), default="UTC")
    resolved_raw_path = _resolve_text_field(raw_path, quality.get("raw_path"))
    resolved_cleaned_path = _resolve_text_field(cleaned_path, quality.get("cleaned_path"))
    normalized_adjustment_policy = _resolve_adjustment_policy(
        adjustment_policy,
        quality.get("adjustment_policy"),
        quality.get("corporate_action_adjustment"),
        adjustment,
        _default_adjustment_policy_for_source(resolved_source),
    )
    resolved_universe_id, resolved_universe_source, resolved_survivorship_bias_risk = _resolve_lineage_metadata(
        source=resolved_source,
        symbol=resolved_symbol,
        interval=interval,
        start=resolved_start,
        end=resolved_end,
        universe_id=universe_id,
        universe_source=universe_source,
        survivorship_bias_risk=survivorship_bias_risk,
        quality_universe_id=quality.get("universe_id"),
        quality_universe_source=quality.get("universe_source"),
        quality_survivorship_bias_risk=quality.get("survivorship_bias_risk"),
    )
    issues = [dict(item) for item in _safe_get(quality, "issues", [])]
    cleaning = {
        "duplicate_timestamps_removed": int(_safe_get(quality, "duplicate_timestamps", 0)),
        "invalid_ohlc_removed": int(_safe_get(quality, "invalid_ohlc", 0)),
        "non_positive_prices_removed": int(_safe_get(quality, "non_positive_prices", 0)),
        "cleaning_loss_rows": int(_safe_get(quality, "cleaning_loss_rows", 0)),
        "missing_bars": int(_safe_get(quality, "missing_bars", 0)),
    }
    return DataManifest(
        data_version=str(_safe_get(quality, "data_version", "")),
        source=resolved_source,
        symbol=resolved_symbol,
        interval=interval,
        asset_class=asset_class,
        timezone=resolved_timezone,
        adjustment=adjustment,
        adjustment_policy=normalized_adjustment_policy,
        corporate_action_adjustment=normalized_adjustment_policy,
        start=resolved_start,
        end=resolved_end,
        row_count=int(_safe_get(quality, "row_count", 0)),
        expected_rows=int(_safe_get(quality, "expected_rows", 0)),
        coverage_pct=float(_safe_get(quality, "coverage_pct", 0.0)),
        fingerprint=fingerprint,
        checksum=fingerprint,
        quality_score=float(_safe_get(quality, "quality_score", 0.0)),
        created_at=utc_now().isoformat(),
        fields=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"],
        issues=issues,
        cleaning=cleaning,
        quality_summary=_normalize_quality_summary(
            quality.get("quality_summary"),
            issues=issues,
            cleaning=cleaning,
        ),
        raw_path=resolved_raw_path,
        cleaned_path=resolved_cleaned_path,
        git_commit=git_commit,
        universe_id=resolved_universe_id,
        universe_source=resolved_universe_source,
        survivorship_bias_risk=resolved_survivorship_bias_risk,
    )


def validate_manifest_for_promotion(
    manifest: DataManifest,
    *,
    now: datetime | None = None,
    allow_sources: set[str] | None = None,
    allow_asset_classes: set[str] | None = None,
    min_coverage_pct: float = 90.0,
    min_quality_score: float = 80.0,
    strict: bool = False,
) -> DataManifestValidation:
    reasons: list[str] = []
    warnings: list[str] = []
    sources = allow_sources or PROMOTION_SOURCES
    asset_classes = allow_asset_classes or {"equity"}
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
    quality_summary = _normalize_quality_summary(
        manifest.quality_summary,
        issues=manifest.issues,
        cleaning=manifest.cleaning,
    )
    if not manifest.data_version:
        reasons.append("missing_data_version")
    if not manifest.source:
        reasons.append("missing_data_source")
    if not manifest.symbol:
        reasons.append("missing_symbol")
    if not manifest.interval:
        reasons.append("missing_interval")
    if source == "fixture":
        reasons.append("fixture_data_not_allowed")
    if source not in sources:
        reasons.append(f"unsupported_data_source:{source or 'unknown'}")
    if asset_class not in asset_classes:
        reasons.append(f"asset_class_not_allowed:{asset_class or 'unknown'}")
    if not manifest.fingerprint:
        reasons.append("missing_fingerprint")
    if not manifest.checksum:
        reasons.append("missing_checksum")
    if manifest.fingerprint and manifest.checksum and manifest.fingerprint != manifest.checksum:
        reasons.append("checksum_mismatch")
    if manifest.row_count <= 0:
        reasons.append("empty_dataset")
    if manifest.coverage_pct < min_coverage_pct:
        reasons.append(f"coverage_below_threshold:{manifest.coverage_pct:.2f}")
    if manifest.quality_score < min_quality_score:
        reasons.append(f"quality_below_threshold:{manifest.quality_score:.2f}")
    if manifest.timezone.upper() != "UTC":
        reasons.append(f"timezone_not_utc:{manifest.timezone}")
    if not manifest.universe_id:
        if strict:
            reasons.append("universe_id_missing")
        else:
            warnings.append("universe_id_missing")
    if not manifest.universe_source:
        if strict:
            reasons.append("universe_source_missing")
        else:
            warnings.append("universe_source_missing")
    if survivorship_bias_risk == "unknown":
        if strict:
            reasons.append("survivorship_bias_risk_unmarked")
        else:
            warnings.append("survivorship_bias_risk_unmarked")
    elif survivorship_bias_risk in {"prone", "mixed"}:
        warnings.append(f"survivorship_bias_risk:{survivorship_bias_risk}")
    if adjustment_policy in {"unknown", "implicit"}:
        if strict:
            reasons.append(f"adjustment_policy:{adjustment_policy}")
        else:
            warnings.append(f"adjustment_policy:{adjustment_policy}")

    duplicate_count = max(
        int(manifest.cleaning.get("duplicate_timestamps_removed", 0)),
        int(quality_summary.get("duplicate_bars", 0)),
    )
    invalid_ohlc = max(
        int(manifest.cleaning.get("invalid_ohlc_removed", 0)),
        int(quality_summary.get("invalid_ohlc_rows", 0)),
    )
    non_positive = max(
        int(manifest.cleaning.get("non_positive_prices_removed", 0)),
        int(quality_summary.get("non_positive_price_rows", 0)),
    )
    missing_bars = max(
        int(manifest.cleaning.get("missing_bars", 0)),
        int(quality_summary.get("missing_bars", 0)),
    )
    zero_volume = int(quality_summary.get("zero_volume_bars", 0))
    if duplicate_count > 0:
        reasons.append(f"duplicate_timestamps:{duplicate_count}")
    if invalid_ohlc > 0:
        reasons.append(f"invalid_ohlc:{invalid_ohlc}")
    if non_positive > 0:
        reasons.append(f"non_positive_prices:{non_positive}")
    if missing_bars > 0:
        if strict:
            reasons.append(f"missing_bars:{missing_bars}")
        else:
            warnings.append(f"missing_bars:{missing_bars}")
    if zero_volume > 0:
        if strict:
            reasons.append(f"zero_volume_bars:{zero_volume}")
        else:
            warnings.append(f"zero_volume_bars:{zero_volume}")

    parsed_start = _parse_manifest_datetime(manifest.start)
    parsed_end = _parse_manifest_datetime(manifest.end)
    if not parsed_start:
        reasons.append("invalid_start_timestamp")
    if not parsed_end:
        reasons.append("invalid_end_timestamp")
    if parsed_start and parsed_end and parsed_start > parsed_end:
        reasons.append("invalid_time_range")
    if parsed_start and parsed_start > timestamp_now + timedelta(minutes=1):
        reasons.append(f"future_timestamp:{parsed_start.isoformat()}")
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
            "quality_summary": quality_summary,
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


def _default_adjustment_policy_for_source(source: str) -> str:
    defaults = {
        "alpaca": "raw",
        "fixture": "raw",
        "sqlite": "raw",
        "yfinance": "raw",
    }
    return defaults.get(str(source or "").strip().lower(), "")


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


def _resolve_lineage_metadata(
    *,
    source: str,
    symbol: str,
    interval: str,
    start: str,
    end: str,
    universe_id: str,
    universe_source: str,
    survivorship_bias_risk: str,
    quality_universe_id: Any = "",
    quality_universe_source: Any = "",
    quality_survivorship_bias_risk: Any = "unknown",
) -> tuple[str, str, str]:
    resolved_universe_id = str(universe_id or quality_universe_id or "").strip()
    resolved_universe_source = str(universe_source or quality_universe_source or "").strip()
    resolved_survivorship_bias_risk = _normalize_survivorship_bias_risk(survivorship_bias_risk)
    if resolved_survivorship_bias_risk == "unknown":
        resolved_survivorship_bias_risk = _normalize_survivorship_bias_risk(quality_survivorship_bias_risk)
    auto_universe_id, auto_universe_source, auto_survivorship_bias_risk = _infer_single_symbol_lineage(
        source=source,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
    )
    if not resolved_universe_id:
        resolved_universe_id = auto_universe_id
    if not resolved_universe_source:
        resolved_universe_source = auto_universe_source
    if resolved_survivorship_bias_risk == "unknown":
        resolved_survivorship_bias_risk = auto_survivorship_bias_risk
    return resolved_universe_id, resolved_universe_source, resolved_survivorship_bias_risk


def _infer_single_symbol_lineage(
    *,
    source: str,
    symbol: str,
    interval: str,
    start: str,
    end: str,
) -> tuple[str, str, str]:
    normalized_source = str(source or "").strip().lower()
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_interval = str(interval or "").strip().lower()
    normalized_start = _normalize_lineage_timestamp(start)
    normalized_end = _normalize_lineage_timestamp(end)
    if not (
        normalized_source
        and _is_explicit_single_symbol(normalized_symbol)
        and normalized_interval
        and normalized_start
        and normalized_end
    ):
        return "", "", "unknown"
    payload = ":".join(
        [
            normalized_source,
            normalized_symbol,
            normalized_interval,
            normalized_start,
            normalized_end,
        ]
    )
    lineage_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return (
        f"single-symbol-{normalized_symbol}-{normalized_interval}-{lineage_hash}",
        (
            "auto_lineage:single_symbol_request:v1:"
            f"{normalized_source}:{normalized_symbol}:{normalized_interval}:{normalized_start}:{normalized_end}"
        ),
        "clean",
    )


def _is_explicit_single_symbol(symbol: str) -> bool:
    if not symbol or symbol in {"*", "ALL"}:
        return False
    return re.fullmatch(r"[A-Z0-9._-]+", symbol) is not None


def _normalize_lineage_timestamp(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = _parse_manifest_datetime(text)
    if parsed is not None:
        if parsed.time() == datetime.min.time():
            return parsed.date().isoformat()
        return parsed.isoformat().replace("+00:00", "Z")
    return ""


def _resolve_text_field(primary: Any, secondary: Any, *, default: str = "") -> str:
    primary_text = str(primary or "").strip()
    if primary_text and primary_text != default:
        return primary_text
    secondary_text = str(secondary or "").strip()
    if secondary_text:
        return secondary_text
    if primary_text:
        return primary_text
    return default


def _normalize_quality_summary(
    value: Any,
    *,
    issues: list[dict[str, Any]] | None = None,
    cleaning: dict[str, Any] | None = None,
) -> dict[str, int]:
    base = _build_quality_summary(issues=issues or [], cleaning=cleaning or {})
    if not isinstance(value, dict):
        return base
    for key in base:
        if key in value:
            base[key] = _coerce_non_negative_int(value.get(key))
    return base


def _build_quality_summary(
    *,
    issues: list[dict[str, Any]],
    cleaning: dict[str, Any],
) -> dict[str, int]:
    issue_counts = _issue_counts_by_type(issues)
    duplicate_removed = _coerce_non_negative_int(cleaning.get("duplicate_timestamps_removed", 0))
    invalid_ohlc_removed = _coerce_non_negative_int(cleaning.get("invalid_ohlc_removed", 0))
    non_positive_removed = _coerce_non_negative_int(cleaning.get("non_positive_prices_removed", 0))
    cleaning_loss_rows = _coerce_non_negative_int(cleaning.get("cleaning_loss_rows", 0))
    missing_bars = max(
        _coerce_non_negative_int(cleaning.get("missing_bars", 0)),
        issue_counts.get("missing_bars", 0),
    )
    duplicate_bars = max(duplicate_removed, issue_counts.get("duplicate_bars", 0))
    return {
        "missing_bars": missing_bars,
        "duplicate_bars": duplicate_bars,
        "price_jump_bars": issue_counts.get("price_jump", 0),
        "zero_volume_bars": issue_counts.get("zero_volume", 0),
        "corporate_action_flags": issue_counts.get("corporate_action", 0),
        "invalid_ohlc_rows": invalid_ohlc_removed,
        "non_positive_price_rows": non_positive_removed,
        "duplicate_timestamps_removed": duplicate_removed,
        "cleaning_loss_rows": cleaning_loss_rows,
        "total_issue_count": sum(issue_counts.values()),
    }


def _issue_counts_by_type(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in issues:
        report_type = str(item.get("report_type", "")).strip().lower()
        if not report_type:
            continue
        counts[report_type] = counts.get(report_type, 0) + _coerce_non_negative_int(item.get("issues_found", 0))
    return counts


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


validate_data_manifest_for_promotion = validate_manifest_for_promotion
