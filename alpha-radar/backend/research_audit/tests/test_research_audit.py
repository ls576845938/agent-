"""Tests for Alpha Radar Research Credibility Audit Engine.

Covers: evidence chain, signal quality, narrative logic, bias detection,
scoring, promotion gate, full pipeline, and module independence.
"""

import json
import sys
from pathlib import Path

# Ensure alpha-radar/ is on sys.path
_PROJECT_DIR = Path(__file__).resolve().parents[4]  # alpha-radar/
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from backend.research_audit.schemas import (
    EvidenceItem,
    ResearchAuditTarget,
    ResearchAuditResult,
    validate_target,
    VALID_SOURCE_TYPES,
    VALID_TARGET_TYPES,
    VALID_DIRECTIONS,
    VALID_FRESHNESS,
    VALID_AUDIT_STATUSES,
    SIGNAL_REQUIRED_KEYS,
)
from backend.research_audit.scoring import (
    CheckResult,
    compute_dimension_score,
    compute_audit_score,
)
from backend.research_audit.evidence_check import run_evidence_checks
from backend.research_audit.signal_check import run_signal_checks
from backend.research_audit.narrative_check import run_narrative_checks
from backend.research_audit.bias_check import run_bias_checks
from backend.research_audit.promotion_gate import determine_status
from backend.research_audit.runner import run_research_audit


# ============================================================================
# Fixtures
# ============================================================================

def make_good_ai_compute_target():
    """Fixture 1: Well-formed AI compute industry chain signal."""
    return ResearchAuditTarget(
        target_type="signal",
        target_id="ai_compute_chain_2026q2",
        title="AI Compute Industry Chain - Upstream Chip Demand",
        thesis=(
            "上游芯片需求受益于AI算力投资，带动中游服务器出货量增长，"
            "但下游应用端短期利润驱动尚未明确。NVDA和AMD受益于数据中心资本开支扩张，"
            "但需关注SMCI库存风险。如果下游AI应用变现不及预期，上游芯片订单可能回调。"
        ),
        related_symbols=["NVDA", "AMD", "SMCI", "MU"],
        related_industries=["Semiconductors", "AI Infrastructure"],
        related_chain_nodes=["upstream_chip", "midstream_server", "downstream_ai_app"],
        evidence_items=[
            EvidenceItem(source_type="news", source_name="Bloomberg",
                         publish_time="2026-05-10T08:00:00Z",
                         claim="TSMC raises Q2 guidance on AI chip demand",
                         affected_targets=["NVDA", "AMD", "TSMC"],
                         direction="positive", confidence=0.85, freshness="recent"),
            EvidenceItem(source_type="filing", source_name="SEC EDGAR",
                         publish_time="2026-05-08T00:00:00Z",
                         claim="NVDA 10-Q shows data center revenue +200% YoY",
                         affected_targets=["NVDA"],
                         direction="positive", confidence=0.95, freshness="recent"),
            EvidenceItem(source_type="industry_data", source_name="Wind",
                         publish_time="2026-05-05T00:00:00Z",
                         claim="Server shipment growth slowing, memory prices declining",
                         affected_targets=["SMCI", "MU"],
                         direction="negative", confidence=0.70, freshness="moderate"),
        ],
        signals=[
            {"name": "semiconductor_equipment_orders", "direction": "positive", "timeframe": "quarterly"},
            {"name": "volume_anomaly_NVDA", "direction": "positive", "timeframe": "daily"},
        ],
        metadata={"failure_conditions": ["AI capex growth decelerates below 20% YoY"],
                  "signal_date": "2026-05-01"},
    )


