from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from quant_us.core.types import new_id

from .schemas import (
    PortfolioAdapterConfig,
    load_portfolio_config,
    now_iso,
    read_run_manifest,
    read_target_weights_frame,
    target_positions_json_path,
    target_positions_parquet_path,
    write_frame,
    write_json,
)


def import_target_weights(
    *,
    portfolio_run_id: str,
    config: PortfolioAdapterConfig,
    strategy_id: str | None = None,
) -> tuple[pd.DataFrame, Path, Path]:
    weights = read_target_weights_frame(config, portfolio_run_id)
    run_manifest = read_run_manifest(config, portfolio_run_id)
    manifest_config = run_manifest.get("config", {}) if isinstance(run_manifest, dict) else {}
    resolved_strategy_id = str(strategy_id or manifest_config.get("strategy_id") or config.strategy_id)
    created_at = now_iso()

    parquet_rows: list[dict[str, object]] = []
    json_rows: list[dict[str, object]] = []
    for row in weights.to_dict(orient="records"):
        target_position_id = new_id("tgt")
        metadata = {
            "portfolio_run_id": row["portfolio_run_id"],
            "source_score_run_id": row["source_score_run_id"],
            "optimizer": row["optimizer"],
            "fallback": row["fallback"],
            "raw_weight": float(row["raw_weight"]),
            "clipped_weight": float(row["clipped_weight"]),
            "constraints_hash": row["constraints_hash"],
        }
        parquet_rows.append(
            {
                "timestamp_utc": row["datetime"],
                "strategy_id": resolved_strategy_id,
                "symbol": row["symbol"],
                "target_weight": float(row["target_weight"]),
                "target_quantity": None,
                "signal_id": "",
                "target_position_id": target_position_id,
                "metadata_json": json.dumps(metadata, sort_keys=True),
                "created_at": created_at,
            }
        )
        json_rows.append(
            {
                "timestamp_utc": pd.Timestamp(row["datetime"]).isoformat(),
                "strategy_id": resolved_strategy_id,
                "symbol": row["symbol"],
                "target_weight": float(row["target_weight"]),
                "target_quantity": None,
                "signal_id": "",
                "target_position_id": target_position_id,
                "metadata": metadata,
            }
        )

    frame = pd.DataFrame(parquet_rows)
    if not frame.empty:
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        frame = frame.sort_values(["timestamp_utc", "symbol"]).reset_index(drop=True)

    parquet_path = target_positions_parquet_path(config, portfolio_run_id)
    json_path = target_positions_json_path(config, portfolio_run_id)
    write_frame(frame, parquet_path)
    write_json(json_path, json_rows)
    return frame, parquet_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert adapter target weights into TargetPosition-compatible artifacts.")
    parser.add_argument("--portfolio-run-id", required=True, help="Portfolio run id under artifacts/portfolio_runs/<run_id>/")
    parser.add_argument("--config", required=False, help="Optional portfolio config yaml path.")
    parser.add_argument("--strategy-id", required=False, help="Optional strategy id override for target positions.")
    args = parser.parse_args()

    config = load_portfolio_config(args.config)
    frame, parquet_path, json_path = import_target_weights(
        portfolio_run_id=args.portfolio_run_id,
        config=config,
        strategy_id=args.strategy_id,
    )
    print(f"wrote target positions parquet: {parquet_path}")
    print(f"wrote target positions json: {json_path}")
    print(f"rows={len(frame)}")


if __name__ == "__main__":
    main()
