"""
signal_check.py — Signal Quality

Evaluates whether a research target's signals are structurally sound, not purely
price-chasing, and contain appropriate volume confirmation, timeframe clarity,
historical sample support, and catalyst-vs-trend distinction.
"""

from typing import Any

from .scoring import CheckResult


def _get_field(item, field_name: str, default=None):
    """Get a field from either a dataclass instance or a dict."""
    if isinstance(item, dict):
        return item.get(field_name, default)
    return getattr(item, field_name, default)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signals(target: Any) -> list[dict]:
    return getattr(target, "signals", None) or []


def _thesis(target: Any) -> str:
    return getattr(target, "thesis", None) or ""


def _backtest_summary(target: Any) -> Any:
    return getattr(target, "backtest_summary", None)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_not_price_chasing(target: Any) -> CheckResult:
    """Check that signals are not purely price/return/momentum driven."""
    signals = _signals(target)
    thesis = _thesis(target)

    # Price-chasing signal names
    price_keywords = {"price", "return", "momentum", "涨幅", "收益率", "动量"}
    has_price_signal = any(
        any(kw in (_get_field(sig, "name") or "").lower() for kw in price_keywords)
        for sig in signals
    )

    # Check for other factor diversity
    non_price_factors = {"fundamental", "valuation", "earnings", "pe", "pb", "roe",
                         "growth", "value", "quality", "dividend", "基本面", "估值", "盈利"}
    has_non_price_signal = any(
        any(kw in (_get_field(sig, "name") or "").lower() for kw in non_price_factors)
        for sig in signals
    )

    # Check thesis for price-chasing phrases without fundamental backing
    chasing_phrases = {"强势上涨", "突破新高", "连续涨停", "急速拉升"}
    fundamental_phrases = {"基本面", "盈利增长", "估值修复", "产能扩张", "市场份额",
                           "margin", "revenue growth", "cost reduction"}
    thesis_chasing = any(p in thesis for p in chasing_phrases)
    thesis_fundamental = any(p in thesis for p in fundamental_phrases)

    # No price-chasing signal present at all → clean
    if not has_price_signal:
        return CheckResult(
            check_name="not_price_chasing",
            passed=True,
            score=1.0,
            details="No price-chasing signals detected; signals are fundamentally grounded",
        )

    # Price signal is present — check for diversity / thesis backing
    if has_non_price_signal:
        return CheckResult(
            check_name="not_price_chasing",
            passed=True,
            score=0.5,
            details="Mixed signals — price and non-price factors both present",
        )

    # Only price signals — is there fundamental justification in the thesis?
    if thesis_fundamental:
        return CheckResult(
            check_name="not_price_chasing",
            passed=True,
            score=0.5,
            details="Signals are price-based but thesis provides fundamental context",
        )

    # Pure price-chasing
    flags = ["PRICE_CHASING"]
    details = "Pure price-chasing pattern detected"
    if thesis_chasing:
        details += "; thesis uses price-chasing language without fundamental basis"
    return CheckResult(
        check_name="not_price_chasing",
        passed=False,
        score=0.0,
        details=details,
        risk_flags=flags,
    )


def _check_volume_confirmation(target: Any) -> CheckResult:
    """Check that at least one signal references volume, capital flow, or relative strength."""
    signals = _signals(target)
    volume_kw = {"volume", "turnover", "flow", "capital", "资金", "成交",
                 "relative_strength", "rs", "量能", "换手", "资金流向"}

    confirmed = any(
        any(kw in (_get_field(sig, "name") or "").lower() for kw in volume_kw)
        for sig in signals
    )

    return CheckResult(
        check_name="volume_confirmation",
        passed=confirmed,
        score=1.0 if confirmed else 0.0,
        details="Volume/flow/relative-strength signal found" if confirmed
        else "No volume, capital flow, or relative strength signal detected",
        risk_flags=[] if confirmed else ["NO_VOLUME_CONFIRMATION"],
    )


_VALID_TIMEFRAMES = {"intraday", "daily", "weekly", "monthly", "quarterly", "annual"}


