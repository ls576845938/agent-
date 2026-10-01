from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
from typing import Any


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ResearchReadonlyViewError(RuntimeError):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    def detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "read_only": True,
            "controls_disabled": True,
            "promotion_eligible": False,
            "paper_allowed": False,
            "live_allowed": False,
            "broker_or_order_allowed": False,
        }


class ResearchReadonlyViews:
    """Side-effect-free projections for the research_readonly HTTP profile.

    Every filesystem root is selected by the server. Missing stores are a valid
    empty state, while malformed or escaped records fail closed.
    """

    def __init__(self, *, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.data_root = self.repo_root / "data"
        self.portfolio_runs_root = self.repo_root / "artifacts" / "portfolio_runs"

    def require_data_root(self, requested: str) -> None:
        self._require_selector("data_root", requested, "data")
        self._ensure_server_owned_root(self.data_root)

    def require_portfolio_root(self, requested: str) -> None:
        self._require_selector(
            "artifacts_root", requested, "artifacts/portfolio_runs"
        )
        self._ensure_server_owned_root(self.portfolio_runs_root)

    def list_feature_snapshots(
        self, *, data_root: str = "data"
    ) -> list[dict[str, Any]]:
        self.require_data_root(data_root)
        root = self.data_root / "features" / "snapshots"
        if not root.exists():
            return []
        self._ensure_bounded(self.data_root, root)
        snapshots: list[dict[str, Any]] = []
        for directory in sorted(root.iterdir()):
            if not directory.is_dir():
                continue
            self._ensure_bounded(root, directory)
            manifest_path = directory / "manifest.json"
            if manifest_path.exists():
                snapshots.append(self._read_json(manifest_path, root))
        return snapshots

    def list_experiments(self, *, data_root: str = "data") -> list[dict[str, Any]]:
        self.require_data_root(data_root)
        return self._list_records(
            self.data_root / "research" / "experiments", "manifest.json"
        )

    def list_candidates(self, *, data_root: str = "data") -> list[dict[str, Any]]:
        self.require_data_root(data_root)
        return self._list_records(
            self.data_root / "research" / "candidates", "candidate.json"
        )

    def list_strategy_manifests(
        self, *, data_root: str = "data", status: str = ""
    ) -> list[dict[str, Any]]:
        self.require_data_root(data_root)
        normalized_status = status.strip()
        if normalized_status and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", normalized_status):
            raise ResearchReadonlyViewError(
                status_code=400,
                code="research_readonly_status_invalid",
                message="Strategy manifest status must be a bounded canonical status.",
            )
        records = self._list_records(
            self.data_root / "research" / "manifests", "manifest.json"
        )
        if normalized_status:
            records = [
                item
                for item in records
                if str(item.get("promotion_status", "")) == normalized_status
            ]
        return records

    def list_pending_reviews(
        self, *, data_root: str = "data"
    ) -> list[dict[str, Any]]:
        self.require_data_root(data_root)
        records = self._list_records(
            self.data_root / "research" / "paper_reviews", "review.json"
        )
        fields = (
            "paper_review_id",
            "strategy_manifest_id",
            "portfolio_sim_id",
            "status",
            "proposed_symbols",
            "proposed_capital",
            "created_at",
        )
        return [
            {key: item.get(key, [] if key == "proposed_symbols" else "") for key in fields}
            for item in records
            if item.get("status") == "PENDING_HUMAN_REVIEW"
        ]

    def system_overview(
        self,
        *,
        data_root: str = "data",
        qlib_artifacts_root: str = "artifacts/qlib_runs",
        portfolio_artifacts_root: str = "artifacts/portfolio_runs",
    ) -> dict[str, Any]:
        self.require_data_root(data_root)
        self._require_selector(
            "qlib_artifacts_root", qlib_artifacts_root, "artifacts/qlib_runs"
        )
        self.require_portfolio_root(portfolio_artifacts_root)
        return {
            "status": "blocked",
            "stage": "research_readonly",
            "mode": "research_readonly",
            "data_root": "data",
            "health": {
                "status": "unknown",
                "reason": "research_readonly_runtime_health_not_probed",
            },
            "registry": {
                "integrity": "unknown",
                "reason": "inspect_the_versioned_registry_endpoint",
            },
            "minute_data_quality": {
                "status": "unknown",
                "reason": "research_readonly_does_not_run_data_quality_jobs",
            },
            "paper_review": self.paper_review_entry_state(data_root=data_root),
            "broker_credentials": {
                "status": "not_checked",
                "checked": False,
                "private_endpoint_used": False,
            },
            "execution": {
                "status": "disabled",
                "permission": False,
                "paper_allowed": False,
                "live_allowed": False,
                "broker_or_order_allowed": False,
            },
            "next_actions": [
                "Inspect committed research evidence; write, approval, private, order and live controls remain disabled."
            ],
        }

    def paper_review_entry_state(
        self, *, data_root: str = "data"
    ) -> dict[str, Any]:
        self.require_data_root(data_root)
        creation = {
            "creation_allowed": False,
            "why_blocked": ["research_readonly_controls_disabled"],
            "next_command": "",
            "preferred_manifest_id": "",
        }
        return {
            "status": "BLOCKED",
            "entry_allowed": False,
            "creation_allowed": False,
            "why_blocked": ["research_readonly_controls_disabled"],
            "next_command": "",
            "preferred_manifest_id": "",
            "creation": creation,
            "summary": (
                "Research records are readable, but review creation and all "
                "paper/private/order/live controls are disabled."
            ),
        }

    def portfolio_status(self) -> dict[str, Any]:
        self.require_data_root("data")
        target_root = self.data_root / "portfolio" / "targets"
        records = self._list_flat_json(target_root)
        return {
            "status": "ok",
            "portfolio_count": len(records),
            "latest_portfolio": records[-1] if records else None,
            "read_only": True,
            "live_enabled": False,
        }

    def list_portfolio_runs(
        self, *, artifacts_root: str = "artifacts/portfolio_runs", limit: int = 20
    ) -> dict[str, Any]:
        self.require_portfolio_root(artifacts_root)
        bounded_limit = max(1, min(int(limit), 100))
        root = self.portfolio_runs_root
        if not root.exists():
            run_roots: list[Path] = []
        else:
            self._ensure_bounded(root, root)
            run_roots = []
            for path in root.iterdir():
                if path.is_dir():
                    self._ensure_bounded(root, path)
                    run_roots.append(path)
            run_roots.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return {
            "status": "ok",
            "research_only": True,
            "daily_only": True,
            "live_enabled": False,
            "dependencies": {
                "pypfopt": importlib.util.find_spec("pypfopt") is not None,
            },
            "configs": {
                "max_sharpe": "configs/portfolio/pypfopt_long_only_max_sharpe.yaml",
                "min_volatility": "configs/portfolio/pypfopt_long_only_min_volatility.yaml",
                "hrp": "configs/portfolio/pypfopt_hrp.yaml",
            },
            "runs": [self._portfolio_run_summary(path) for path in run_roots[:bounded_limit]],
        }

    def get_portfolio_run(
        self,
        portfolio_run_id: str,
        *,
        artifacts_root: str = "artifacts/portfolio_runs",
    ) -> dict[str, Any]:
        self.require_portfolio_root(artifacts_root)
        if not _SAFE_ID.fullmatch(portfolio_run_id):
            raise ResearchReadonlyViewError(
                status_code=400,
                code="research_readonly_portfolio_run_id_invalid",
                message="Portfolio run id must be a bounded opaque identifier.",
            )
        run_root = self.portfolio_runs_root / portfolio_run_id
        self._ensure_bounded(self.portfolio_runs_root, run_root)
        if not run_root.is_dir():
            raise ResearchReadonlyViewError(
                status_code=404,
                code="research_readonly_portfolio_run_not_found",
                message=f"Portfolio run not found: {portfolio_run_id}",
            )
        return {
            "summary": self._portfolio_run_summary(run_root),
            "run_manifest": self._read_optional_json(run_root / "run_manifest.json", run_root),
            "expected_returns_preview": self._parquet_preview(run_root / "expected_returns.parquet", run_root),
            "covariance_preview": self._parquet_preview(run_root / "covariance.parquet", run_root),
            "target_weights_preview": self._parquet_preview(run_root / "target_weights.parquet", run_root),
            "target_positions_preview": self._parquet_preview(run_root / "target_positions.parquet", run_root),
            "target_positions_json": self._read_optional_json(run_root / "target_positions.json", run_root),
        }

    def _portfolio_run_summary(self, run_root: Path) -> dict[str, Any]:
        self._ensure_bounded(self.portfolio_runs_root, run_root)
        manifest = self._read_optional_json(run_root / "run_manifest.json", run_root)
        weights_path = run_root / "target_weights.parquet"
        positions_path = run_root / "target_positions.parquet"
        weight_rows = 0
        latest_weight_sum = None
        if weights_path.exists():
            self._ensure_bounded(run_root, weights_path)
            try:
                import pandas as pd

                frame = pd.read_parquet(weights_path)
            except Exception as exc:
                raise ResearchReadonlyViewError(
                    status_code=409,
                    code="research_readonly_portfolio_artifact_unreadable",
                    message=f"Portfolio artifact is unreadable: {weights_path.name}",
                ) from exc
            required_columns = {"datetime", "target_weight"}
            if not required_columns.issubset(frame.columns):
                raise ResearchReadonlyViewError(
                    status_code=409,
                    code="research_readonly_portfolio_artifact_unreadable",
                    message=(
                        "Portfolio artifact lacks required summary columns: "
                        f"{weights_path.name}"
                    ),
                )
            weight_rows = int(len(frame))
            if not frame.empty:
                latest_date = frame["datetime"].max()
                latest = frame[frame["datetime"] == latest_date]
                latest_weight_sum = float(latest["target_weight"].sum())
        return {
            "portfolio_run_id": run_root.name,
            "updated_at": datetime.fromtimestamp(
                run_root.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
            "status": "RESEARCH_ONLY_COMPLETED" if weights_path.exists() else "RESEARCH_ONLY_MISSING",
            "source_score_run_id": manifest.get("source_score_run_id", ""),
            "optimizer": (
                manifest.get("config", {}).get("optimizer", "")
                if isinstance(manifest.get("config", {}), dict)
                else ""
            ),
            "fallback_used": bool(manifest.get("fallback_used", False)),
            "target_weight_rows": weight_rows,
            "latest_weight_sum": latest_weight_sum,
            "has_target_positions": positions_path.exists(),
            "logical_root": f"artifacts/portfolio_runs/{run_root.name}",
            "read_only": True,
            "live_enabled": False,
        }

    def _list_records(self, root: Path, filename: str) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        self._ensure_bounded(self.data_root, root)
        records: list[dict[str, Any]] = []
        for directory in sorted(root.iterdir()):
            if not directory.is_dir():
                continue
            self._ensure_bounded(root, directory)
            path = directory / filename
            if path.exists():
                records.append(self._read_json(path, root))
        records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return records

    def _list_flat_json(self, root: Path) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        self._ensure_bounded(self.data_root, root)
        records = [self._read_json(path, root) for path in sorted(root.glob("*.json"))]
        return records

    def _read_optional_json(self, path: Path, root: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return self._read_json(path, root)

    def _read_json(self, path: Path, root: Path) -> dict[str, Any]:
        self._ensure_bounded(root, path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResearchReadonlyViewError(
                status_code=409,
                code="research_readonly_record_unreadable",
                message=f"Committed/local research record is unreadable: {path.name}",
            ) from exc
        if not isinstance(payload, dict):
            raise ResearchReadonlyViewError(
                status_code=409,
                code="research_readonly_record_invalid",
                message=f"Research record must contain a JSON object: {path.name}",
            )
        return payload

    def _parquet_preview(
        self, path: Path, root: Path, *, limit: int = 12
    ) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        self._ensure_bounded(root, path)
        try:
            import pandas as pd

            frame = pd.read_parquet(path).head(max(1, min(limit, 100)))
            payload = json.loads(frame.to_json(orient="records", date_format="iso"))
        except Exception as exc:
            raise ResearchReadonlyViewError(
                status_code=409,
                code="research_readonly_portfolio_artifact_unreadable",
                message=f"Portfolio artifact is unreadable: {path.name}",
            ) from exc
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _require_selector(name: str, requested: str, expected: str) -> None:
        if requested != expected:
            raise ResearchReadonlyViewError(
                status_code=400,
                code="research_readonly_selector_is_server_owned",
                message=f"{name} is server-owned in research_readonly mode.",
            )

    def _ensure_server_owned_root(self, root: Path) -> None:
        if not root.resolve().is_relative_to(self.repo_root):
            raise ResearchReadonlyViewError(
                status_code=409,
                code="research_readonly_server_root_escape",
                message="Server-owned research root resolved outside the repository.",
            )

    @staticmethod
    def _ensure_bounded(root: Path, path: Path) -> None:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(resolved_root):
            raise ResearchReadonlyViewError(
                status_code=409,
                code="research_readonly_path_escape",
                message="Research record resolved outside its server-owned root.",
            )