def make_good_optical_stock_pool_target():
    """Fixture 2: Well-formed optical module stock pool rule."""
    return ResearchAuditTarget(
        target_type="stock_pool",
        target_id="optical_module_pool_001",
        title="Optical Module 800G Upgrade Cycle Stock Pool",
        thesis=(
            "800G光模块升级周期驱动上游光芯片和中游光模块厂商利润增长。"
            "下游数据中心客户资本开支持续扩张，受益标的包括中际旭创、新易盛、天孚通信。"
            "短期催化剂：英伟达GB300发布；长期逻辑：AI集群向800G/1.6T升级。"
            "如果光模块价格跌幅超预期或下游砍单，则逻辑失效。"
        ),
        related_symbols=["300308", "300502", "300394"],
        related_industries=["Optical Communication", "AI Hardware"],
        related_chain_nodes=["upstream_optical_chip", "midstream_module", "downstream_datacenter"],
        evidence_items=[
            EvidenceItem(source_type="industry_data", source_name="LightCounting",
                         publish_time="2026-04-20T00:00:00Z",
                         claim="800G optical module shipments to exceed 10M units in 2026",
                         affected_targets=["300308", "300502"],
                         direction="positive", confidence=0.80, freshness="moderate"),
            EvidenceItem(source_type="financial", source_name="Company Filings",
                         publish_time="2026-04-25T00:00:00Z",
                         claim="中际旭创Q1 revenue +80% YoY, gross margin expanding",
                         affected_targets=["300308"],
                         direction="positive", confidence=0.90, freshness="recent"),
            EvidenceItem(source_type="manual_note", source_name="Analyst Note",
                         claim="Optical component lead times extending, potential supply bottleneck",
                         affected_targets=["300394"],
                         direction="negative", confidence=0.60, freshness="recent"),
        ],
        signals=[
            {"name": "revenue_growth_qoq", "direction": "positive", "timeframe": "quarterly"},
            {"name": "capital_flow_institutional", "direction": "positive", "timeframe": "weekly"},
            {"name": "relative_strength_vs_sector", "direction": "positive", "timeframe": "daily"},
        ],
        backtest_summary={"sharpe": 1.8, "win_rate": 0.65, "sample_size": 120},
        metadata={"failure_conditions": ["800G adoption rate below 30% by Q4 2026"],
                  "signal_date": "2026-03-15"},
    )


def make_bad_ai_only_target():
    """Fixture 3: Poor-quality AI-generated-only conclusion."""
    return ResearchAuditTarget(
        target_type="signal",
        target_id="bad_ai_only_001",
        title="AI Hot Stock Pick",
        thesis="毫无疑问，AI是未来十年最大的投资机会，这个赛道必然会诞生万亿市值的公司。",
        related_symbols=[],
        related_industries=[],
        related_chain_nodes=[],
        evidence_items=[
            EvidenceItem(source_type="ai_generated", source_name="Claude Analysis",
                         claim="This stock will go up because of AI trend",
                         direction="positive", confidence=0.9, freshness="unknown"),
            EvidenceItem(source_type="ai_generated", source_name="Claude Analysis",
                         claim="Market sentiment is bullish on tech",
                         direction="positive", confidence=0.8, freshness="unknown"),
        ],
        signals=[
            {"name": "price_momentum", "direction": "positive"},
            {"name": "return_1m", "direction": "positive"},
        ],
    )


# ============================================================================
# Test Evidence Checks
# ============================================================================

