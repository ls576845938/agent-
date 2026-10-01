from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.api.btc_outbound_path_redaction import (
    BtcOutboundPathRedactionError,
    REDACTED_PHYSICAL_PATH,
    sanitize_btc_outbound_payload,
)


def test_recursive_path_redaction_preserves_non_path_semantics(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    artifact_root = tmp_path / "runtime-artifacts"
    repo_path = repo_root / "reports" / "control.json"
    artifact_path = artifact_root / "runs" / "gate.json"
    outside_path = tmp_path / "outside" / "market.sqlite"

    payload = {
        "status": "blocked_fail_closed",
        "decision": "btc_research_only_no_paper_no_live",
        "blockers": ["runtime artifact missing"],
        "source_head": "a" * 40,
        "ordinary_text": "D drive diagnostics are unavailable",
        "endpoint": "/api/research/btc/control-center",
        "reports": [
            {
                "source_report_path": str(repo_path),
                "outputs": {
                    "gate": str(artifact_path),
                    "outside": str(outside_path),
                },
            },
            {
                "current_sqlite_coverage": {
                    "db_path": r"D:\quant\data\market.sqlite",
                },
                "selected_bundle_dir": "D:/quant/bundles/latest",
            },
            {
                "source_report_path": r"\\server\share\report.json",
                "selected_bundle_dir": "/srv/quant/private-bundle",
            },
        ],
    }

    sanitized = sanitize_btc_outbound_payload(
        payload,
        repo_root=repo_root,
        provenance_roots={"artifacts": artifact_root},
    )

    assert sanitized["status"] == payload["status"]
    assert sanitized["decision"] == payload["decision"]
    assert sanitized["blockers"] == payload["blockers"]
    assert sanitized["source_head"] == payload["source_head"]
    assert sanitized["ordinary_text"] == payload["ordinary_text"]
    assert sanitized["endpoint"] == payload["endpoint"]
    assert sanitized["reports"][0]["source_report_path"] == "reports/control.json"
    assert sanitized["reports"][0]["outputs"]["gate"] == "artifacts/runs/gate.json"
    assert sanitized["reports"][0]["outputs"]["outside"] == REDACTED_PHYSICAL_PATH
    assert (
        sanitized["reports"][1]["current_sqlite_coverage"]["db_path"]
        == REDACTED_PHYSICAL_PATH
    )
    assert sanitized["reports"][1]["selected_bundle_dir"] == REDACTED_PHYSICAL_PATH
    assert sanitized["reports"][2]["source_report_path"] == REDACTED_PHYSICAL_PATH
    assert sanitized["reports"][2]["selected_bundle_dir"] == REDACTED_PHYSICAL_PATH


def test_posix_repo_paths_are_logicalized_and_external_paths_are_redacted() -> None:
    sanitized = sanitize_btc_outbound_payload(
        {
            "source_report_path": "/srv/quant/repo/reports/status.json",
            "outputs": ["/srv/quant/runtime/gate.json"],
            "label": "ordinary/string",
        },
        repo_root="/srv/quant/repo",
    )

    assert sanitized == {
        "source_report_path": "reports/status.json",
        "outputs": [REDACTED_PHYSICAL_PATH],
        "label": "ordinary/string",
    }


def test_absolute_path_keys_fail_closed_on_redaction_collision() -> None:
    with pytest.raises(
        BtcOutboundPathRedactionError,
        match="btc_outbound_path_key_collision_fail_closed",
    ):
        sanitize_btc_outbound_payload(
            {
                "outputs": {
                    r"D:\private\first.json": 1,
                    r"E:\private\second.json": 2,
                },
            },
            repo_root=r"C:\quant\repo",
        )


@pytest.mark.parametrize(
    ("repo_root", "inside", "escaped", "inside_label"),
    [
        (
            "/srv/base/repo-root/../repo",
            "/srv/base/repo/sub/../inside/report.json",
            "/srv/base/repo/sub/../../secret/token.json",
            "inside/report.json",
        ),
        (
            r"C:\base\repo-root\..\repo",
            r"C:\base\repo\sub\..\inside\report.json",
            r"C:\base\repo\sub\..\..\secret\token.json",
            "inside/report.json",
        ),
        (
            r"\\server\share\base\repo-root\..\repo",
            r"\\server\share\base\repo\sub\..\inside\report.json",
            r"\\server\share\base\repo\sub\..\..\secret\token.json",
            "inside/report.json",
        ),
        (
            "/srv/repo",
            "/srv/repo/sub/../inside/report.json",
            "/srv/repo/../secret/token.json",
            "inside/report.json",
        ),
        (
            r"C:\repo",
            r"C:\repo\sub\..\inside\report.json",
            r"C:\repo\..\secret\token.json",
            "inside/report.json",
        ),
    ],
)
def test_lexical_normalization_blocks_escape_and_keeps_inside(
    repo_root: str,
    inside: str,
    escaped: str,
    inside_label: str,
) -> None:
    sanitized = sanitize_btc_outbound_payload(
        {
            "inside_path": inside,
            "escaped_path": escaped,
        },
        repo_root=repo_root,
    )

    assert sanitized["inside_path"] == inside_label
    assert sanitized["escaped_path"] == REDACTED_PHYSICAL_PATH


def test_provenance_root_is_lexically_normalized_before_containment() -> None:
    sanitized = sanitize_btc_outbound_payload(
        {
            "inside_path": "/srv/runtime/sub/../inside/report.json",
            "escaped_path": "/srv/runtime/sub/../../secret/token.json",
        },
        repo_root="/srv/repo",
        provenance_roots={"artifacts": "/srv/runtime/root/.."},
    )

    assert sanitized["inside_path"] == "artifacts/inside/report.json"
    assert sanitized["escaped_path"] == REDACTED_PHYSICAL_PATH


def test_normalized_mapping_key_collision_stays_fail_closed() -> None:
    with pytest.raises(
        BtcOutboundPathRedactionError,
        match="btc_outbound_path_key_collision_fail_closed",
    ):
        sanitize_btc_outbound_payload(
            {
                "outputs": {
                    "/srv/repo/first/../same.json": 1,
                    "/srv/repo/same.json": 2,
                },
            },
            repo_root="/srv/repo",
        )


@pytest.mark.parametrize(
    ("repo_root", "inside_uri", "escaped_uri", "inside_label"),
    [
        (
            "/srv/repo",
            "file:///srv/repo/sub/../inside/report.json",
            "file:///srv/repo/sub/../../secret/token.json",
            "inside/report.json",
        ),
        (
            r"C:\repo",
            "file:///C:/repo/sub/../inside/report.json",
            "file:///C:/repo/sub/../../secret/token.json",
            "inside/report.json",
        ),
        (
            r"\\server\share\repo",
            "file://server/share/repo/sub/../inside/report.json",
            "file://server/share/repo/sub/../../secret/token.json",
            "inside/report.json",
        ),
    ],
)
def test_file_uri_paths_are_normalized_without_physical_disclosure(
    repo_root: str,
    inside_uri: str,
    escaped_uri: str,
    inside_label: str,
) -> None:
    sanitized = sanitize_btc_outbound_payload(
        {
            "inside_path": inside_uri,
            "escaped_path": escaped_uri,
        },
        repo_root=repo_root,
    )

    assert sanitized["inside_path"] == inside_label
    assert sanitized["escaped_path"] == REDACTED_PHYSICAL_PATH


def test_embedded_paths_are_redacted_but_urls_hashes_and_strategy_text_survive() -> None:
    source_hash = "a" * 64
    payload = {
        "windows_error": r"read failed at D:\private\token.json",
        "unc_error": r"read failed at \\server\share\token.json",
        "posix_error": "read failed at /srv/private/token.json",
        "file_uri_error": "read failed at file:///srv/private/token.json",
        "url": "https://example.com/research/btc?source=public",
        "api_route": "/api/research/btc/control-center",
        "source_hash": source_hash,
        "strategy": "Signal -> Forecast -> TargetPosition / risk",
        "strategy_id": "donchian_long/short_v2",
    }

    sanitized = sanitize_btc_outbound_payload(
        payload,
        repo_root="/srv/repo",
    )

    assert sanitized["windows_error"] == f"read failed at {REDACTED_PHYSICAL_PATH}"
    assert sanitized["unc_error"] == f"read failed at {REDACTED_PHYSICAL_PATH}"
    assert sanitized["posix_error"] == f"read failed at {REDACTED_PHYSICAL_PATH}"
    assert sanitized["file_uri_error"] == f"read failed at {REDACTED_PHYSICAL_PATH}"
    assert sanitized["url"] == payload["url"]
    assert sanitized["api_route"] == payload["api_route"]
    assert sanitized["source_hash"] == source_hash
    assert sanitized["strategy"] == payload["strategy"]
    assert sanitized["strategy_id"] == payload["strategy_id"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "artifact_missing:/srv/private/a.json",
            f"artifact_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "artifact_missing://server/share/a.json",
            f"artifact_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "btc_artifact_missing:file:///srv/private/a.json",
            f"btc_artifact_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        ("/api", "/api"),
        ("/api/research/btc", "/api/research/btc"),
        ("/research", "/research"),
        ("/research/btc", "/research/btc"),
        ("route:/api", "route:/api"),
        ("route:/research/btc", "route:/research/btc"),
        ("/apiary", REDACTED_PHYSICAL_PATH),
        ("/researcher", REDACTED_PHYSICAL_PATH),
        (
            "artifact_missing:/apiary",
            f"artifact_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "artifact_missing:/researcher",
            f"artifact_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "https://example.com/research/btc?source=public",
            "https://example.com/research/btc?source=public",
        ),
        ("s3://public-bucket/btc/report.json", "s3://public-bucket/btc/report.json"),
        (
            "sqlite:///D:/private/market.sqlite",
            f"sqlite:{REDACTED_PHYSICAL_PATH}",
        ),
        ("a" * 64, "a" * 64),
        (
            "Signal -> Forecast -> TargetPosition / risk",
            "Signal -> Forecast -> TargetPosition / risk",
        ),
        ("donchian_long/short_v2", "donchian_long/short_v2"),
    ],
)
def test_scheme_aware_path_segment_table(value: str, expected: str) -> None:
    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            'read "/srv/private/My Report/a.json" failed',
            f'read "{REDACTED_PHYSICAL_PATH}" failed',
        ),
        (
            r"read 'C:\private\My Report\a.json' failed",
            f"read '{REDACTED_PHYSICAL_PATH}' failed",
        ),
        (
            r'read "\\server\share\My Report\a.json" failed',
            f'read "{REDACTED_PHYSICAL_PATH}" failed',
        ),
        (
            "source='file:///srv/private/My Report/a.json' unavailable",
            f"source='{REDACTED_PHYSICAL_PATH}' unavailable",
        ),
        (
            'source="file://server/share/My Report/a.json" unavailable',
            f'source="{REDACTED_PHYSICAL_PATH}" unavailable',
        ),
        (
            r"""primary="/srv/private/My Report/a.json" fallback='C:\private\My Report\b.json' done""",
            (
                f'primary="{REDACTED_PHYSICAL_PATH}" '
                f"fallback='{REDACTED_PHYSICAL_PATH}' done"
            ),
        ),
    ],
)
def test_quoted_paths_with_spaces_use_matching_quote_boundaries(
    value: str,
    expected: str,
) -> None:
    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == expected


