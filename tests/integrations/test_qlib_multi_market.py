from pathlib import Path

from integrations.qlib_adapter.run_qlib_workflow import _backtest_summary


def test_disabled_analysis_is_not_completed():
    result = _backtest_summary(metrics_payload={"metrics": {}}, config={
        "workflow": {"enable_portfolio_analysis": False}}, run_id="research-test")
    assert result["portfolio_analysis_status"] == "not_run"


def test_market_module_does_not_present_fixed_chart_as_runtime():
    root = Path(__file__).resolve().parents[2]
    source = (root / "frontend/src/workspaces/StrategyModulesWorkspace.tsx").read_text(encoding="utf-8")
    assert '[38, 45, 42, 56' not in source
    assert '候选配置' in source
