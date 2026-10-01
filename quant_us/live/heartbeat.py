from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quant_us.core.clock import utc_now


@dataclass
class Heartbeat:
    service_name: str
    last_seen: datetime = field(default_factory=utc_now)

    def beat(self) -> datetime:
        self.last_seen = utc_now()
        return self.last_seen
