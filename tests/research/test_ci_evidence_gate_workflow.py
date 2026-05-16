from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/ci.yml")


def test_ci_has_research_evidence_gate_job() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    assert "research-evidence-gate" in jobs
    job_text = str(jobs["research-evidence-gate"])
    assert "test_compression_expansion_event_ledger_artifacts.py" in job_text
    assert "test_compression_expansion_event_ledger_attribution_artifact.py" in job_text
    assert "test_ci_evidence_gate_workflow.py" in job_text


def test_ci_research_evidence_gate_avoids_data_dependent_tests() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    gate_section = workflow_text.split("research-evidence-gate:", 1)[1]

    assert "test_btc_hypothesis_lab_no_lookahead.py" not in gate_section
    assert "test_compression_expansion_event_ledger_validation.py" not in gate_section