class TestEvidenceChecks:
    def test_good_target_passes_critical_evidence_checks(self):
        target = make_good_ai_compute_target()
        results = run_evidence_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["min_independent_sources"].passed
        assert by_name["non_ai_source_present"].passed
        assert by_name["publish_time_traceability"].passed
        assert by_name["counter_evidence_present"].passed

    def test_bad_target_fails_critical_evidence_checks(self):
        target = make_bad_ai_only_target()
        results = run_evidence_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["min_independent_sources"].passed
        assert not by_name["non_ai_source_present"].passed
        assert "SINGLE_SOURCE_DEPENDENCY" in by_name["min_independent_sources"].risk_flags
        assert "AI_ONLY_EVIDENCE" in by_name["non_ai_source_present"].risk_flags

    def test_empty_evidence_fails(self):
        target = ResearchAuditTarget(target_type="signal", target_id="empty_test",
                                     title="Empty", thesis="Nothing")
        results = run_evidence_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["min_independent_sources"].passed
        assert by_name["min_independent_sources"].score == 0.0

    def test_optical_pool_passes_evidence_checks(self):
        target = make_good_optical_stock_pool_target()
        results = run_evidence_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["min_independent_sources"].passed
        assert by_name["non_ai_source_present"].passed
        assert by_name["publish_time_traceability"].passed
        assert by_name["source_freshness"].passed

    def test_target_mapping_mismatch_flagged(self):
        target = ResearchAuditTarget(
            target_type="signal", target_id="mismatch-001", thesis="test",
            evidence_items=[
                EvidenceItem(source_type="news", source_name="Bloomberg",
                             affected_targets=["GOOGL"], direction="positive"),
                EvidenceItem(source_type="news", source_name="Reuters",
                             affected_targets=["GOOGL"], direction="positive"),
            ],
            related_symbols=["AAPL", "MSFT"],
        )
        results = run_evidence_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["target_mapping"].passed
        assert "EVIDENCE_TARGET_MISMATCH" in by_name["target_mapping"].risk_flags

    def test_min_independent_sources_scoring(self):
        """Verify score differentiation: 3+ sources=1.0, 2 sources=0.5, <2=0.0."""
        t0 = ResearchAuditTarget(target_type="signal", target_id="t0")
        r0 = {r.check_name: r for r in run_evidence_checks(t0)}
        assert r0["min_independent_sources"].score == 0.0

        # Two sources -> score 0.5
        t2 = ResearchAuditTarget(
            target_type="signal", target_id="t2",
            evidence_items=[
                EvidenceItem(source_type="news", source_name="Bloomberg",
                             direction="positive"),
                EvidenceItem(source_type="news", source_name="Reuters",
                             direction="neutral"),
            ],
        )
        r2 = {r.check_name: r for r in run_evidence_checks(t2)}
        assert r2["min_independent_sources"].passed
        assert r2["min_independent_sources"].score == 0.5

        # Good target has 3+ unique sources
        r3 = {r.check_name: r for r in run_evidence_checks(make_good_ai_compute_target())}
        assert r3["min_independent_sources"].passed
        assert r3["min_independent_sources"].score == 1.0


# ============================================================================
# Test Signal Checks
# ============================================================================

class TestSignalChecks:
    def test_price_chasing_detected(self):
        target = make_bad_ai_only_target()
        results = run_signal_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["not_price_chasing"].passed
        assert "PRICE_CHASING" in by_name["not_price_chasing"].risk_flags

    def test_no_volume_confirmation_detected(self):
        target = make_bad_ai_only_target()
        results = run_signal_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["volume_confirmation"].passed

    def test_timeframe_clarity_fails_for_undefined(self):
        target = make_bad_ai_only_target()
        results = run_signal_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["timeframe_clarity"].passed

    def test_optical_pool_has_good_signals(self):
        target = make_good_optical_stock_pool_target()
        results = run_signal_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["volume_confirmation"].passed
        assert by_name["historical_sample"].passed
        assert by_name["timeframe_clarity"].passed

    def test_good_ai_compute_passes_most_signals(self):
        target = make_good_ai_compute_target()
        results = run_signal_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["not_price_chasing"].passed
        assert by_name["volume_confirmation"].passed
        assert by_name["timeframe_clarity"].passed
        assert by_name["catalyst_vs_trend"].passed
        # historical_sample fails because the fixture lacks backtest_summary
        # (deliberately — it tests that the pipeline flags missing history)

    def test_empty_signals_returns_neutral(self):
        target = ResearchAuditTarget(target_type="signal", target_id="no_sig")
        results = run_signal_checks(target)
        assert len(results) == 1
        assert results[0].check_name == "no_signals_to_check"
        assert results[0].score == 0.5


# ============================================================================
# Test Narrative Checks
# ============================================================================

class TestNarrativeChecks:
    def test_chain_path_clarity_passes(self):
        target = make_good_ai_compute_target()
        results = run_narrative_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["chain_path_clarity"].passed

    def test_profit_driver_identified(self):
        target = make_good_ai_compute_target()
        results = run_narrative_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["profit_driver_identified"].passed

    def test_grand_narrative_detected(self):
        target = make_bad_ai_only_target()
        results = run_narrative_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["chain_path_clarity"].passed
        assert not by_name["profit_driver_identified"].passed

    def test_optical_pool_narrative_passes(self):
        target = make_good_optical_stock_pool_target()
        results = run_narrative_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["chain_path_clarity"].passed
        assert by_name["profit_driver_identified"].passed
        assert by_name["direction_clarity"].passed


