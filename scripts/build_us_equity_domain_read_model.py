from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.application.us_equity_domain_read_model import (
    TEAM_CONTEXT_DISCOVERY_PATH,
    USDomainReadModelService,
)
from quant_us.monitoring.us_equity_domain_read_model_repository import (
    USCommittedEvidenceRepository,
)


def build_report(
    *,
    repo_root: Path,
    generated_at_utc: datetime | None = None,
) -> dict[str, object]:
    root = repo_root.resolve()
    service = USDomainReadModelService(
        repository=USCommittedEvidenceRepository(repo_root=root),
        head_resolver=lambda: _git_head(root),
        clock=lambda: generated_at_utc or datetime.now(timezone.utc),
    )
    return service.read()


def write_report(
    payload: dict[str, object],
    *,
    repo_root: Path,
    output: Path,
) -> Path:
    root = repo_root.resolve()
    target = output if output.is_absolute() else root / output
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("us_domain_read_model_output_outside_repo") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def _git_head(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize the current-HEAD US equity domain read model."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(TEAM_CONTEXT_DISCOVERY_PATH),
    )
    parser.add_argument("--generated-at-utc")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Build and print without writing the durable projection.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generated_at = (
        datetime.fromisoformat(args.generated_at_utc.replace("Z", "+00:00"))
        if args.generated_at_utc
        else None
    )
    payload = build_report(
        repo_root=args.repo_root,
        generated_at_utc=generated_at,
    )
    if not args.check_only:
        write_report(
            payload,
            repo_root=args.repo_root,
            output=args.output,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
