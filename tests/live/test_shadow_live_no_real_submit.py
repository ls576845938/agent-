from __future__ import annotations

import pytest

from quant_us.live.shadow_live import ShadowLiveConfig


def test_shadow_live_config_rejects_real_order_submission_flag() -> None:
    with pytest.raises(ValueError, match="submit_real_orders MUST be False"):
        ShadowLiveConfig(submit_real_orders=True)
