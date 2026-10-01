from __future__ import annotations

import json
from pathlib import Path

from scripts.init_us_equity_broker_credentials_local_review import (
    init_us_equity_broker_credentials_local_review,
)


def test_local_review_init_copies_safe_template_without_unlocking_live(tmp_path: Path) -> None:
    _write_template(tmp_path)

    payload = init_us_equity_broker_credentials_local_review(
        repo_root=tmp_path,
        report=Path("out/init.json"),
        generated_at="2026-06-28T00:00:00Z",
    )

    assert payload["status"] == "local_review_initialized"
    assert payload["blockers"] == []
    assert payload["local_review_exists_after"] is True
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    local_payload = json.loads((tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json").read_text(encoding="utf-8"))
    assert local_payload["order_permission_enabled"] is False
    assert local_payload["read_only_or_live_disabled"] is True
    assert "SECRET" not in json.dumps(local_payload)
    assert "account_number" not in json.dumps(local_payload)


def test_local_review_init_refuses_to_overwrite_existing_local_file(tmp_path: Path) -> None:
    _write_template(tmp_path)
    local = tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json"
    local.write_text('{"manual":"keep"}\n', encoding="utf-8")

    payload = init_us_equity_broker_credentials_local_review(
        repo_root=tmp_path,
        report=Path("out/init.json"),
        generated_at="2026-06-28T00:00:00Z",
    )

    assert payload["status"] == "local_review_init_blocked"
    assert "broker_credentials_local_review_already_exists" in payload["blockers"]
    assert json.loads(local.read_text(encoding="utf-8")) == {"manual": "keep"}


def test_local_review_init_blocks_secret_like_template_values(tmp_path: Path) -> None:
    _write_template(tmp_path, extra={"api_token": "SECRET_SHOULD_NOT_BE_COPIED"})

    payload = init_us_equity_broker_credentials_local_review(
        repo_root=tmp_path,
        report=Path("out/init.json"),
        generated_at="2026-06-28T00:00:00Z",
    )

    assert payload["status"] == "local_review_init_blocked"
    assert "broker_credentials_template_contains_secret_like_value" in payload["blockers"]
    assert not (tmp_path / "configs/execution/us_equity_broker_credentials_review.local.json").exists()


def _write_template(tmp_path: Path, extra: dict[str, object] | None = None) -> None:
    payload: dict[str, object] = {
        "schema_version": "us_equity_broker_credentials_review_input_v1",
        "reviewer": "",
        "reviewed_at": "",
        "broker_name": "",
        "account_id_hash": "",
        "credential_storage": "outside_source_control",
        "api_key_present_in_repo": False,
        "secret_values_logged": False,
        "read_only_or_live_disabled": True,
        "order_permission_enabled": False,
        "private_endpoint_test_used": False,
        "order_endpoint_test_used": False,
        "funding_source_recorded_outside_repo": False,
        "manual_approval_ticket": "",
        "notes": "safe template",
    }
    if extra:
        payload.update(extra)
    path = tmp_path / "configs/execution/us_equity_broker_credentials_review.template.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
