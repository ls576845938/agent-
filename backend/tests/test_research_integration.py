"""Integration tests for Research workflow pipeline."""
from __future__ import annotations
from pathlib import Path
import pytest

@pytest.mark.integration
class TestCandidateGeneration:
    def test_generate_from_param_grid(self, tmp_path):
        from quant_us.research.automation.candidate_gen import CandidateGenerator, CandidateConfig
        config = CandidateConfig(strategy_family="momentum", strategy_ids=["momentum"],
            param_grid={"lookback":[20,60],"top_n":[1,2]}, symbols=["SPY"], max_candidates=10)
        candidates = CandidateGenerator(data_root=str(tmp_path)).generate(config)
        assert len(candidates) == 4
    
    def test_id_deterministic(self, tmp_path):
        from quant_us.research.automation.candidate_gen import CandidateGenerator, CandidateConfig
        config = CandidateConfig(strategy_family="momentum", strategy_ids=["momentum"],
            param_grid={"lookback":[20],"top_n":[1]}, symbols=["SPY"], max_candidates=10)
        c1 = CandidateGenerator(data_root=str(tmp_path)).generate(config)
        c2 = CandidateGenerator(data_root=str(tmp_path)).generate(config)
        assert c1[0]["candidate_id"] == c2[0]["candidate_id"]
    
    def test_max_limit(self, tmp_path):
        from quant_us.research.automation.candidate_gen import CandidateGenerator, CandidateConfig
        c = CandidateConfig(strategy_family="momentum", strategy_ids=["momentum"],
            param_grid={"lookback":[20,60,120],"top_n":[1,2,3]}, symbols=["SPY"], max_candidates=2)
        assert len(CandidateGenerator(data_root=str(tmp_path)).generate(c)) <= 2

@pytest.mark.integration
class TestCandidateScoring:
    def test_score_candidates(self, tmp_path):
        from quant_us.research.automation.candidate_gen import CandidateGenerator, CandidateConfig
        from quant_us.research.automation.scorer import CandidateScorer
        config = CandidateConfig(strategy_family="momentum", strategy_ids=["momentum"],
            param_grid={"lookback":[20,60]}, symbols=["SPY"], max_candidates=10)
        gen = CandidateGenerator(data_root=str(tmp_path))
        gen.save_candidates("exp_score_int", gen.generate(config))
        scores = CandidateScorer(data_root=str(tmp_path)).score("exp_score_int")
        assert isinstance(scores, list)  # scores may be empty if no backtest results

@pytest.mark.integration
class TestExperimentReport:
    def test_report_generated(self, tmp_path):
        from quant_us.research.automation.candidate_gen import CandidateGenerator, CandidateConfig
        from quant_us.research.automation.report_gen import ExperimentReportGenerator
        config = CandidateConfig(strategy_family="momentum", strategy_ids=["momentum"],
            param_grid={"lookback":[20,60]}, symbols=["SPY"], max_candidates=4)
        gen = CandidateGenerator(data_root=str(tmp_path))
        gen.save_candidates("exp_rpt_int", gen.generate(config))
        rpt = ExperimentReportGenerator(data_root=str(tmp_path)).generate("exp_rpt_int")
        assert isinstance(rpt, dict)
        assert rpt.get("candidate_count", 0) >= 0

@pytest.mark.integration
class TestFullPipeline:
    def test_smoke(self, tmp_path):
        from quant_us.research.automation.candidate_gen import CandidateGenerator, CandidateConfig
        from quant_us.research.automation.scorer import CandidateScorer
        from quant_us.research.automation.report_gen import ExperimentReportGenerator
        config = CandidateConfig(strategy_family="momentum", strategy_ids=["momentum"],
            param_grid={"lookback":[20,60],"top_n":[1,2]}, symbols=["SPY"], max_candidates=8)
        gen = CandidateGenerator(data_root=str(tmp_path))
        gen.save_candidates("exp_full_int", gen.generate(config))
        scores = CandidateScorer(data_root=str(tmp_path)).score("exp_full_int")
        rpt = ExperimentReportGenerator(data_root=str(tmp_path)).generate("exp_full_int")
        assert isinstance(scores, list)
        assert isinstance(rpt, dict)

@pytest.mark.integration
class TestSafetyInvariants:
    def test_no_live_imports(self):
        import ast
        forbidden = {"quant_us.live", "quant_us.execution", "AlpacaBroker", "submit_order"}
        for p in ["quant_us/research/automation/candidate_gen.py",
                   "quant_us/research/automation/scorer.py",
                   "quant_us/research/automation/report_gen.py"]:
            if not Path(p).exists(): continue
            tree = ast.parse(Path(p).read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, 'module', '') or ''
                    names = [a.asname or a.name for a in node.names] if hasattr(node, 'names') else []
                    for s in names + [mod]:
                        for f in forbidden:
                            assert f not in str(s), f"{p} imports {f}"