# ============================================================================
# Test Bias Checks
# ============================================================================

class TestBiasChecks:
    def test_single_source_bias_detected(self):
        target = make_bad_ai_only_target()
        results = run_bias_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["single_source_dependency"].passed
        assert "SINGLE_SOURCE_BIAS" in by_name["single_source_dependency"].risk_flags

    def test_confirmation_bias_detected(self):
        target = make_bad_ai_only_target()
        results = run_bias_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["confirmatory_evidence_only"].passed
        assert "CONFIRMATION_BIAS" in by_name["confirmatory_evidence_only"].risk_flags

    def test_no_failure_conditions_detected(self):
        target = make_bad_ai_only_target()
        results = run_bias_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["no_failure_conditions"].passed

    def test_good_target_has_failure_conditions(self):
        target = make_good_ai_compute_target()
        results = run_bias_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["no_failure_conditions"].passed

    def test_hot_chasing_detected(self):
        target = ResearchAuditTarget(
            target_type="signal", target_id="hot-chase-001",
            thesis="AI and ChatGPT and LLM will revolutionize everything!",
        )
        results = run_bias_checks(target)
        by_name = {r.check_name: r for r in results}
        assert not by_name["hot_chasing"].passed
        assert "HOT_CHASING" in by_name["hot_chasing"].risk_flags

    def test_good_target_no_confirmation_bias(self):
        target = make_good_ai_compute_target()
        results = run_bias_checks(target)
        by_name = {r.check_name: r for r in results}
        assert by_name["confirmatory_evidence_only"].passed


# ============================================================================
# Test Scoring
# ============================================================================

class TestScoring:
    def test_dimension_score_average(self):
        results = [
            CheckResult("a", True, 1.0),
            CheckResult("b", False, 0.0),
            CheckResult("c", True, 0.5),
        ]
        assert compute_dimension_score(results) == 0.5

    def test_dimension_score_all_pass(self):
        results = [
            CheckResult("c1", True, 1.0),
            CheckResult("c2", True, 1.0),
        ]
        assert compute_dimension_score(results) == 1.0

    def test_dimension_score_empty(self):
        assert compute_dimension_score([]) == 0.0

    def test_composite_score_bounds(self):
        assert compute_audit_score(0.0, 0.0, 0.0, 0.0) == 0.0
        assert compute_audit_score(1.0, 1.0, 1.0, 1.0) == 100.0

    def test_composite_score_weighting(self):
        assert compute_audit_score(1.0, 0.0, 0.0, 0.0) == 35.0


# ============================================================================
# Test Promotion Gate
# ============================================================================

class TestPromotionGate:
    def test_blocked_for_low_evidence(self):
        assert determine_status(0.2, 0.8, 0.8, 0.8, [], []) == "BLOCKED"

    def test_blocked_for_critical_check_failed(self):
        assert determine_status(0.8, 0.8, 0.8, 0.8,
                                ["min_independent_sources"], []) == "BLOCKED"

    def test_high_conviction(self):
        assert determine_status(0.9, 0.9, 0.9, 0.9, [], []) == "HIGH_CONVICTION"

    def test_research_ready(self):
        assert determine_status(0.7, 0.7, 0.7, 0.7, [], ["warning"]) == "RESEARCH_READY"

    def test_need_more_evidence(self):
        assert determine_status(0.4, 0.7, 0.7, 0.7, [], []) == "NEED_MORE_EVIDENCE"

    def test_watchlist_default(self):
        assert determine_status(0.55, 0.55, 0.55, 0.55, [], []) == "WATCHLIST"


# ============================================================================
# Test Full Pipeline
# ============================================================================

