# BTC-V3-PAPER-READINESS-SCHEMA-DRIFT-01

## Classification

- Category: `engineering`
- Owner: `btc_developer`
- Found by: `BTC-V3-FINAL-PAPER-READINESS-01`
- Gate impact: `blocks_gate`

## Reproduction

After running the current-HEAD gate rebuild:

```text
py -3 -m pytest tests/contracts/test_btc_paper_readiness_report.py \
  --basetemp <unique> -p no:cacheprovider
```

Result: `13 passed, 1 failed`.

The failing contract reports:

```text
jsonschema.ValidationError: 'commit' is a required property
```

The current builder emits the BTC artifact envelope fields such as
`source_head`, `code_commit`, `generated_at` and `decision`. The tracked
`schemas/btc_paper_readiness_report.schema.json` still requires the legacy
shape containing `commit`, `branch`, `asset`, `symbol` and other fields.

## Required repair

Choose one canonical BTC paper-readiness contract, migrate producer,
consumer and schema together, and retain fail-closed semantics. This final
review does not authorize changing the producer or schema.

## Acceptance

- Current builder output validates against the canonical tracked schema.
- Existing consumers use the same schema version and field meanings.
- Missing prerequisites still produce a valid blocked report.
- Paper/private/order/live flags remain false.

## Resolution

- Status: `retired_engineering_blocker`
- Goal: `BTC-V3-ENGINEERING-BLOCKER-CLOSURE-01`
- `btc_paper_readiness_report_v1` remains the BTC canonical contract.
- The current-HEAD builder now emits the complete canonical core fields and
  the schema also recognizes the current BTC artifact envelope.
- Both legacy ready fixtures and current-HEAD blocked fixtures validate
  against the same tracked schema. Missing evidence remains `blocked`,
  `paper_queue_status=locked`, and both paper authorization booleans false.
- No concrete runtime artifact or latest pointer was rebuilt by this repair.
