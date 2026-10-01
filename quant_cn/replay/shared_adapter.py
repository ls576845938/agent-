"""Project a local replay into the integrated shared replay envelope."""

from __future__ import annotations

from quant_cn.compat.shared_adapter import (
    ReplayEventAdapterInput,
    ReplaySnapshotAdapterInput,
    build_replay_input,
)
from quant_cn.replay.engine import ReplayInput
from quant_shared.replay.contracts import ReplayInput as SharedReplayInput


def to_shared_replay_input(value: ReplayInput) -> SharedReplayInput:
    events = tuple(
        ReplayEventAdapterInput(
            event_id=f"order-{item.order_id}",
            occurred_at=item.created_at,
            event_type="order",
            domain_payload={
                "fingerprint": item.fingerprint,
                "stable_security_id": item.stable_security_id,
            },
        )
        for item in value.orders
    ) + tuple(
        ReplayEventAdapterInput(
            event_id=f"fill-{item.fill_id}",
            occurred_at=item.occurred_at,
            event_type="fill",
            domain_payload={
                "fingerprint": item.fingerprint,
                "stable_security_id": item.stable_security_id,
            },
        )
        for item in value.fills
    )
    snapshot = ReplaySnapshotAdapterInput(
        snapshot_id=f"opening-{value.replay_id}",
        as_of=min(
            (
                *(item.created_at for item in value.orders),
                value.fixed_clock,
            )
        ),
        data_version=value.source_ref,
        domain_payload={"opening_cash": str(value.opening_cash)},
    )
    return build_replay_input(
        replay_id=value.replay_id,
        fixed_clock=value.fixed_clock,
        random_seed=value.seed,
        snapshots=(snapshot,),
        events=events,
        parameters={"source_mode": value.source_mode},
    )
