---
name: quant-gate-evidence-review
description: Review BTC or US equity promotion, paper, live-readiness, execution, monitoring, or replay evidence against current HEAD. Use when a task asks whether a gate passed, what remains blocked, whether artifacts are fresh, or whether the system may advance to paper or live.
---

# Quant Gate Evidence Review

1. Run `quant-agent-preflight` with the relevant domain and `gate` scope.
2. Read the concrete latest report named by the production dependency chain. Do not infer the path from a similar filename.
3. Verify report schema, `generated_at`/`as_of_utc`, code commit, input hashes, decision, blockers, and safety flags.
4. Treat wrapper exit success, historical diagnostics, fixture evidence, flat heartbeat, or standalone schema tests as insufficient gate evidence.
5. Check dependency topology before suggesting a rebuild. Never run dependent builders in parallel.
6. Keep `research_only`, `blocked`, `fail_closed`, and stale artifacts classified exactly as recorded.
7. Report the current stage, root blockers, evidence paths, missing tests, and the precise next gate action. State whether paper/live advancement is allowed.
8. Do not call broker, private, order, or live endpoints during evidence review.
