from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "docs" / "agent_playbooks" / "pitfall_catalog.json"
CANONICAL_AGENT_FILES = {
    "a-share-developer.toml",
    "quant-architect.toml",
    "data-steward.toml",
    "super-developer.toml",
    "btc-developer.toml",
    "integrator.toml",
    "researcher.toml",
}


def _outer_workspace() -> Path:
    common_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    return Path(common_dir).resolve().parent.parent


def test_agents_contract_is_stable_and_not_status_driven() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "BTC/加密资产、美股与 A 股" in text
    assert "agent-governance-v2" in text
    assert "当前用户提示或 active Goal objective 即为已批准任务" in text
    assert "无需为读取、编辑、格式化、测试" in text
    assert "Full Access 或 Goal mode" in text
    assert "context_packet.py" in text
    assert "tools/agent_governance/safe_status.py" in text
    assert "常驻角色任务必须从本仓库项目以 Local 环境启动" in text
    assert "不得直接修改或提交注册主工作树" in text
    assert "$CODEX_HOME/worktrees" in text
    assert "当前用户目标和 active milestone 是工作选择边界" in text
    assert "完整 blocker inventory 只用于暴露风险" in text
    assert "每个显式修复请求默认最多一个 producer ticket" in text
    assert "security、risk、OMS、ledger、private/order/live" in text
    assert "`git status --short`" not in text
    assert "默认不全文加载原始日志" in text
    assert "Frontend is good enough" not in text
    assert "Daily (3 agents)" not in text
    assert "Reasoning Effort Guide" not in text
    assert "Current Priority" not in text


def test_outer_workspace_is_only_a_bootstrap() -> None:
    text = (_outer_workspace() / "AGENTS.md").read_text(encoding="utf-8")

    assert "真实 Git 仓库" in text
    assert "workspace/CWD 新建任务" in text
    assert "完整踩坑日志" in text
    assert "Architect Agent" not in text


def test_project_config_bounds_parallelism_and_enables_hooks() -> None:
    with (REPO_ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)

    assert config["model"] == "gpt-5.6-sol"
    assert config["model_reasoning_effort"] == "high"
    assert config["approval_policy"] == "never"
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["agents"]["max_threads"] <= 3
    assert config["agents"]["max_depth"] == 1
    assert config["features"]["hooks"] is True


def test_only_canonical_agent_profiles_are_active() -> None:
    agent_dir = REPO_ROOT / ".codex" / "agents"
    active = {path.name for path in agent_dir.glob("*.toml")}

    assert active == CANONICAL_AGENT_FILES
    assert (agent_dir / "legacy" / "cli-devops.toml.disabled").exists()
    assert (REPO_ROOT / ".codex" / "prompts" / "archive" / "phase-f5-all.md.disabled").exists()

    profiles = {}
    for path in agent_dir.glob("*.toml"):
        with path.open("rb") as handle:
            profiles[path.name] = tomllib.load(handle)

    assert profiles["quant-architect.toml"]["sandbox_mode"] == "read-only"
    assert profiles["researcher.toml"]["sandbox_mode"] == "read-only"
    writer_profiles = (
        "a-share-developer.toml",
        "btc-developer.toml",
        "data-steward.toml",
        "integrator.toml",
        "super-developer.toml",
    )
    for profile_name in writer_profiles:
        assert profiles[profile_name]["sandbox_mode"] == "danger-full-access"

    for profile_name in writer_profiles:
        instructions = profiles[profile_name]["developer_instructions"]
        assert "current user prompt or active Goal objective is the approved ticket" in instructions
        assert "Do not ask for repeated confirmation" in instructions
        assert "Full Access does not relax promotion gates" in instructions

    for profile_name in writer_profiles:
        instructions = profiles[profile_name]["developer_instructions"]
        assert "tools/agent_governance/worktree_plan.py" in instructions
        assert "core.sparseCheckout" in instructions
        assert "tools/agent_governance/safe_status.py" in instructions

    for profile_name in ("quant-architect.toml", "researcher.toml"):
        assert "tools/agent_governance/safe_status.py" in profiles[profile_name]["developer_instructions"]


def test_pitfall_catalog_is_traceable() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rules = catalog["rules"]
    ids = [rule["id"] for rule in rules]

    assert catalog["ruleset_version"] == "agent-governance-v2"
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Z][A-Z0-9-]*-\d{3}", rule_id) for rule_id in ids)

    allowed_roles = {
        "all",
        "a_share_developer",
        "architect",
        "data_steward",
        "super_developer",
        "btc_developer",
        "researcher",
        "integrator",
    }
    for rule in rules:
        assert rule["status"] in {"active", "superseded", "resolved"}
        assert rule["severity"] in {"P0", "P1", "P2"}
        assert rule["enforcement"] in {
            "global_invariant",
            "conditional_guardrail",
            "advisory",
        }
        assert rule["roles"] and set(rule["roles"]).issubset(allowed_roles)
        assert rule["scopes"]
        assert rule["rule"].strip()
        assert rule["sources"]
        assert rule["regression_tests"]
        if rule["enforcement"] == "conditional_guardrail":
            applicability = rule["applicability"]
            assert applicability["change_risks"]
            assert applicability["capabilities"]
            assert applicability["operations"]
            assert rule["owner"]
            assert re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", rule["last_reviewed"]
            )
            assert re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", rule["review_due"]
            )
            assert rule["sunset_criteria"].strip()
        if rule["status"] == "superseded":
            assert rule["superseded_by"] in ids
        for source in rule["sources"]:
            source_path = source.split("#", 1)[0]
            assert (REPO_ROOT / source_path).exists(), source
        for test_path in rule["regression_tests"]:
            assert (REPO_ROOT / test_path).exists(), test_path

    by_id = {rule["id"]: rule for rule in rules}
    objective = by_id["GOV-OBJECTIVE-001"]
    circuit = by_id["GOV-ENGINEERING-CIRCUIT-001"]
    assert objective["severity"] == circuit["severity"] == "P0"
    assert {"shared", "governance", "monitoring"}.issubset(
        objective["scopes"]
    )
    assert "blocker inventory" in objective["rule"]
    assert "current-HEAD" in circuit["rule"]
    assert "最多一个 producer ticket" in circuit["rule"]
    assert objective["enforcement"] == "conditional_guardrail"
    assert circuit["enforcement"] == "conditional_guardrail"
    artifact = by_id["QSYS-ARTIFACT-001"]
    assert artifact["applicability"]["change_risks"] == [
        "promotion_evidence",
        "live_execution",
    ]

    delivery_policy = json.loads(
        (
            REPO_ROOT
            / "docs"
            / "agent_playbooks"
            / "delivery_risk_policy.json"
        ).read_text(encoding="utf-8")
    )
    hotfix = delivery_policy["change_risks"]["demo_transport_hotfix"]
    assert hotfix["independent_integrator_required"] is False
    assert hotfix["promotion_artifact_rebuild_required"] is False
    assert hotfix["backend_restart_required"] is True
    assert "live_permissions" in hotfix["forbidden_changes"]


def test_repo_skills_have_no_placeholders() -> None:
    skill_root = REPO_ROOT / ".agents" / "skills"
    expected = {"quant-agent-preflight", "quant-gate-evidence-review", "quant-agent-handoff"}

    assert {path.name for path in skill_root.iterdir() if path.is_dir()} == expected
    for name in expected:
        skill = (skill_root / name / "SKILL.md").read_text(encoding="utf-8")
        assert "TODO" not in skill
        assert skill.startswith("---\nname:")
        assert (skill_root / name / "agents" / "openai.yaml").exists()
