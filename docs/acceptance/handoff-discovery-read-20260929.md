# HANDOFF-DISCOVERY-READ-20260929 acceptance

## Scope and boundary

- Role: `super_developer`
- Change risk: `governance_control`
- Base commit: `1dd1bcdb1094772f42176af1ac48c703cb73199c`
- Producer branch: `agent/super_developer/handoff-discovery-read-20260929`
- Catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- Source touch set: `tools/agent_governance/handoff.py`
- Test touch set: `tests/agent_governance/test_handoff.py`
- Evidence touch set: this report and the ticket's append-only handoff directory
- No business, editor, schema, security, launcher, hook, timeout, permission, data,
  artifact, manifest, ledger, private, order, paper, or live path changed.

Initial scoped status was clean for the complete declared touch set. The worktree
was created by `worktree_plan.py`, remained sparse, and used base commit
`1dd1bcdb1094772f42176af1ac48c703cb73199c`. `quant_crypto/` was added only to
this worktree's sparse visibility because `team_context.py` imports committed BTC
read-model adapters; no file under that directory was edited.

## Root cause and implementation

The bounded handoff walker materialized each ref's `.agent/handoffs` root tree in
the initial `cat-file --batch`, then requested the same unique root object IDs in
the first depth batch. It also performed two membership filters by scanning the
ordered `scan_refs` list for every discovered entry.

The repair is local to one discovery invocation:

- reuse root and descendant tree bodies by object ID;
- parse each tree object once while retaining every ref/path user;
- count the materialized-byte cap from bodies actually returned by Git;
- count the tree-object cap by unique object ID while retaining the original
  path-depth limit;
- check the unchanged discovery-wide deadline even when a cache hit avoids a Git
  child;
- keep the ordered ref list for output and use a set only for membership filters.

There is no cross-call cache and therefore no settled or stale result. The
unchanged limits remain:

- discovery deadline: 10 seconds;
- Git child timeout: 4 seconds;
- refs: 512 distinct uncovered projections;
- tree objects: 4096 unique object IDs;
- blob objects: 4096;
- tree depth: 4;
- single blob: 1 MiB;
- materialized bytes: 32 MiB.

## Failure-first and regression evidence

Failure-first root reuse:

```text
py -3 -m pytest tests/agent_governance/test_handoff.py::test_tree_discovery_reuses_root_object_without_second_git_batch -q
before repair: 1 failed in 2.53s
failure: root tree was read twice
after repair: 1 passed in 4.85s
```

Failure-first deadline preservation:

```text
py -3 -m pytest tests/agent_governance/test_handoff.py::test_tree_discovery_cached_root_still_checks_global_deadline -q
before checkpoint: 1 failed in 2.16s (DID NOT RAISE)
after checkpoint, included in tree-discovery group: passed
```

The added regressions cover root reuse, exact/over materialized-byte boundaries,
unique object counting across depths, depth rejection, missing root, wrong root
type, malformed cached tree, missing descendant object, and cache-hit deadline
expiry.

Focused results:

```text
py -3 -m pytest tests/agent_governance/test_handoff.py -q
29 passed in 73.37s

py -3 -m pytest tests/agent_governance/test_team_context.py -q
16 passed in 73.94s

git diff --check -- tools/agent_governance/handoff.py tests/agent_governance/test_handoff.py
passed (no whitespace errors; checkout emitted only the configured LF/CRLF warning)
```

## Real repository performance and projection parity

Original implementation baseline under the unchanged 10-second deadline:

- elapsed: 9.354 seconds;
- refs: 903;
- valid events: 1230;
- invalid handoffs: 17;
- root specs: 904, representing 849 unique root object IDs;
- initial root batch: 13,865,295 bytes;
- redundant depth-zero root batch: 13,296,538 bytes.

The baseline implementation also timed out in a later parity attempt, which is
consistent with the prior `handoff_git_timeout:cat-file` and
`handoff_discovery_timeout` failures near the 10-second boundary.

Current implementation, same Git refs and unchanged limits:

- full discovery elapsed: 6.466970 seconds;
- exact Team Context CLI elapsed: 7.093518 seconds;
- refs: 903;
- valid events: 1230;
- invalid handoffs: 17;
- main-covered refs: 499;
- uncovered refs: 404;
- main projection entries: 985;
- full current discovery SHA-256: `c708a303b1d8e4b71d656a541ed3169157d23346d9ede4530630e41ed965f3a7`.

The baseline and current tree projection each contained 414,987
`(ref, path, object_id)` rows and both hashed to
`af1de77db36ccc3789716e52dc711e188257ca4c751ec61b198e5dabf28d03df`.
Thus no ref, main source, path, or blob identity was skipped by the optimization.

The exact CLI command was:

```text
py -3 tools/agent_governance/team_context.py --role architect --change-risk research_readonly_release --max-events 3 --max-chars 6000 --format json
```

It reported the correct branch and HEAD, returned the full projection, and kept
all 17 historical invalid handoffs visible. Its exit code was 2 because invalid
handoffs remain present; that is expected fail-closed evidence, not an empty or
successful-clean projection. The invalid entries were not repaired or hidden by
this ticket.

## Governance and gate state

Read playbooks: `AGENTS.md`, `docs/knowledge/README.md`,
`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`,
`docs/agent_playbooks/shared_pitfalls.md`, and
`docs/agent_playbooks/super_developer_pitfalls.md`.

Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`,
`GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`,
`GOV-PITFALL-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`,
`GOV-PROMPT-001`, and `GOV-WINDOWS-001`.

No raw pitfall log was needed. No artifact, manifest, ledger, replay, or data was
created or rebuilt. No backend restart is required. Independent integration is
required before main consumption. Promotion, paper, live, private, order,
real-order, transfer, and withdraw permissions all remain false.
