---
name: quant-agent-preflight
description: Prepare any task in this BTC, US equity, and China A-share quant repository by loading the correct role rules, selecting active pitfall IDs, checking the real repo root and dirty worktree, and declaring a conflict-safe touch set. Use before architecture reviews, data work, research, code edits, gate rebuilds, tests, or artifact generation.
---

# Quant Agent Preflight

1. Confirm the task CWD is the `agent-` Git root. Stop write work if the task was started from the outer Obsidian folder.
2. Identify the canonical role: `architect`, `data_steward`, `super_developer`, `btc_developer`, `a_share_developer`, `researcher`, or the short-lived `integrator`.
3. Read `AGENTS.md`, `docs/knowledge/README.md`, the shared playbook, and the matching role playbook.
4. Run:

   ```powershell
   py -3 tools/agent_governance/context_packet.py --role <role> --scope <scope> --change-risk <change-risk> --format markdown
   ```

5. Select `change-risk` from `delivery_risk_policy.json`. Use
   `demo_transport_hotfix` only for Demo parser/transport/candle/public-tail
   changes that leave strategy, risk, order construction, private-WS
   reconciliation, ledger, security, and live permissions unchanged. Use
   `unclassified` when evidence is insufficient; it preserves the strict legacy
   path. A P0 severity alone does not make a conditional incident rule globally
   applicable. Read only the raw-log entries referenced by selected IDs when
   their incident details affect the task. Do not load either raw pitfall log in
   full by default.
6. Read the injected Team Context packet. If it is absent or stale, run:

   ```powershell
   py -3 tools/agent_governance/team_context.py --repo-root . --role <role> --change-risk <change-risk> --format markdown
   ```

   Treat this as discovery only. Run `handoff.py validate` before consuming another agent's delivery.
7. Record the current HEAD, catalog hash, dirty paths, intended touch set, upstream handoff IDs, and dependency blockers.
8. For a writer role, plan an isolated worktree before implementation:

   ```powershell
   py -3 tools/agent_governance/worktree_plan.py --role <writer-role> --task-id <ticket-id>
   ```

   Add `--apply` only when starting a new writer task. Do not migrate an already-running dirty task automatically.
9. If another agent owns an intended file, SQLite database, or latest artifact path, stop the overlapping write and report the conflict.
10. Never consume another worktree's uncommitted path. Resolve large data only through a committed manifest and immutable shared-data version.
11. Keep private/order/live endpoints and secret files outside the task unless the user has explicitly authorized that exact operation and repository gates allow it.
12. For `demo_transport_hotfix`, validate the committed touch set, regression,
    Demo safety attestation, and cross-agent handoff before using the main
    fast-forward path. Do not request a promotion artifact/read-model rebuild;
    do require a backend restart. Treat `integrated_fastpath` as derived delivery
    state only, never as promotion or trading permission.
