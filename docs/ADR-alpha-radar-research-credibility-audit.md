# ADR: Alpha Radar Research Credibility Audit Engine

**Status:** Proposed
**Date:** 2026-05-13
**Author:** Architecture Agent
**Affected Systems:** Alpha Radar (new), quant_us (unchanged)

---

## Context

The Alpha Radar project needs a credibility audit engine for subjective investment research artifacts -- evidence chains, industry chain logic, signal ratings, AI-generated research conclusions, and stock pool ratings. These are fundamentally different from the execution-level quantitative strategy audit that `quant_us.research` performs.

The `quant_us` module audits quantitative strategy candidates for backtest integrity and live-trading readiness: order/fill/ledger reconciliation, PBO/DSR/CPCV, walk-forward, Monte Carlo survival, cost/slippage models, and data manifest governance. Alpha Radar needs something that answers different questions:

- Is the evidence chain complete and logically sound?
- Does the signal have corroborating support?
- Is the narrative internally consistent and free of contradiction?
- Are there identifiable biases in the research process?

The two audit systems share **patterns** but not **purpose**. Attempting to reuse quant_us directly would introduce domain confusion, unwanted dependencies on quant-specific infrastructure (data manifests, ledger artifacts, cost models), and an awkward impedance mismatch between quantitative metrics and qualitative credibility checks.

---

## Decision

Create `alpha-radar/backend/research_audit/` as an independent Python package. It copies patterns from `quant_us` but shares zero code and has no dependency on `quant_us`.

### Module Structure

```
alpha-radar/backend/research_audit/
    __init__.py              # Exports: ResearchAuditRunner, ResearchAuditResult
    schemas.py               # Dataclasses: AuditTarget, AuditResult, CredibilityScore, CheckResult
    runner.py                # ResearchAuditRunner -- orchestrates check modules
    scoring.py               # CredibilityScorer -- weighted rubric, composite score
    report.py                # Markdown report generation with dossier-style sections
    evidence_check.py        # EvidenceChainChecker -- completeness, corroboration, traceability
    signal_check.py          # SignalChecker -- signal logic, data sources, replicability
    narrative_check.py       # NarrativeChecker -- internal consistency, contradiction detection
    bias_check.py            # BiasChecker -- recency, anchoring, confirmation, selection bias
    promotion_gate.py        # Gate: BLOCKED/WATCHLIST/NEED_MORE_EVIDENCE/RESEARCH_READY/HIGH_CONVICTION
    tests/
        __init__.py
        test_evidence_check.py
        test_signal_check.py
        test_narrative_check.py
        test_bias_check.py
        test_scoring.py
        test_runner.py
        test_report.py
        test_promotion_gate.py
        fixtures/
            sample_evidence_chain.json
            sample_signal.json
            sample_narrative.json
```

### Data Flow

