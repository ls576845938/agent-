from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_PROVIDER = "binance_usdm"


def selected_btc_perpetual_provider(config_path: Path) -> tuple[str, dict[str, Any]]:
    """Return the explicitly selected BTC perpetual provider config.

    The legacy config only contained ``providers.binance_usdm``. Newer configs
    may set ``selected_provider`` at the top level. When absent, preserve the
    legacy Binance default unless exactly one provider is enabled.
    """

    if not config_path.exists():
        return DEFAULT_PROVIDER, {}
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    providers = _mapping(payload.get("providers"))
    selected = str(payload.get("selected_provider") or payload.get("active_provider") or "").strip()
    if selected:
        return selected, _mapping(providers.get(selected))

    enabled = [
        name
        for name, provider in providers.items()
        if isinstance(name, str) and _mapping(provider).get("enabled") is True
    ]
    if len(enabled) == 1:
        name = enabled[0]
        return name, _mapping(providers.get(name))

    return DEFAULT_PROVIDER, _mapping(providers.get(DEFAULT_PROVIDER))


def selected_btc_perpetual_bundle_dir(repo_root: Path, config_path: Path) -> Path | None:
    provider_name, provider = selected_btc_perpetual_provider(config_path)
    selected_bundle_id = str(provider.get("selected_bundle_id", "") or "").strip()
    if not selected_bundle_id:
        return None
    bundle_root = repo_root / str(provider.get("root", default_provider_root(provider_name))) / "bundles"
    return bundle_root / selected_bundle_id


def default_provider_root(provider_name: str) -> str:
    return f"data/external/btc_perpetual/{provider_name}/"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
