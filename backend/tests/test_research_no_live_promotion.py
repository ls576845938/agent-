"""PROVE research can't reach live.

No submit_order, no AlpacaBroker, no QUANT_LIVE, no broker imports
from any research module.
"""

from __future__ import annotations

import importlib
import pkgutil
import unittest


# Modules that are part of the research track
_RESEARCH_MODULES = [
    "quant_us.research",
    "quant_us.research.experiments",
    "quant_us.research.datasets",
    "quant_us.research.sweeps",
    "quant_us.research.cache",
    "quant_us.research.lab.manifest",
    "quant_us.research.lab.scorecard",
    "quant_us.research.automation",
    "quant_us.research.automation.pipeline",
    "quant_us.research.automation.ranking",
    "quant_us.research.automation.overfit",
    "quant_us.research.automation.dossier",
]

_FORBIDDEN_IMPORTS = [
    "submit_order",
    "AlpacaBroker",
    "QUANT_LIVE",
    "quant_us.live",
    "quant_us.execution",
]


class TestResearchNoLivePromotion(unittest.TestCase):
    """Verify that research modules never import live/execution code."""

    def _check_module_source(self, module_name: str) -> list[str]:
        """Check a module's source for forbidden content."""
        try:
            mod = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError):
            return [f"Could not import {module_name}"]

        source_file = getattr(mod, "__file__", None)
        if source_file is None:
            return [f"No __file__ for {module_name}"]

        try:
            with open(source_file, encoding="utf-8") as f:
                content = f.read()
        except (FileNotFoundError, OSError):
            return [f"Could not read {source_file}"]

        violations = []
        import re
        for forbidden in _FORBIDDEN_IMPORTS:
            if forbidden in {"quant_us.live", "quant_us.execution"}:
                if re.search(rf'(from\s+{re.escape(forbidden)}\s+import|import\s+{re.escape(forbidden)})', content):
                    violations.append(f"{module_name} contains an import of '{forbidden}'")
            elif forbidden in content:
                violations.append(f"{module_name} contains '{forbidden}'")
        return violations

    def test_no_live_imports_in_research(self) -> None:
        all_violations = []
        for mod_name in _RESEARCH_MODULES:
            violations = self._check_module_source(mod_name)
            all_violations.extend(violations)

        self.assertEqual(
            all_violations, [],
            f"Research modules contain forbidden imports: {all_violations}"
        )

    def test_no_submit_order_in_research_source(self) -> None:
        """Double-check no 'submit_order' string exists in research package."""
        import quant_us.research
        pkg_path = quant_us.research.__file__
        if pkg_path:
            pkg_dir = pkg_path.replace("__init__.py", "") if "__init__.py" in pkg_path else None
            if pkg_dir:
                import os
                for root, _dirs, files in os.walk(pkg_dir):
                    for fname in files:
                        if fname.endswith(".py"):
                            fpath = os.path.join(root, fname)
                            try:
                                with open(fpath, encoding="utf-8") as f:
                                    content = f.read()
                                self.assertNotIn(
                                    "submit_order", content,
                                    f"Found submit_order in {fpath}"
                                )
                            except (FileNotFoundError, OSError):
                                pass

    def test_no_alpaca_broker_in_research(self) -> None:
        """Verify research modules don't import Alpaca broker."""
        import quant_us.research
        pkg_path = quant_us.research.__file__
        if pkg_path:
            pkg_dir = pkg_path.replace("__init__.py", "") if "__init__.py" in pkg_path else None
            if pkg_dir:
                import os
                for root, _dirs, files in os.walk(pkg_dir):
                    for fname in files:
                        if fname.endswith(".py"):
                            fpath = os.path.join(root, fname)
                            try:
                                with open(fpath, encoding="utf-8") as f:
                                    content = f.read()
                                if "AlpacaBroker" in content:
                                    # Check if it's just a comment or a test
                                    if "#" not in content.split("AlpacaBroker")[0][-5:]:
                                        self.fail(f"Found AlpacaBroker in {fpath}")
                            except (FileNotFoundError, OSError):
                                pass

    def test_no_quant_live_env_var_in_research(self) -> None:
        """Verify research modules don't reference QUANT_LIVE env var."""
        import quant_us.research
        pkg_path = quant_us.research.__file__
        if pkg_path:
            pkg_dir = pkg_path.replace("__init__.py", "") if "__init__.py" in pkg_path else None
            if pkg_dir:
                import os
                for root, _dirs, files in os.walk(pkg_dir):
                    for fname in files:
                        if fname.endswith(".py"):
                            fpath = os.path.join(root, fname)
                            try:
                                with open(fpath, encoding="utf-8") as f:
                                    content = f.read()
                                self.assertNotIn(
                                    "QUANT_LIVE", content,
                                    f"Found QUANT_LIVE in {fpath}"
                                )
                            except (FileNotFoundError, OSError):
                                pass

    def test_experiment_manager_has_no_submit_method(self) -> None:
        """ExperimentManager should not have any submit-like method."""
        from quant_us.research.lab.manifest import ExperimentManager
        forbidden_methods = [
            attr for attr in dir(ExperimentManager)
            if "submit" in attr.lower() or "order" in attr.lower()
        ]
        self.assertEqual(forbidden_methods, [])

    def test_no_broker_import_in_regime_module(self) -> None:
        """Regime module should not import broker code."""
        import quant_us.regime.detector as detector
        with open(detector.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        import re
        self.assertFalse(re.search(r'from\s+quant_us\.live\s+import', content), "Found live import")
        self.assertFalse(re.search(r'import\s+quant_us\.live', content), "Found live import")
        self.assertFalse(re.search(r'from\s+quant_us\.execution\s+import', content), "Found execution import")
        self.assertFalse(re.search(r'import\s+quant_us\.execution', content), "Found execution import")

    def test_no_broker_in_scorecard_module(self) -> None:
        """Scorecard module should not import broker code."""
        import quant_us.research.lab.scorecard as scorecard
        with open(scorecard.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        import re
        self.assertFalse(re.search(r'from\s+quant_us\.live\s+import', content), "Found live import")
        self.assertFalse(re.search(r'import\s+quant_us\.live', content), "Found live import")
        self.assertFalse(re.search(r'from\s+quant_us\.execution\s+import', content), "Found execution import")
        self.assertFalse(re.search(r'import\s+quant_us\.execution', content), "Found execution import")

    def test_no_broker_in_portfolio_construction(self) -> None:
        """Portfolio construction should not import broker code."""
        import quant_us.portfolio.construction.engine as engine
        with open(engine.__file__ or "", encoding="utf-8") as f:
            content = f.read()
        import re
        self.assertFalse(re.search(r'from\s+quant_us\.live\s+import', content), "Found live import")
        self.assertFalse(re.search(r'import\s+quant_us\.live', content), "Found live import")
        self.assertFalse(re.search(r'from\s+quant_us\.execution\s+import', content), "Found execution import")
        self.assertFalse(re.search(r'import\s+quant_us\.execution', content), "Found execution import")
        self.assertNotIn("submit_order", content)
