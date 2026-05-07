from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quant_us.core.clock import utc_now
from quant_us.core.types import new_id
from quant_us.live.modes import RuntimeMode


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    mode: RuntimeMode
    message: str = ""
    timestamp_utc: datetime = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: new_id("rtevt"))
