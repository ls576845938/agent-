from __future__ import annotations

import sys
from pathlib import Path

from scripts import win_make


def test_win_make_lists_us_equity_targets() -> None:
    data = win_make.parse_makefile(Path("Makefile"))

    assert data.recipes[".PHONY"] == []
    assert "validate-us-equity-evidence" in data.recipes
    assert "build-us-etf-macro-rotation" in data.recipes
    assert "build-us-equity-strategy-production-line" in data.recipes
    assert "dry-run-us-equity-tiingo-eod" in data.recipes
    assert "capture-us-equity-tiingo-eod" in data.recipes
    assert any("build_us_etf_macro_rotation_research_report.py" in recipe for recipe in data.recipes["validate-us-equity-evidence"])


def test_win_make_joins_continued_recipe_lines(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "\n".join(
            [
                "PYTHON ?= python3",
                "sample:",
                "\t$(PYTHON) scripts/example.py \\",
                '\t\t--repo-root "." \\',
                '\t\t--json',
            ]
        ),
        encoding="utf-8",
    )

    data = win_make.parse_makefile(makefile)

    assert data.recipes["sample"] == ['$(PYTHON) scripts/example.py --repo-root "." --json']


def test_win_make_uses_current_python_when_makefile_defaults_to_python3() -> None:
    data = win_make.MakefileData(variables={"PYTHON": "python3"}, recipes={"sample": ["$(PYTHON) -m pytest -q"]})

    variables = win_make.default_variables(data, Path("scripts/win_make.py"))
    expanded = win_make.expand_command(data.recipes["sample"][0], variables)

    assert sys.executable in expanded
    assert "python3" not in expanded


def test_win_make_reports_unknown_target() -> None:
    data = win_make.MakefileData(variables={}, recipes={})

    exit_code = win_make.run_target(
        "missing",
        makefile_data=data,
        variables={},
        cwd=Path("."),
        dry_run=True,
    )

    assert exit_code == 2