@pytest.mark.parametrize(
    "value",
    [
        '"ordinary quoted text with spaces"',
        "'https://example.com/research/btc report'",
        f'"{"a" * 64}"',
        '"Signal -> Forecast -> TargetPosition / risk"',
        '"/api"',
        "'/api/research/btc'",
        '"/research"',
        "'/research/btc'",
    ],
)
def test_quoted_non_physical_text_is_not_consumed(value: str) -> None:
    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            'read "/srv/private/My Report/a.json failed',
            f'read "{REDACTED_PHYSICAL_PATH}',
        ),
        (
            r"read 'C:\private\My Report\a.json failed",
            f"read '{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "source='file:///srv/private/My Report/a.json unavailable",
            f"source='{REDACTED_PHYSICAL_PATH}",
        ),
    ],
)
def test_unmatched_quoted_physical_path_fails_closed_without_suffix_leakage(
    value: str,
    expected: str,
) -> None:
    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == expected
    assert "Report" not in sanitized["detail"]
    assert "a.json" not in sanitized["detail"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "artifact_missing:/srv/private/My Report/a.json failed",
            f"artifact_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            r"windows_missing:C:\private\My Report\a.json failed",
            f"windows_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "source_missing:file:///srv/private/My Report/a.json unavailable",
            f"source_missing:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "code:/srv/private/My token=value/report.json tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "code:/srv/private/My,Report/a.json tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "code:/srv/private/My;Report/a.json tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "code:/srv/private/My(Report/a.json) tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "code:/srv/private/My:Report/a.json tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            "code:/srv/private/My Report/a.json tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            r"code:/srv/private/a.json fallback=C:\private\b.json tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
        (
            r"code:\\server\share\My token=value\report.json tail",
            f"code:{REDACTED_PHYSICAL_PATH}",
        ),
    ],
)
def test_unquoted_paths_with_spaces_drop_ambiguous_path_bearing_suffix(
    value: str,
    expected: str,
) -> None:
    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == expected
    assert sanitized["detail"].count(REDACTED_PHYSICAL_PATH) == 1
    assert "private" not in sanitized["detail"].lower()
    assert "report" not in sanitized["detail"].lower()
    assert "token=value" not in sanitized["detail"]
    assert "fallback=" not in sanitized["detail"]