```
ResearchAuditTarget
    |
    v
ResearchAuditRunner.run(target)
    |
    +-- evidence_check.EvidenceChainChecker.check(target)
    |       returns: CheckResult (status, reasons, flags)
    |
    +-- signal_check.SignalChecker.check(target)
    |       returns: CheckResult
    |
    +-- narrative_check.NarrativeChecker.check(target)
    |       returns: CheckResult
    |
    +-- bias_check.BiasChecker.check(target)
    |       returns: CheckResult
    |
    v
CredibilityScorer.score([check1, check2, check3, check4])
    |
    v
PromotionGate.evaluate(target, checks, score)
    |       returns: GateDecision + AuditResult
    |
    v
report.ReportGenerator.generate(target, result)
    |       returns: markdown string
    |
    v
Persist: JSON file(s) under alpha-radar/backend/data/research-audit/
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Copy-first, not shared package** | The two systems answer different questions. Sharing a base package would couple them to each other's versioning and create an unwanted dependency from Alpha Radar to quant_us. Duplicated patterns (gate evaluation, scoring, report gen) are stable enough to copy. |
| **No quant_us dependency** | The research_audit package must import nothing from quant_us. All schemas, enums, and helpers are defined in-house. This keeps Alpha Radar deployable independently. |
| **JSON-file persistence** | Each audit run produces a JSON result file under `data/research-audit/runs/{audit_id}.json`. This is simple, debuggable, and easily consumed by the frontend. No database required at launch. |
| **Machine-readable flags** | Every CheckResult includes a `flags: list[str]` field with prefixed identifiers (e.g., `evidence_missing_source`, `signal_unsupported_claim`). Frontend renders these as warning badges. Pattern from quant_us promotion_gate `blocking_reasons` / `machine_readable_blockers`. |
| **Markdown report** | The report generator produces a multi-section markdown dossier, stored at `data/research-audit/reports/{audit_id}.md`. Pattern from quant_us `dossier.py` and `report_gen.py`. |

---

## What We Migrate (Patterns Only, Not Code)

| Pattern | Source | Adaptation for Alpha Radar |
|---------|--------|---------------------------|
| Gate decision statuses | `promotion_gate.py` BLOCKED/WATCHLIST/NEED_MORE_RESEARCH/READY_FOR_PAPER_REVIEW | BLOCKED/WATCHLIST/NEED_MORE_EVIDENCE/RESEARCH_READY/HIGH_CONVICTION |
| Evidence contract validation | `evidence_contracts.py` required fields, missing reasons, status | Required fields per credibility dimension (source, date, author, corroboration count), blocking reasons list |
| Weighted scoring rubric | `promotion_gate.py` accumulating checks --> threshold-based decision | Weighted checks per dimension; composite score 0.0-1.0; per-dimension sub-scores |
| Report section builders | `dossier.py` header/strategy/backtest/walk_forward/cost_stress sections | header/evidence_chain/signal/narrative/bias/recommendation sections |
| Runner orchestration | `promotion_gate.evaluate()` as single entry point | `ResearchAuditRunner.run()` calls all checkers, scorer, gate |
| Machine-readable blocker flags | `evidence["machine_readable_blockers"]` | `flags` list on each CheckResult, prefixed by dimension |
| Persistence with SHA256 integrity | `promotion_gate.py` `_persist_promotion_result()` + `_file_sha256()` | JSON result files with audit_id in filename; SHA256 recorded in result metadata |

---

## What We Explicitly Exclude and Why

| Excluded Feature | Reason |
|-----------------|--------|
| Order/Fill/Ledger reconciliation | Execution-level concern. Alpha Radar audits research credibility, not trade integrity. |
| PBO, DSR, CPCV, walk-forward metrics | Quantitative overfit/validation tools. Not applicable to subjective evidence chains. |
| Monte Carlo survival rate, alpha decay, param stability | Robustness suite for strategy parameters. Alpha Radar does not define parameters. |
| Cost models, slippage models | Execution-cost modeling. Irrelevant to research credibility. |
| Data manifest validation | quant_us data governance (data_version, checksums, manifest store). Alpha Radar uses its own source tracking. |
| Trade count, max drawdown, Sharpe ratio gates | Performance-based gates. Alpha Radar gates on evidence completeness, not returns. |
| Corporate actions digest | Backtest-specific bookkeeping. Not applicable. |
| Any quant_us import | Independence requirement. No `from quant_us` anywhere. |

---

## Check Dimensions

### 1. Evidence Chain Check (`evidence_check.py`)

Validates that the research artifact has a complete, traceable evidence chain.

**Rules:**
- Source must be explicitly declared (provider URL, data vendor, analyst note)
- Timestamp must be present and non-future
- Author/originator must be identified
- At least one corroborating reference must exist (cross-source, cross-time)
- All claims in the artifact must trace to an evidence entry
- Evidence entries must have non-empty content (not just a title)

**Output flags:** `evidence_missing_source`, `evidence_future_timestamp`, `evidence_missing_author`, `evidence_no_corroboration`, `evidence_untraced_claim`, `evidence_empty_entry`

### 2. Signal Check (`signal_check.py`)

Assesses the signal or rating itself for logical soundness and data support.

**Rules:**
- Signal direction (bullish/bearish/neutral) must be explicitly stated
- Signal must reference at least one quantitative or categorical input
- If the signal references an external data source, the source must be named
- No contradictory signal from the same source within the same window (unless explained)
- For AI-generated signals: the model name and version must be recorded

**Output flags:** `signal_missing_direction`, `signal_no_input_reference`, `signal_unnamed_source`, `signal_self_contradiction`, `signal_ai_model_unnamed`

### 3. Narrative Check (`narrative_check.py`)

Checks the internal consistency and logical flow of the research narrative.

**Rules:**
- Narrative must not contain contradictory statements
- If a rating is "long" the narrative must not conclude with bearish risks without reconciling them
- All named entities (stocks, sectors, macro indicators) in the conclusion must appear in the body
- The narrative must have at least one stated assumption or caveat
- Timeline of events must be chronologically consistent

**Output flags:** `narrative_contradiction`, `narrative_rating_mismatch`, `narrative_untraced_entity`, `narrative_no_caveat`, `narrative_time_inconsistency`

### 4. Bias Check (`bias_check.py`)

Detects common research biases through heuristic pattern matching.

**Rules:**
- **Recency bias:** If >80% of evidence is from the last 7 days, flag
- **Anchoring bias:** If successive ratings from same author are unchanged despite contradictory evidence, flag
- **Confirmation bias:** If all cited sources share the same directional view, flag
- **Selection bias:** If the stock pool is defined after the signal is generated (ex post), flag
- **Herding bias:** If the signal direction matches the majority of peer signals without independent reasoning, flag

**Output flags:** `bias_recency`, `bias_anchoring`, `bias_confirmation`, `bias_selection`, `bias_herding`

---

## Scoring Rubric

The `CredibilityScorer` produces a composite score 0.0-1.0 and four dimension subscores.

| Dimension | Weight | Scoring Logic |
|-----------|--------|---------------|
| Evidence Chain | 0.35 | Base 1.0, subtract 0.25 per blocking flag, 0.1 per warning flag |
| Signal | 0.25 | Base 1.0, subtract 0.2 per blocking flag, 0.1 per warning flag |
| Narrative | 0.25 | Base 1.0, subtract 0.2 per blocking flag, 0.1 per warning flag |
| Bias | 0.15 | Base 1.0, subtract 0.15 per detected bias |

Each subscore is clamped to [0.0, 1.0].

---

## Promotion Gate Decisions

```
GateDecision:
  BLOCKED               -> fatal check failures. Cannot proceed.
  WATCHLIST             -> non-fatal warnings exist. Action recommended.
  NEED_MORE_EVIDENCE    -> evidence is incomplete or missing required fields.
  RESEARCH_READY        -> all checks pass. Artifact may enter research pool.
  HIGH_CONVICTION       -> all checks pass AND composite score > 0.85.
