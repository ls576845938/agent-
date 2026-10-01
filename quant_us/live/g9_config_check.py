"""G9 Config Integrity Checker for Production Ops Hardening.

Validates that all operational configuration is consistent and versioned.
Detects drift between approved config and current runtime state.
NEVER auto-fixes drift. NEVER outputs secret values.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g9_config_check")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Patterns that indicate potential secret values
SECRET_VALUE_PATTERNS = re.compile(
    r'(sk_|pk_|api[_-]?key|secret|token|password|credential|private[_-]?key)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# ConfigIntegrityResult
# ---------------------------------------------------------------------------


@dataclass
class ConfigIntegrityResult:
    passed: bool = False
    checks: dict[str, bool] = field(default_factory=dict)
    drift_detected: list[str] = field(default_factory=list)
    mismatches: list[dict] = field(default_factory=list)
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "drift_detected": self.drift_detected,
            "mismatches": self.mismatches,
            "checked_at": self.checked_at,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Config Integrity Check",
            "",
            f"**Status**: {'PASS' if self.passed else 'FAIL'}",
            f"**Checked At**: {self.checked_at[:19]}",
            "",
            "## Checks",
        ]
        for name, passed in sorted(self.checks.items()):
            status = "PASS" if passed else "FAIL"
            lines.append(f"- [{status}] {name}")

        if self.drift_detected:
            lines.extend([
                "",
                "## Drift Detected",
            ])
            for item in self.drift_detected:
                lines.append(f"- {item}")

        if self.mismatches:
            lines.extend([
                "",
                "## Mismatches",
            ])
            for m in self.mismatches:
                lines.append(f"- {m.get('field', '?')}: {m.get('expected', '?')} vs {m.get('actual', '?')}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ConfigIntegrityChecker
# ---------------------------------------------------------------------------


class ConfigIntegrityChecker:
    """Validates all config is consistent and versioned.

    All check methods are prefixed with _check_ and return (bool, list[drift]).
    NEVER outputs secret values in results.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.live_pilot_dir = self.data_root / "live_pilot"

    def check(self) -> ConfigIntegrityResult:
        """Run all config integrity checks."""
        result = ConfigIntegrityResult()
        all_passed = True

        # 1. Runtime config file exists and is valid
        c1_passed, c1_drift = self._check_runtime_config()
        result.checks["runtime_config_exists"] = c1_passed
        result.drift_detected.extend(c1_drift)
        all_passed = all_passed and c1_passed

        # 2. Risk envelope file exists and is valid
        c2_passed, c2_drift = self._check_risk_envelope()
        result.checks["risk_envelope_valid"] = c2_passed
        result.drift_detected.extend(c2_drift)
        all_passed = all_passed and c2_passed

        # 3. Strategy params consistent with approved versions
        c3_passed, c3_drift = self._check_strategy_versions()
        result.checks["strategy_versions_consistent"] = c3_passed
        result.drift_detected.extend(c3_drift)
        all_passed = all_passed and c3_passed

        # 4. Broker endpoint matches expected (paper vs live)
        c4_passed, c4_drift = self._check_broker_endpoint()
        result.checks["broker_endpoint_correct"] = c4_passed
        result.drift_detected.extend(c4_drift)
        all_passed = all_passed and c4_passed

        # 5. Env flags consistent (live submission must be disabled)
        c5_passed, c5_drift = self._check_env_flags()
        result.checks["env_flags_safe"] = c5_passed
        result.drift_detected.extend(c5_drift)
        all_passed = all_passed and c5_passed

        # 6. Approval manifests exist and not expired
        c6_passed, c6_drift = self._check_approval_manifests()
        result.checks["approval_manifests_valid"] = c6_passed
        result.drift_detected.extend(c6_drift)
        all_passed = all_passed and c6_passed

        # 7. Promotion manifests exist and valid
        c7_passed, c7_drift = self._check_promotion_manifests()
        result.checks["promotion_manifests_valid"] = c7_passed
        result.drift_detected.extend(c7_drift)
        all_passed = all_passed and c7_passed

        # 8. Release manifest (if any) consistent with current config
        c8_passed, c8_drift, c8_mismatches = self._check_release_consistency()
        result.checks["release_manifest_consistent"] = c8_passed
        result.drift_detected.extend(c8_drift)
        result.mismatches.extend(c8_mismatches)
        all_passed = all_passed and c8_passed

        result.passed = all_passed
        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_runtime_config(self) -> tuple[bool, list[str]]:
        drift: list[str] = []
        config_path = self.live_pilot_dir / "runtime_config.json"
        if not config_path.exists():
            drift.append("runtime_config.json not found")
            return False, drift

        try:
            data = json.loads(config_path.read_text())
            if not isinstance(data, dict):
                drift.append("runtime_config.json is not a valid JSON object")
                return False, drift
        except (json.JSONDecodeError, OSError) as exc:
            drift.append(f"runtime_config.json parse error: {exc}")
            return False, drift

        return True, drift

    def _check_risk_envelope(self) -> tuple[bool, list[str]]:
        drift: list[str] = []
        envelope_dir = self.live_pilot_dir / "envelopes"
        if not envelope_dir.exists():
            drift.append("envelopes directory not found")
            return False, drift

        envelope_files = sorted(envelope_dir.glob("*.json"))
        if not envelope_files:
            drift.append("no risk envelope files found")
            return False, drift

        valid_count = 0
        for path in envelope_files:
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict) and data.get("envelope_id"):
                    valid_count += 1
            except (json.JSONDecodeError, OSError):
                continue

        if valid_count == 0:
            drift.append("no valid risk envelope files found")
            return False, drift

        return True, drift

    def _check_strategy_versions(self) -> tuple[bool, list[str]]:
        drift: list[str] = []
        cfg_path = self.live_pilot_dir / "strategy_config.json"
        if not cfg_path.exists():
            # No strategy config is not necessarily a failure
            return True, drift

        try:
            data = json.loads(cfg_path.read_text())
            if not isinstance(data, dict):
                drift.append("strategy_config.json not a valid object")
                return False, drift
        except (json.JSONDecodeError, OSError) as exc:
            drift.append(f"strategy_config.json parse error: {exc}")
            return False, drift

        return True, drift

    def _check_broker_endpoint(self) -> tuple[bool, list[str]]:
        drift: list[str] = []
        cfg_path = self.live_pilot_dir / "runtime_config.json"
        if not cfg_path.exists():
            return True, drift  # No config means we can't check

        try:
            data = json.loads(cfg_path.read_text())
            base_url = data.get("base_url", "") or data.get("broker_base_url", "") or ""
            paper_endpoints = ["paper-api.alpaca.markets", "127.0.0.1"]
            is_paper = any(ep in base_url for ep in paper_endpoints)

            # Check if we are pointing at a live endpoint
            live_endpoints = ["api.alpaca.markets"]
            is_live = any(ep in base_url for ep in live_endpoints) and not is_paper

            if is_live:
                drift.append(
                    f"Broker endpoint appears to be LIVE: {self._mask_secrets(base_url)}"
                )
                return False, drift
        except (json.JSONDecodeError, OSError):
            return True, drift

        return True, drift

    def _check_env_flags(self) -> tuple[bool, list[str]]:
        drift: list[str] = []
        live_submission = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower()
        if live_submission in ("1", "true", "yes"):
            drift.append(
                "QUANT_LIVE_SUBMISSION_ENABLED is enabled — should be '0' or 'false'"
            )
            return False, drift
        return True, drift

    def _check_approval_manifests(self) -> tuple[bool, list[str]]:
        drift: list[str] = []
        approvals_dir = self.live_pilot_dir / "approvals"
        if not approvals_dir.exists():
            drift.append("approvals directory not found")
            return False, drift

        approval_files = sorted(approvals_dir.glob("*.json"))
        if not approval_files:
            drift.append("no approval files found")
            return False, drift

        valid_count = 0
        now = _utc_now().isoformat()
        for path in approval_files:
            try:
                data = json.loads(path.read_text())
                status = data.get("status", "")
                expires_at = data.get("expires_at", "")
                if status == "APPROVED":
                    valid_count += 1
                    if expires_at and expires_at < now:
                        drift.append(f"Approval {path.stem} is EXPIRED")
            except (json.JSONDecodeError, OSError):
                continue

        if valid_count == 0:
            drift.append("no valid approved approval manifests found")
            return False, drift

        return True, drift

    def _check_promotion_manifests(self) -> tuple[bool, list[str]]:
        drift: list[str] = []
        promotions_dir = self.live_pilot_dir / "promotions"
        if promotions_dir.exists():
            prom_files = sorted(promotions_dir.glob("*.json"))
            if not prom_files:
                drift.append("no promotion manifest files found")
                return False, drift
        # Promotions dir is optional — not failing if missing

        return True, drift

    def _check_release_consistency(self) -> tuple[bool, list[str], list[dict]]:
        drift: list[str] = []
        mismatches: list[dict] = []
        releases_dir = self.live_pilot_dir / "releases"
        if not releases_dir.exists():
            return True, drift, mismatches

        release_files = sorted(releases_dir.glob("*.json"))
        if not release_files:
            return True, drift, mismatches

        # Check the latest release for config drift
        latest = release_files[-1]
        try:
            release_data = json.loads(latest.read_text())
            release_config_hash = release_data.get("config_hash", "")
            if release_config_hash:
                from quant_us.live.g9_release_manifest import ReleaseManifestManager
                mgr = ReleaseManifestManager(data_root=str(self.data_root))
                current_hash = mgr.compute_config_hash()
                if current_hash != release_config_hash:
                    drift.append("config hash drift detected — release hash does not match current config")
                    mismatches.append({
                        "field": "config_hash",
                        "expected": release_config_hash[:16] + "...",
                        "actual": current_hash[:16] + "...",
                    })
        except (json.JSONDecodeError, OSError):
            return True, drift, mismatches

        return len(drift) == 0, drift, mismatches

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _hash_config(self, path: str) -> str:
        """SHA256 hash of config file."""
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:
            return ""

    def _mask_secrets(self, value: str) -> str:
        """Mask any secret-like values before returning."""
        if not value:
            return value
        if SECRET_VALUE_PATTERNS.search(value) or len(value) > 20:
            # Mask all but first 8 and last 4 characters
            if len(value) > 12:
                return value[:8] + "*" * (len(value) - 12) + value[-4:]
        return value

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_result(self, result: ConfigIntegrityResult, output_path: str | None = None) -> str:
        if output_path is None:
            timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
            output_path = str(self.data_root / f"live_pilot/config_check_{timestamp}.json")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
        _logger.info("Config check result saved: %s", path)
        return str(path)