class TestFullAuditPipeline:
    def test_good_target_produces_valid_result(self):
        target = make_good_ai_compute_target()
        result = run_research_audit(target)
        assert result.audit_id
        assert result.audit_score > 0
        assert result.audit_status in {
            "BLOCKED", "WATCHLIST", "NEED_MORE_EVIDENCE",
            "RESEARCH_READY", "HIGH_CONVICTION",
        }
        assert result.report_markdown
        assert result.report_json
        assert "target" in result.report_json

    def test_bad_target_blocked_with_low_score(self):
        target = make_bad_ai_only_target()
        result = run_research_audit(target)
        assert result.audit_status == "BLOCKED"
        assert result.audit_score < 50
        risk_flags = set(result.risk_flags)
        assert "SINGLE_SOURCE_DEPENDENCY" in risk_flags or "SINGLE_SOURCE_BIAS" in risk_flags
        assert "AI_ONLY_EVIDENCE" in risk_flags

    def test_optical_pool_passes_well(self):
        target = make_good_optical_stock_pool_target()
        result = run_research_audit(target)
        assert result.evidence_score >= 0.5
        assert result.signal_score >= 0.5
        assert result.audit_score >= 50

    def test_persistence(self, tmp_path):
        target = make_good_ai_compute_target()
        persist_dir = str(tmp_path / "audit_results")
        result = run_research_audit(target, persist_dir=persist_dir)
        saved_path = Path(persist_dir) / f"{result.audit_id}.json"
        assert saved_path.exists()
        saved = json.loads(saved_path.read_text())
        assert saved["audit_id"] == result.audit_id

    def test_report_markdown_has_expected_sections(self):
        target = make_good_ai_compute_target()
        result = run_research_audit(target)
        assert "Research Audit Report" in result.report_markdown
        assert "Evidence Chain" in result.report_markdown
        assert "Signal Quality" in result.report_markdown
        assert "Recommendation" in result.report_markdown


# ============================================================================
# Test Module Independence
# ============================================================================

class TestModuleIndependence:
    def test_no_quant_us_in_source(self):
        """Verify no quant_us imports in research_audit source files (excluding tests)."""
        research_audit_dir = Path(__file__).resolve().parents[1]
        violations = []
        for py_file in research_audit_dir.rglob("*.py"):
            # Skip the tests directory itself
            if "tests" in py_file.parts:
                continue
            content = py_file.read_text()
            if "from quant_us" in content or "import quant_us" in content:
                violations.append(str(py_file.relative_to(research_audit_dir.parent.parent)))
        assert not violations, f"quant_us imports found in: {violations}"

    def test_schemas_roundtrip(self):
        target = make_good_ai_compute_target()
        d = target.to_dict()
        target2 = ResearchAuditTarget.from_dict(d)
        assert target2.target_id == target.target_id
        assert len(target2.evidence_items) == len(target.evidence_items)

    def test_result_roundtrip(self):
        target = make_good_ai_compute_target()
        result = run_research_audit(target)
        d = result.to_dict()
        result2 = ResearchAuditResult.from_dict(d)
        assert result2.audit_id == result.audit_id
        assert result2.audit_status == result.audit_status

    def test_validate_target_catches_errors(self):
        target = ResearchAuditTarget(target_type="invalid_type", target_id="")
        errors = validate_target(target)
        assert len(errors) > 0

    def test_validate_target_passes_good(self):
        target = make_good_ai_compute_target()
        errors = validate_target(target)
        assert len(errors) == 0

    def test_constants_are_immutable(self):
        assert isinstance(VALID_SOURCE_TYPES, frozenset)
        assert isinstance(VALID_TARGET_TYPES, frozenset)
        assert isinstance(VALID_DIRECTIONS, frozenset)
        assert isinstance(VALID_FRESHNESS, frozenset)
        assert isinstance(VALID_AUDIT_STATUSES, frozenset)
        assert isinstance(SIGNAL_REQUIRED_KEYS, frozenset)

    def test_validate_target_rejects_invalid_evidence_source_type(self):
        target = ResearchAuditTarget(
            target_type="signal", target_id="bad-source",
            evidence_items=[
                EvidenceItem(source_type="bogus_type", source_name="X"),
            ],
        )
        errors = validate_target(target)
        assert any("source_type" in e for e in errors)

    def test_validate_target_rejects_invalid_signal_direction(self):
        target = ResearchAuditTarget(
            target_type="signal", target_id="bad-dir",
            signals=[{"name": "sig", "direction": "super_bullish"}],
        )
        errors = validate_target(target)
        assert any("direction" in e for e in errors)
