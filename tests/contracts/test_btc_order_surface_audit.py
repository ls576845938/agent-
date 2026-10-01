from __future__ import annotations

from pathlib import Path

from quant_crypto.monitoring.order_surface_audit import audit_btc_direct_order_call_surface


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_btc_real_quant_crypto_sources_do_not_expose_non_oms_order_surface() -> None:
    source_files = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / "quant_crypto").rglob("*.py"))
    }

    payload = audit_btc_direct_order_call_surface(source_files)

    assert payload["status"] == "complete"
    assert payload["decision"] == "non_oms_order_surface_clean"
    assert payload["blockers"] == []
    assert payload["findings"] == []
    assert len(payload["artifact_hash"]) == 64
    assert len(payload["input_hashes"]["source_files"]) == 64


def test_btc_order_surface_audit_blocks_direct_private_order_calls_outside_oms() -> None:
    payload = audit_btc_direct_order_call_surface(
        {
            "quant_crypto/research/btc_strategy.py": "\n".join(
                [
                    "import ccxt",
                    'ORDER_ENDPOINT = "/api/v5/trade/order"',
                    "live_order_allowed = True",
                    "exchange.create_order('BTC/USDT', 'market', 'buy', 1)",
                ]
            ),
            "quant_crypto/oms/lifecycle.py": "def create_order(order_intent):\n    return order_intent\n",
        }
    )

    assert payload["status"] == "blocked"
    assert payload["decision"] == "freeze_or_wrap_non_oms_order_surface"
    rules = {finding["rule"] for finding in payload["findings"]}
    assert rules == {
        "broker_sdk_import",
        "private_or_order_endpoint_literal",
        "unsafe_live_order_flag",
        "direct_order_call",
    }
    assert all("quant_crypto/research/btc_strategy.py" in blocker for blocker in payload["blockers"])


def test_btc_order_surface_audit_allows_paper_oms_order_lifecycle_boundary() -> None:
    payload = audit_btc_direct_order_call_surface(
        {
            "quant_crypto/oms/lifecycle.py": "\n".join(
                [
                    "class BTCPaperOMS:",
                    "    def create_order(self, order_intent):",
                    "        return order_intent",
                    "    def cancel_order(self, client_order_id):",
                    "        return client_order_id",
                ]
            ),
            "quant_crypto/portfolio/order_intent.py": "intent = {'source_boundary': 'no_broker_submit'}",
        }
    )

    assert payload["status"] == "complete"
    assert payload["findings"] == []
