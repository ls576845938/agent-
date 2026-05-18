from __future__ import annotations

from pathlib import Path


REGISTRY_BUILDER = Path("scripts/build_global_research_registry.py")


def test_global_registry_builder_has_no_runtime_or_broker_imports() -> None:
    source = REGISTRY_BUILDER.read_text(encoding="utf-8")

    forbidden_imports = [
        "from quant_us.live",
        "import quant_us.live",
        "from quant_us.execution",
        "import quant_us.execution",
        "from backend.app.services.us_quant",
        "import backend.app.services.us_quant",
    ]
    for forbidden in forbidden_imports:
        assert forbidden not in source


def test_global_registry_builder_does_not_call_order_submission_surfaces() -> None:
    source = REGISTRY_BUILDER.read_text(encoding="utf-8")

    forbidden_runtime_tokens = [
        "AlpacaBroker(",
        "LiveRuntime(",
        "PaperRuntime(",
        "submit_order(",
        "place_order(",
        "create_order(",
    ]
    for forbidden in forbidden_runtime_tokens:
        assert forbidden not in source