def _check_timeframe_clarity(target: Any) -> CheckResult:
    """Check that signals define a clear timeframe."""
    signals = _signals(target)
    if not signals:
        return CheckResult(
            check_name="timeframe_clarity",
            passed=True,  # vacuously true
            score=1.0,
            details="No signals to check timeframe on",
        )

    defined = sum(
        1 for sig in signals
        if (_get_field(sig, "timeframe") or "") in _VALID_TIMEFRAMES
    )
    ratio = defined / len(signals)
    passed = defined >= 1

    return CheckResult(
        check_name="timeframe_clarity",
        passed=passed,
        score=ratio,
        details=f"{defined}/{len(signals)} signals have a defined timeframe",
        risk_flags=[] if passed else ["UNDEFINED_TIMEFRAME"],
    )


def _check_historical_sample(target: Any) -> CheckResult:
    """Check that signals or backtest_summary contain historical evidence."""
    signals = _signals(target)
    backtest = _backtest_summary(target)

    # Check signal-level metadata
    history_keys = {"historical_win_rate", "backtest_sharpe", "sample_size"}
    signal_has_history = any(
        any(k in (sig or {}) for k in history_keys)
        for sig in signals
    )

    if backtest:
        return CheckResult(
            check_name="historical_sample",
            passed=True,
            score=1.0,
            details="backtest_summary present with historical performance data",
        )
    elif signal_has_history:
        return CheckResult(
            check_name="historical_sample",
            passed=True,
            score=0.5,
            details="Signal-level historical metadata found but no backtest_summary",
        )
    else:
        return CheckResult(
            check_name="historical_sample",
            passed=False,
            score=0.0,
            details="No historical performance or backtest data available",
            risk_flags=["NO_HISTORICAL_SAMPLE"],
        )


def _check_catalyst_vs_trend(target: Any) -> CheckResult:
    """Check that thesis distinguishes short-term catalyst from long-term trend."""
    thesis = _thesis(target)
    if not thesis:
        return CheckResult(
            check_name="catalyst_vs_trend",
            passed=False,
            score=0.0,
            details="No thesis provided to evaluate",
            risk_flags=["CATALYST_TREND_CONFLATION"],
        )

    # Keywords indicating timeframe distinction
    short_term_kw = {"短期", "short-term", "catalyst", "催化剂", "事件驱动"}
    long_term_kw = {"长期", "long-term", "structural", "结构性", "cyclical", "周期性", "趋势"}

    has_short = any(kw in thesis for kw in short_term_kw)
    has_long = any(kw in thesis for kw in long_term_kw)

    if has_short and has_long:
        return CheckResult(
            check_name="catalyst_vs_trend",
            passed=True,
            score=1.0,
            details="Thesis clearly distinguishes short-term catalyst from long-term trend",
        )
    elif has_short or has_long:
        return CheckResult(
            check_name="catalyst_vs_trend",
            passed=True,
            score=0.5,
            details="Implicit timeframe distinction present but not fully developed",
        )
    else:
        return CheckResult(
            check_name="catalyst_vs_trend",
            passed=False,
            score=0.0,
            details="No distinction between short-term catalyst and long-term logic",
            risk_flags=["CATALYST_TREND_CONFLATION"],
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_signal_checks(target: Any) -> list[CheckResult]:
    """Run all signal quality checks against a research target.

    Args:
        target: An object with optional attributes:
            .signals (list[dict]), .thesis (str), .backtest_summary (Any).

    Returns:
        list[CheckResult]: Results for all 5 signal checks.
    """
    signals = _signals(target)
    if not signals:
        return [
            CheckResult(
                check_name="no_signals_to_check",
                passed=True,
                score=0.5,
                details="No signals defined for this target — neutral assessment",
            ),
        ]

    return [
        _check_not_price_chasing(target),
        _check_volume_confirmation(target),
        _check_timeframe_clarity(target),
        _check_historical_sample(target),
        _check_catalyst_vs_trend(target),
    ]