@pytest.mark.parametrize("line_break", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "physical_path",
    [
        "/srv/private/My Report/a.json",
        r"C:\private\My Report\a.json",
        r"\\server\share\My Report\a.json",
        "file:///srv/private/My Report/a.json",
    ],
)
def test_unquoted_path_redaction_stops_at_each_cr_or_lf_boundary(
    physical_path: str,
    line_break: str,
) -> None:
    value = (
        f"code:{physical_path} tail"
        f"{line_break}status=blocked_fail_closed"
    )

    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == (
        f"code:{REDACTED_PHYSICAL_PATH}"
        f"{line_break}status=blocked_fail_closed"
    )


def test_each_line_continues_tokenization_after_prior_line_redaction() -> None:
    value = (
        "first:/srv/private/My Report/a.json tail\n"
        r"second:C:\private\My Report\b.json tail"
        "\r\nstatus=blocked_fail_closed"
    )

    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == (
        f"first:{REDACTED_PHYSICAL_PATH}\n"
        f"second:{REDACTED_PHYSICAL_PATH}\r\n"
        "status=blocked_fail_closed"
    )


def test_multiline_quoted_paths_keep_line_boundaries_and_trailing_detail() -> None:
    value = (
        'first="/srv/private/My Report/a.json" failed\r\n'
        r"second='C:\private\My Report\b.json' unavailable"
        "\rstatus=blocked_fail_closed"
    )

    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == (
        f'first="{REDACTED_PHYSICAL_PATH}" failed\r\n'
        f"second='{REDACTED_PHYSICAL_PATH}' unavailable\r"
        "status=blocked_fail_closed"
    )


