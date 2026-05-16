"""
Alpha Radar Research Credibility Audit Engine.

Evaluates the credibility of investment research by analyzing four dimensions:

    - **Evidence chain integrity**   — source diversity, freshness, mapping
    - **Signal quality**             — methodology, volume confirmation, timeframe clarity
    - **Narrative logic**            — chain path, profit drivers, direction clarity
    - **Cognitive bias detection**   — hindsight, confirmation, hot-chasing, etc.

Each dimension produces a score in [0.0, 1.0]; a weighted composite maps to
[0.0, 100.0].  The final audit status is one of:

    BLOCKED | WATCHLIST | NEED_MORE_EVIDENCE | RESEARCH_READY | HIGH_CONVICTION

Usage:

    from alpha_radar.backend.research_audit import run_research_audit, ResearchAuditTarget, EvidenceItem

    target = ResearchAuditTarget(
        target_type="signal",
        target_id="ai_semi_2026q2",
        title="AI Semiconductor Capex Upswing",
        thesis="...",
        evidence_items=[EvidenceItem(...), ...],
        signals=[{"name": "semiconductor_equipment_orders", "direction": "positive", ...}],
    )
    result = run_research_audit(target)
    print(result.audit_status, result.audit_score)
"""

from .schemas import EvidenceItem, ResearchAuditTarget, ResearchAuditResult
from .runner import run_research_audit

# Convenience type alias — values are the five status strings above.
AuditStatus = str
