from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_10s_microstructure_data_contract import (
    build_contract_lock,
    build_report,
    derive_measured_metrics,
    evaluate_manifest_specs,
    write_immutable_artifact_bundle,
)
from tools.agent_governance.shared_data import default_shared_data_root


MANIFEST_PATHS = (
    ".agent/data_manifests/btc-okx-v3-immutable-public-market-evidence/btc-okx-v3-public-btcusdt-20260727T075929750Z-src311c5ec7.json",
    ".agent/data_manifests/btc-okx-public-ws-l2-funding-evidence/btc-okx-public-evidence-20260728T081955Z-main1c2d545c-corr1.json",
    ".agent/data_manifests/btc-okx-timestamp-aligned-public-l2-history/btc-okx-l2-observer-1d-00000002-20260729t035023327336z.json",
    ".agent/data_manifests/btc-okx-real-l2-attestation/btc-okx-real-l2-attestation-20260728T232947Z-e3471caf3-timestamp-precision07-quality1.json",
)
EXACT_MANIFEST_SPEC = re.compile(
    r"^[0-9a-f]{40}:[.]agent/data_manifests/[A-Za-z0-9._/-]+[.]json$"
)


def exact_manifest_specs(
    *,
    manifest_ref: str,
    explicit_specs: list[str] | None,
) -> list[str]:
    specs = list(explicit_specs or [])
    if not specs:
        specs = [f"{manifest_ref}:{path}" for path in MANIFEST_PATHS]
    invalid = [value for value in specs if not EXACT_MANIFEST_SPEC.fullmatch(value)]
    if invalid:
        raise ValueError(f"exact_committed_manifest_git_spec_required:{invalid[0]}")
    return specs


def _head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build immutable offline BTC 10s microstructure research-admission evidence.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--shared-root", type=Path)
    parser.add_argument("--manifest-ref", default="4f3139431bb801f71f0bca9bbb0f69e4febdb8a4")
    parser.add_argument(
        "--manifest-git-spec",
        action="append",
        default=[],
        help="Repeatable exact <40-hex-commit>:.agent/data_manifests/...json binding.",
    )
    parser.add_argument("--prereg", type=Path, default=Path("docs/research/BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-at")
    args = parser.parse_args(argv)

    root = args.repo_root.resolve()
    shared_root = (args.shared_root or default_shared_data_root(root)).resolve()
    prereg_path = args.prereg if args.prereg.is_absolute() else root / args.prereg
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    specs = exact_manifest_specs(
        manifest_ref=args.manifest_ref,
        explicit_specs=args.manifest_git_spec,
    )
    sources = evaluate_manifest_specs(repo_root=root, shared_root=shared_root, manifest_git_specs=specs)
    metrics = derive_measured_metrics(sources)
    source_head = _head(root)
    generated_at = args.generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = build_report(
        prereg=prereg,
        source_head=source_head,
        generated_at=generated_at,
        source_evaluations=sources,
        measured_metrics=metrics,
    )
    lock = build_contract_lock(prereg=prereg, source_head=source_head, source_evaluations=sources)
    receipt = write_immutable_artifact_bundle(report=report, lock=lock, output=args.output.resolve())
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
