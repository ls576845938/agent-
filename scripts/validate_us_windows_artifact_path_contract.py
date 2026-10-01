from __future__ import annotations

import argparse
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/governance/us_windows_artifact_path_contract_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a US durable or external artifact-path reference."
    )
    parser.add_argument("--reference", required=True, help="JSON reference to validate")
    args = parser.parse_args()

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    schema_path = ROOT / config["reference_schema_path"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    reference_path = Path(args.reference)
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    jsonschema.validate(reference, schema)
    print(
        json.dumps(
            {
                "status": "valid",
                "schema_version": reference["schema_version"],
                "path_kind": reference["path_kind"],
                "stable_identity": reference["stable_identity"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
