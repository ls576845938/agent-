"""Tests for factor report generation.

Covers: report generation, recommendation logic.
"""

from __future__ import annotations

import unittest


def _recommend_factor(ic: float, icir: float, quantile_monotonic: bool) -> str:
    """Generate a recommendation based on factor evaluation metrics.

    Returns one of: REJECT | RESEARCH_MORE | USABLE | STRONG
    """
    if abs(ic) < 0.02:
        return "REJECT"
    if icir < 0.5:
        return "RESEARCH_MORE"
    if not quantile_monotonic:
        return "RESEARCH_MORE"
    if abs(ic) > 0.1 and icir > 1.0:
        return "STRONG"
    return "USABLE"


def _generate_factor_report(factor_id: str, ic: float, icir: float) -> str:
    """Generate a simple markdown factor report."""
    rec = _recommend_factor(ic, icir, True)
    lines = [
        f"# Factor Report: {factor_id}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| IC | {ic:.4f} |",
        f"| ICIR | {icir:.4f} |",
        f"| Recommendation | {rec} |",
        "",
    ]
    return "\n".join(lines)


class TestFactorRecommendation(unittest.TestCase):
    """Factor recommendation logic tests."""

    def test_strong_factor(self) -> None:
        rec = _recommend_factor(0.12, 1.5, True)
        self.assertEqual(rec, "STRONG")

    def test_usable_factor(self) -> None:
        rec = _recommend_factor(0.05, 0.8, True)
        self.assertEqual(rec, "USABLE")

    def test_reject_low_ic(self) -> None:
        rec = _recommend_factor(0.01, 0.5, True)
        self.assertEqual(rec, "REJECT")

    def test_reject_negative_low_ic(self) -> None:
        rec = _recommend_factor(-0.01, 0.3, True)
        self.assertEqual(rec, "REJECT")

    def test_research_more_low_icir(self) -> None:
        rec = _recommend_factor(0.05, 0.3, True)
        self.assertEqual(rec, "RESEARCH_MORE")

    def test_research_more_non_monotonic(self) -> None:
        rec = _recommend_factor(0.08, 1.0, False)
        self.assertEqual(rec, "RESEARCH_MORE")


class TestFactorReport(unittest.TestCase):
    """Factor report generation tests."""

    def test_report_contains_factor_id(self) -> None:
        report = _generate_factor_report("momentum_60d", 0.08, 1.2)
        self.assertIn("momentum_60d", report)

    def test_report_contains_metrics(self) -> None:
        report = _generate_factor_report("test", 0.08, 1.2)
        self.assertIn("IC", report)
        self.assertIn("ICIR", report)
        self.assertIn("Recommendation", report)

    def test_report_contains_recommendation(self) -> None:
        report = _generate_factor_report("test", 0.12, 1.5)
        self.assertIn("STRONG", report)

    def test_report_contains_recommendation_reject(self) -> None:
        report = _generate_factor_report("test", 0.01, 0.1)
        self.assertIn("REJECT", report)

    def test_report_markdown_format(self) -> None:
        report = _generate_factor_report("test", 0.08, 1.2)
        self.assertTrue(report.startswith("#"))
        self.assertIn("|", report)

    def test_report_handles_negative_ic(self) -> None:
        report = _generate_factor_report("test", -0.05, -0.8)
        self.assertIn("-0.05", report)
