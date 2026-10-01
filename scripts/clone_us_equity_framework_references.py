from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REFERENCE_ROOT = Path("D:/quant_open_source_reference")


@dataclass(frozen=True)
class ReferenceRepo:
    name: str
    url: str
    zip_url: str
    purpose: str


REFERENCE_REPOS = [
    ReferenceRepo(
        name="nautilus_trader",
        url="https://github.com/nautechsystems/nautilus_trader.git",
        zip_url="https://codeload.github.com/nautechsystems/nautilus_trader/zip/refs/heads/develop",
        purpose="event-driven engine, deterministic replay, order lifecycle",
    ),
    ReferenceRepo(
        name="Lean",
        url="https://github.com/QuantConnect/Lean.git",
        zip_url="https://codeload.github.com/QuantConnect/Lean/zip/refs/heads/master",
        purpose="algorithm lifecycle, brokerage/data model, CLI workflow",
    ),
    ReferenceRepo(
        name="zipline-reloaded",
        url="https://github.com/stefan-jansen/zipline-reloaded.git",
        zip_url="https://codeload.github.com/stefan-jansen/zipline-reloaded/zip/refs/heads/main",
        purpose="calendar, bundle, asset finder, Pipeline-style research",
    ),
]


def clone_reference_repos(
    *,
    root: Path = DEFAULT_REFERENCE_ROOT,
    dry_run: bool = True,
    depth: int = 1,
    zip_fallback: bool = False,
    runner: Callable[..., Any] = subprocess.run,
) -> list[dict[str, str]]:
    root = Path(root)
    results: list[dict[str, str]] = []
    for repo in REFERENCE_REPOS:
        target = root / repo.name
        archive = root / "_archives" / f"{repo.name}.zip"
        command = ["git", "clone", "--depth", str(depth), repo.url, str(target)]
        zip_command = ["curl.exe", "-L", "--fail", "--max-time", "300", "-o", str(archive), repo.zip_url]
        if target.exists():
            results.append(
                {
                    "name": repo.name,
                    "status": "already_exists",
                    "target": str(target),
                    "purpose": repo.purpose,
                }
            )
            continue
        if dry_run:
            results.append(
                {
                    "name": repo.name,
                    "status": "dry_run",
                    "target": str(target),
                    "command": " ".join(command),
                    "zip_fallback_command": " ".join(zip_command),
                    "purpose": repo.purpose,
                }
            )
            continue
        root.mkdir(parents=True, exist_ok=True)
        try:
            runner(command, check=True)
        except subprocess.CalledProcessError as exc:
            if zip_fallback:
                archive.parent.mkdir(parents=True, exist_ok=True)
                try:
                    runner(zip_command, check=True)
                except subprocess.CalledProcessError as zip_exc:
                    results.append(
                        {
                            "name": repo.name,
                            "status": "clone_and_zip_failed",
                            "target": str(target),
                            "archive": str(archive),
                            "error": str(exc),
                            "zip_error": str(zip_exc),
                            "purpose": repo.purpose,
                        }
                    )
                    continue
                results.append(
                    {
                        "name": repo.name,
                        "status": "zip_downloaded_after_clone_failed",
                        "target": str(target),
                        "archive": str(archive),
                        "clone_error": str(exc),
                        "purpose": repo.purpose,
                    }
                )
                continue
            results.append(
                {
                    "name": repo.name,
                    "status": "clone_failed",
                    "target": str(target),
                    "error": str(exc),
                    "purpose": repo.purpose,
                }
            )
            continue
        results.append({"name": repo.name, "status": "cloned", "target": str(target), "purpose": repo.purpose})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone external US equity framework reference repositories.")
    parser.add_argument("--root", default=str(DEFAULT_REFERENCE_ROOT), help="External clone root outside the repo.")
    parser.add_argument("--depth", type=int, default=1, help="git clone depth.")
    parser.add_argument("--execute", action="store_true", help="Actually clone. Default is dry-run.")
    parser.add_argument("--zip-fallback", action="store_true", help="Download codeload zip if git clone fails.")
    args = parser.parse_args()
    results = clone_reference_repos(
        root=Path(args.root),
        dry_run=not args.execute,
        depth=args.depth,
        zip_fallback=args.zip_fallback,
    )
    for row in results:
        print(row)


if __name__ == "__main__":
    main()
