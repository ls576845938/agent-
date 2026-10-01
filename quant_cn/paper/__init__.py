"""Offline-only CN paper-readiness closure contracts."""

from quant_cn.paper.readiness import (
    PAPER_SAFETY_FLAGS,
    OfflineKillSwitch,
    OfflinePaperFixture,
    PaperDrillResult,
    build_offline_fixture,
    run_offline_paper_drill,
)

__all__ = [
    "PAPER_SAFETY_FLAGS",
    "OfflineKillSwitch",
    "OfflinePaperFixture",
    "PaperDrillResult",
    "build_offline_fixture",
    "run_offline_paper_drill",
]
