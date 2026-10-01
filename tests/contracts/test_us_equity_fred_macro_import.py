from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pandas as pd

from scripts.fetch_us_equity_fred_macro import SERIES, _load_series, fetch_us_equity_fred_macro


SCHEMA = Path("schemas/us_equity_fred_macro_import_report.schema.json")
COMPAT_SCHEMA = Path("schemas/fred_macro_import_report.schema.json")


def test_fred_public_graph_uses_curl_compatible_product_user_agent(monkeypatch) -> None:
    expected_user_agent = "curl/8.0.0 QuantSystem-PublicData/1.0"
    captured_requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback) -> None:
            return None

        def read(self) -> bytes:
            return b"observation_date,WALCL\n2026-08-01,1\n"

    def fake_urlopen(request, *, timeout: float):
        captured_requests.append((request, timeout))
        return Response()

    monkeypatch.setattr("scripts.fetch_us_equity_fred_macro.urllib.request.urlopen", fake_urlopen)

    frame, source = _load_series(
        "WALCL",
        start_date="2000-01-01",
        offline_source_dir=None,
        api_key="",
        timeout_seconds=7.5,
    )

    assert list(frame.columns) == ["observation_date", "WALCL"]
    assert source.startswith("https://fred.stlouisfed.org/graph/fredgraph.csv?")
    assert len(captured_requests) == 1
    request, timeout = captured_requests[0]
    assert timeout == 7.5
    assert request.full_url == source
    assert request.get_header("User-agent") == expected_user_agent
    assert request.get_header("User-agent").startswith("curl/")
    assert "QuantSystem-PublicData/" in request.get_header("User-agent")


def test_fred_macro_import_combines_required_series_from_offline_fixtures(tmp_path: Path) -> None:
    source = tmp_path / "fred"
    source.mkdir()
    for series in SERIES:
        (source / f"{series}.csv").write_text(
            "observation_date,{series},realtime_start,realtime_end\n"
            "2026-06-23,1.0,2026-06-24,9999-12-31\n"
            "2026-06-24,2.0,2026-06-25,9999-12-31\n".format(series=series),
            encoding="utf-8",
        )

    payload = fetch_us_equity_fred_macro(
        repo_root=tmp_path,
        output_data=Path("data/external/us_equity_macro/fred_macro.csv"),
        report_path=Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json"),
        offline_source_dir=source,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "pass"
    _validate_schema(payload)
    _validate_schema(payload, COMPAT_SCHEMA)
    assert payload["latest_common_date"] == "2026-06-24"
    assert payload["macro_lag_days"] == 2
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["order_endpoint_used"] is False
    assert payload["guardrails"]["token_written_to_artifacts"] is False
    out = tmp_path / "data/external/us_equity_macro/fred_macro.csv"
    assert out.exists()
    df = pd.read_csv(out)
    assert set(SERIES).issubset(df.columns)
    assert "timestamp_utc" in df.columns
    assert {"realtime_start", "realtime_end"}.issubset(df.columns)


def test_fred_macro_import_blocks_missing_series(tmp_path: Path) -> None:
    source = tmp_path / "fred"
    source.mkdir()
    for series in SERIES[:-1]:
        (source / f"{series}.csv").write_text(
            "observation_date,{series}\n2026-06-24,2.0\n".format(series=series),
            encoding="utf-8",
        )

    payload = fetch_us_equity_fred_macro(
        repo_root=tmp_path,
        output_data=Path("data/external/us_equity_macro/fred_macro.csv"),
        report_path=Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json"),
        offline_source_dir=source,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    _validate_schema(payload)
    assert "fred_series_fetch_failed:DGS2" in payload["blockers"]
    assert "fred_macro_required_columns_missing" in payload["blockers"]
    assert payload["guardrails"]["real_order_submitted"] is False


def test_fred_macro_import_schema_accepts_public_graph_csv_blocked_report() -> None:
    payload = {
        "schema_version": "us_equity_fred_macro_import_report_v1",
        "generated_at": "2026-06-28T00:00:00Z",
        "provider": "FRED",
        "source_type": "public_graph_csv",
        "status": "blocked",
        "series": list(SERIES),
        "series_reports": [{"series_id": series, "status": "failed", "source": "fred_graph_csv"} for series in SERIES],
        "latest_by_series": {},
        "latest_common_date": None,
        "macro_lag_days": 2,
        "publication_lag_policy": "research pipeline must shift macro data before signal use",
        "output_data": "data/external/us_equity_macro/fred_macro.csv",
        "row_count": 0,
        "blockers": ["fred_macro_required_columns_missing"],
        "guardrails": {
            "macro_data_only": True,
            "api_key_required": False,
            "api_key_used_for_macro_data": False,
            "token_written_to_artifacts": False,
            "broker_endpoint_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": False,
            "real_order_submitted": False,
        },
    }

    _validate_schema(payload)
    _validate_schema(payload, COMPAT_SCHEMA)


def test_fred_macro_import_does_not_write_api_key_to_artifact(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "fred"
    source.mkdir()
    for series in SERIES:
        (source / f"{series}.csv").write_text(
            "observation_date,{series}\n2026-06-24,2.0\n".format(series=series),
            encoding="utf-8",
        )

    payload = fetch_us_equity_fred_macro(
        repo_root=tmp_path,
        output_data=Path("data/external/us_equity_macro/fred_macro.csv"),
        report_path=Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json"),
        offline_source_dir=source,
        api_key="SECRET_TEST_KEY",
        generated_at="2026-06-25T00:00:00Z",
    )

    text = (tmp_path / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json").read_text(encoding="utf-8")
    assert payload["status"] == "pass"
    _validate_schema(payload)
    assert "SECRET_TEST_KEY" not in text


def test_fred_macro_import_schema_rejects_token_written_flag(tmp_path: Path) -> None:
    source = tmp_path / "fred"
    source.mkdir()
    for series in SERIES:
        (source / f"{series}.csv").write_text(
            "observation_date,{series}\n2026-06-24,2.0\n".format(series=series),
            encoding="utf-8",
        )

    payload = fetch_us_equity_fred_macro(
        repo_root=tmp_path,
        output_data=Path("data/external/us_equity_macro/fred_macro.csv"),
        report_path=Path("artifacts/us_equity_data_status/latest/fred_macro_import_report.json"),
        offline_source_dir=source,
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["token_written_to_artifacts"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted token_written_to_artifacts=true")


def _validate_schema(payload: dict[str, object], schema_path: Path = SCHEMA) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