```

Threshold logic:
- Any CheckResult with `status == "FAIL"` -> BLOCKED
- All pass but any `flags` exist -> WATCHLIST
- Evidence chain has missing required fields -> NEED_MORE_EVIDENCE
- All pass, no flags -> RESEARCH_READY
- RESEARCH_READY + composite score > 0.85 + no bias flags -> HIGH_CONVICTION

---

## API Design

```
POST /api/research-audit/run
  Body: {
    "target_type": "evidence_chain" | "signal" | "narrative" | "full_artifact",
    "target_id": string,
    "content": { ... artifact payload }
  }
  Response: {
    "audit_id": string,
    "status": "completed",
    "decision": string,
    "composite_score": float,
    "dimension_scores": { ... },
    "flags": [string],
    "report_path": string | null
  }

GET /api/research-audit/result/{audit_id}
  Returns full audit result JSON from persisted file.

GET /api/research-audit/target/{type}/{id}
  Returns all audit results for a given target (ordered by recency).
```

These endpoints are stubs that delegate to `ResearchAuditRunner` synchronously at launch. Async execution is deferred until the system processes more than ~50 artifacts/day.

---

## Consequences

### Positive

1. Clean separation of concerns. quant_us stays execution-focused; Alpha Radar stays credibility-focused.
2. No cross-system version coupling. Each can evolve independently.
3. Frontend can render machine-readable flags as badges without knowing the audit internals.
4. Pattern reuse speeds development without code coupling.
5. JSON persistence means zero infrastructure dependencies to start.

### Negative

1. Code duplication of gate/scoring/report patterns. Acceptable because these patterns are stable (changes at most twice per year).
2. No shared type definitions between quant_us and Alpha Radar. If a future system needs both audit types, it must import both packages.

### Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Scope creep: evidence_check grows into quant_us territory | Medium | Explicit "Do Not Migrate" list enforced in code review. |
| AI-generated signal detection becomes outdated quickly | Medium | BiasChecker model registry is configuration-driven, not hardcoded. |
| Report markdown diverges from frontend expectations | Low | Frontend consumes JSON flags, not raw markdown. Report is a separate concern. |
| JSON file persistence becomes slow at scale | Low (at launch) | API design supports swapping to DB later. Runner interface is file-agnostic. |
| Gate thresholds feel arbitrary | Medium | All thresholds are constants at module top, documented, and changeable without code changes via config file in v2. |