def test_unmatched_quoted_path_only_redacts_its_current_line() -> None:
    value = (
        'read "/srv/private/My Report/a.json failed\n'
        "status=blocked_fail_closed"
    )

    sanitized = sanitize_btc_outbound_payload(
        {"detail": value},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == (
        f'read "{REDACTED_PHYSICAL_PATH}\n'
        "status=blocked_fail_closed"
    )


def test_nested_blockers_keep_identity_while_each_path_segment_is_redacted() -> None:
    payload = {
        "status_detail": "artifact_missing:/srv/private/status.json",
        "blockers": [
            "btc_artifact_missing://server/share/blocker.json",
            {
                "nested": [
                    "source_unavailable:file:///srv/private/source.json",
                    r"windows_missing:C:\private\state.json",
                ]
            },
        ],
    }

    sanitized = sanitize_btc_outbound_payload(
        payload,
        repo_root="/srv/repo",
    )

    assert (
        sanitized["status_detail"]
        == f"artifact_missing:{REDACTED_PHYSICAL_PATH}"
    )
    assert (
        sanitized["blockers"][0]
        == f"btc_artifact_missing:{REDACTED_PHYSICAL_PATH}"
    )
    assert sanitized["blockers"][1]["nested"] == [
        f"source_unavailable:{REDACTED_PHYSICAL_PATH}",
        f"windows_missing:{REDACTED_PHYSICAL_PATH}",
    ]


def test_first_unquoted_path_redacts_the_entire_remaining_suffix() -> None:
    detail = (
        r"primary=/srv/private/a.json "
        r"fallback=D:\private\b.json "
        r"mirror=\\server\share\c.json"
    )

    sanitized = sanitize_btc_outbound_payload(
        {"detail": detail},
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == f"primary={REDACTED_PHYSICAL_PATH}"


def test_embedded_repo_path_keeps_code_and_uses_relative_provenance_label() -> None:
    sanitized = sanitize_btc_outbound_payload(
        {
            "detail": "artifact_ready:/srv/repo/sub/../reports/a.json",
        },
        repo_root="/srv/repo",
    )

    assert sanitized["detail"] == "artifact_ready:reports/a.json"
