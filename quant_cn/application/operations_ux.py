"""Application projection for the CN operator read model."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from quant_cn.operations.read_model import (
    CNOperatorReadModel,
    CNUpstreamEvidence,
    aggregate_cn_operator_blockers,
)


def build_cn_operations_read_model(
    *,
    upstream_evidence: Sequence[CNUpstreamEvidence],
    current_head: str,
    generated_at: datetime,
    data_version: str = "unavailable",
) -> CNOperatorReadModel:
    """Build a deterministic read-only view without touching runtime state."""

    evidence = tuple(upstream_evidence)
    return CNOperatorReadModel(
        code_commit=current_head,
        generated_at=generated_at,
        evidence=evidence,
        blockers=aggregate_cn_operator_blockers(evidence),
        data_version=data_version,
    )


__all__ = ["build_cn_operations_read_model"]
