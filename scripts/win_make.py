from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


VARIABLE_RE = re.compile(r"^([A-Za-z0-9_]+)\s*\?=\s*(.*)$")
TARGET_RE = re.compile(r"^([A-Za-z0-9_.\-/]+)\s*:(?:\s|$)")
EXPANSION_RE = re.compile(r"\$\(([A-Za-z0-9_]+)\)")
POSIX_TEST_GUARD_RE = re.compile(r'^test -n "(.*)" \|\| \(echo "(.+)" >&2; exit ([0-9]+)\)$')


@dataclass(frozen=True)
class MakefileData:
    variables: dict[str, str]
    recipes: dict[str, list[str]]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_makefile(path: Path) -> MakefileData:
    variables: dict[str, str] = {}
    recipes: dict[str, list[str]] = {}
    current_target: str | None = None
    pending_recipe: str | None = None
    target_header_continuation = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if target_header_continuation:
            target_header_continuation = raw_line.rstrip().endswith("\\")
            continue

        if raw_line.startswith("\t"):
            if current_target is None:
                continue
            recipe_piece = raw_line[1:].rstrip()
            if pending_recipe is not None:
                recipe_piece = f"{pending_recipe} {recipe_piece.lstrip()}"
            if recipe_piece.endswith("\\"):
                pending_recipe = recipe_piece[:-1].rstrip()
                continue
            recipes.setdefault(current_target, []).append(recipe_piece)
            pending_recipe = None
            continue

        if pending_recipe is not None and current_target is not None:
            recipes.setdefault(current_target, []).append(pending_recipe)
            pending_recipe = None

        variable_match = VARIABLE_RE.match(raw_line)
        if variable_match:
            variables[variable_match.group(1)] = variable_match.group(2).strip()
            continue

        target_match = TARGET_RE.match(raw_line)
        if target_match:
            current_target = target_match.group(1)
            recipes.setdefault(current_target, [])
            target_header_continuation = raw_line.rstrip().endswith("\\")
            continue

        if raw_line.strip() and not raw_line.lstrip().startswith("#"):
            current_target = None

    if pending_recipe is not None and current_target is not None:
        recipes.setdefault(current_target, []).append(pending_recipe)

    return MakefileData(variables=variables, recipes=recipes)


def default_variables(makefile_data: MakefileData, script_path: Path) -> dict[str, str]:
    variables = dict(makefile_data.variables)
    variables.update({key: value for key, value in os.environ.items() if key in variables})

    if not os.environ.get("PYTHON"):
        variables["PYTHON"] = quote_for_shell(Path(sys.executable))
    variables["MAKE"] = f"{quote_for_shell(Path(sys.executable))} {quote_for_shell(script_path)}"
    return variables


def quote_for_shell(path: Path) -> str:
    text = str(path)
    if any(char.isspace() for char in text):
        return f'"{text}"'
    return text


def expand_command(command: str, variables: dict[str, str]) -> str:
    previous = None
    expanded = command
    while expanded != previous:
        previous = expanded
        expanded = EXPANSION_RE.sub(lambda match: variables.get(match.group(1), ""), expanded)
    return expanded


def normalize_recipe_command(command: str) -> str:
    command = command.strip()
    while command.startswith("@") or command.startswith("-"):
        command = command[1:].lstrip()
    return command


def run_command(command: str, *, cwd: Path, dry_run: bool) -> int:
    command = normalize_recipe_command(command)
    if not command:
        return 0
    print(f"> {command}", flush=True)
    if dry_run:
        return 0

    guard_match = POSIX_TEST_GUARD_RE.match(command)
    if guard_match:
        value, message, exit_code = guard_match.groups()
        if value:
            return 0
        print(message, file=sys.stderr, flush=True)
        return int(exit_code)

    completed = subprocess.run(command, cwd=cwd, shell=True)
    return completed.returncode


def run_target(
    target: str,
    *,
    makefile_data: MakefileData,
    variables: dict[str, str],
    cwd: Path,
    dry_run: bool,
) -> int:
    if target not in makefile_data.recipes:
        print(f"Unknown target: {target}", file=sys.stderr)
        return 2

    recipes = makefile_data.recipes[target]
    if not recipes:
        print(f"Target has no recipe: {target}", file=sys.stderr)
        return 2

    for recipe in recipes:
        expanded = expand_command(recipe, variables)
        exit_code = run_command(expanded, cwd=cwd, dry_run=dry_run)
        if exit_code != 0:
            return exit_code
    return 0


def parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Small Windows-compatible runner for this repository's Makefile.")
    parser.add_argument("args", nargs="*", help="Optional VAR=value overrides followed by one target.")
    parser.add_argument("--list", action="store_true", help="List targets with recipes.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    return parser.parse_args(argv)


def split_overrides_and_target(args: list[str]) -> tuple[dict[str, str], str | None]:
    overrides: dict[str, str] = {}
    target: str | None = None
    for arg in args:
        if "=" in arg and target is None:
            key, value = arg.split("=", 1)
            overrides[key] = value
            continue
        if target is not None:
            raise ValueError("Only one target is supported per invocation.")
        target = arg
    return overrides, target


def main(argv: list[str] | None = None) -> int:
    namespace = parse_cli(sys.argv[1:] if argv is None else argv)
    root = repo_root()
    makefile = root / "Makefile"
    makefile_data = parse_makefile(makefile)

    if namespace.list:
        for target in sorted(name for name, recipe in makefile_data.recipes.items() if recipe):
            print(target)
        return 0

    try:
        overrides, target = split_overrides_and_target(namespace.args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if target is None:
        print("A target is required. Use --list to inspect available targets.", file=sys.stderr)
        return 2

    variables = default_variables(makefile_data, Path(__file__).resolve())
    variables.update(overrides)
    return run_target(
        target,
        makefile_data=makefile_data,
        variables=variables,
        cwd=root,
        dry_run=namespace.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
