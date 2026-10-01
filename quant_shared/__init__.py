"""Asset-neutral infrastructure contracts shared by quant domains.

The package intentionally exposes no broker, order-routing, paper, or live
capability. Asset domains adapt these stable infrastructure protocols at their
own boundary.
"""

SHARED_PLATFORM_VERSION = "shared_platform_v2"
SHARED_PLATFORM_V3_VERSION = "shared_platform_v3"
SHARED_PLATFORM_V3_CAPABILITIES = (
    "runtime_state",
    "action_authorization",
    "audit_event",
    "read_model_envelope",
)


def discover_shared_platform() -> dict[str, object]:
    """Return additive version/capability discovery metadata.

    The V2 symbol remains the compatibility source for existing consumers;
    callers opt into V3 through this separate discovery function.
    """

    return {
        "versions": {
            "v2": SHARED_PLATFORM_VERSION,
            "v3": SHARED_PLATFORM_V3_VERSION,
        },
        "v3_capabilities": SHARED_PLATFORM_V3_CAPABILITIES,
    }

__all__ = [
    "SHARED_PLATFORM_V3_CAPABILITIES",
    "SHARED_PLATFORM_V3_VERSION",
    "SHARED_PLATFORM_VERSION",
    "discover_shared_platform",
]
