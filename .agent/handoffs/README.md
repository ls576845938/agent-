# Cross-Agent Handoff Events

This directory contains small, append-only handoff envelopes. It is not a mutable status store.

Rules:

- Commit the deliverable first. Emit the handoff in a later commit that references `deliverable_commit`.
- Use one unique path per event: `.agent/handoffs/<ticket_id>/<event_id>.json`.
- Never edit or delete a published event. Correct it with `superseded` or `rejected`.
- Other worktrees discover committed events through Git refs. Uncommitted files are never deliverables.
- A data handoff references a Git-tracked shared dataset manifest. Large data lives in the immutable shared data root.
- Handoffs never unlock promotion, paper, live, private, broker, exchange, or order actions.

Validate and emit:

```powershell
py -3 tools/agent_governance/handoff.py --repo-root . validate --input handoff.json
py -3 tools/agent_governance/handoff.py --repo-root . emit --input handoff.json
```

Discover team state:

```powershell
py -3 tools/agent_governance/team_context.py --repo-root . --role super_developer --format markdown
```
