from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from quant_cn.market.rules import (
    BOARD_LOT,
    FEE_SCHEDULE,
    PRICE_LIMIT,
    RULE_AMBIGUOUS,
    RULE_EXPIRED,
    RULE_MISSING,
    RULE_NOT_AVAILABLE,
    RULE_NOT_YET_EFFECTIVE,
    RULE_OVERLAP,
    RULE_RESOLVED,
    SELLABILITY,
    BoardLotPolicy,
    EffectiveRuleBook,
    FeeComponent,
    FeePolicy,
    MarketDimensions,
    PriceLimitPolicy,
    SellabilityPolicy,
)

from .factories import (
    AS_OF,
    EFFECTIVE_FROM,
    EFFECTIVE_TO,
    dimensions_for,
    make_record,
    make_rule,
)


def test_effective_interval_is_start_inclusive_end_exclusive() -> None:
    dimensions = dimensions_for(make_record())
    book = EffectiveRuleBook((make_rule(PRICE_LIMIT, dimensions),))
    assert book.resolve(
        PRICE_LIMIT,
        dimensions=dimensions,
        as_of=EFFECTIVE_FROM,
    ).status == RULE_RESOLVED
    assert book.resolve(
        PRICE_LIMIT,
        dimensions=dimensions,
        as_of=EFFECTIVE_TO,
    ).status == RULE_EXPIRED


def test_resolution_distinguishes_missing_future_and_invisible() -> None:
    dimensions = dimensions_for(make_record())
    other = MarketDimensions("XSHE", "main", "cash_equity", "common_stock", "other")
    book = EffectiveRuleBook((make_rule(PRICE_LIMIT, dimensions),))
    assert book.resolve(
        PRICE_LIMIT,
        dimensions=other,
        as_of=AS_OF,
    ).status == RULE_MISSING
    assert book.resolve(
        PRICE_LIMIT,
        dimensions=dimensions,
        as_of=EFFECTIVE_FROM - timedelta(microseconds=1),
    ).status == RULE_NOT_YET_EFFECTIVE

    invisible = make_rule(
        PRICE_LIMIT,
        dimensions,
        version="future-version",
        available_time=AS_OF + timedelta(seconds=1),
        ingested_at=AS_OF + timedelta(seconds=2),
        processed_at=AS_OF + timedelta(seconds=3),
    )
    result = EffectiveRuleBook((invisible,)).resolve(
        PRICE_LIMIT,
        dimensions=dimensions,
        as_of=AS_OF,
    )
    assert result.status == RULE_NOT_AVAILABLE
    assert result.versions == ()
    assert result.rule is None


def test_overlap_and_multi_dimension_matches_fail_closed() -> None:
    record = make_record()
    exact = dimensions_for(record)
    dimension_level = dimensions_for(record, security_id=False)
    overlap = EffectiveRuleBook(
        (
            make_rule(PRICE_LIMIT, exact, version="one"),
            make_rule(PRICE_LIMIT, exact, version="two"),
        )
    ).resolve(PRICE_LIMIT, dimensions=exact, as_of=AS_OF)
    assert overlap.status == RULE_OVERLAP

    ambiguous = EffectiveRuleBook(
        (
            make_rule(BOARD_LOT, exact, version="security"),
            make_rule(BOARD_LOT, dimension_level, version="dimension"),
        )
    ).resolve(BOARD_LOT, dimensions=exact, as_of=AS_OF)
    assert ambiguous.status == RULE_AMBIGUOUS


def test_policy_types_do_not_hide_market_defaults() -> None:
    with pytest.raises(TypeError, match="^decimal_required:upper_ratio$"):
        PriceLimitPolicy(True, 0.1, Decimal("0.10"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="^fee_policy_buy_must_be_non_empty$"):
        FeePolicy(
            buy=(),
            sell=(
                FeeComponent(
                    "explicit_zero",
                    Decimal("0"),
                    Decimal("0"),
                    Decimal("0"),
                ),
            ),
        )
    assert BoardLotPolicy(100, 100, True).buy_lot_size == 100
    assert SellabilityPolicy(0).sellable_after_sessions == 0


def test_distinct_dimensions_require_distinct_injected_rules() -> None:
    main = MarketDimensions("XSHG", "main", "cash_equity", "common_stock", "main")
    growth = MarketDimensions("XSHE", "growth", "cash_equity", "common_stock", "growth")
    fund = MarketDimensions("XSHG", "fund", "etf", "fund", "fund")

    rules = (
        make_rule(
            PRICE_LIMIT,
            main,
            payload=PriceLimitPolicy(True, Decimal("0.10"), Decimal("0.10")),
        ),
        make_rule(
            PRICE_LIMIT,
            growth,
            payload=PriceLimitPolicy(True, Decimal("0.20"), Decimal("0.20")),
        ),
        make_rule(
            PRICE_LIMIT,
            fund,
            payload=PriceLimitPolicy(False, None, None),
        ),
        make_rule(BOARD_LOT, main, payload=BoardLotPolicy(100, 100, True)),
        make_rule(SELLABILITY, main, payload=SellabilityPolicy(1)),
        make_rule(
            FEE_SCHEDULE,
            main,
            payload=FeePolicy(
                buy=(FeeComponent("fee", Decimal("0"), Decimal("0"), Decimal("0")),),
                sell=(FeeComponent("fee", Decimal("0"), Decimal("0"), Decimal("0")),),
            ),
        ),
    )
    book = EffectiveRuleBook(rules)
    assert book.resolve(PRICE_LIMIT, dimensions=main, as_of=AS_OF).rule.payload.upper_ratio == (
        Decimal("0.10")
    )
    assert book.resolve(
        PRICE_LIMIT,
        dimensions=growth,
        as_of=AS_OF,
    ).rule.payload.upper_ratio == Decimal("0.20")
    assert not book.resolve(
        PRICE_LIMIT,
        dimensions=fund,
        as_of=AS_OF,
    ).rule.payload.has_price_limit
    unmatched = MarketDimensions("XSHG", "main", "etf", "fund", "unknown-id")
    assert book.resolve(
        PRICE_LIMIT,
        dimensions=unmatched,
        as_of=AS_OF,
    ).status == RULE_MISSING


def test_rule_metadata_is_utc_aware_ordered_and_hashed() -> None:
    dimensions = dimensions_for(make_record())
    with pytest.raises(ValueError, match="^rule_ingested_at_after_processed_at$"):
        make_rule(
            PRICE_LIMIT,
            dimensions,
            ingested_at=AS_OF,
            processed_at=AS_OF - timedelta(seconds=1),
        )
    with pytest.raises(
        ValueError,
        match="^checksum_must_be_lowercase_sha256:rule.checksum$",
    ):
        make_rule(PRICE_LIMIT, dimensions, checksum="C" * 64)
