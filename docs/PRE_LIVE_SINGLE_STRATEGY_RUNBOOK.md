# Pre-Live Single Strategy Runbook

This runbook is for a small-funds, single-strategy workflow. It is command-first and intentionally stops at paper-only review evidence. Live trading remains frozen in this baseline.

## Overview

Start here:

```bash
python -m quant_us.cli pre-live next-step --data-root data --strategy etf_rotation
```

The older overview surface remains useful for a fuller status panel:

```bash
python -m quant_us.cli overview --data-root data --strategy etf_rotation --initial-cash 10000
```

With an explicit 30-day validation state:

```bash
python -m quant_us.cli overview \
  --data-root data \
  --strategy etf_rotation \
  --initial-cash 10000 \
  --validation-state data/reports/paper_production/validation_state.json
```

Read the three phase lines:

- `simulated: READY` means local simulated evidence can proceed to paper evidence review.
- `paper: BLOCKED_CREDENTIALS` means paper credentials are missing from `APCA_API_KEY_ID` or `APCA_API_SECRET_KEY`.
- `paper: BLOCKED_REVIEW` means credentials may be present, but evidence registry or human paper-review evidence is not acceptable.
- `paper: BLOCKED_VALIDATION` means review is acceptable, but 30-day paper validation evidence still blocks.
- `live: FROZEN` means no live order path is available from this workflow.

The `next_action` line is the command to run next.

## Paper Submit Preflight

Before any small-scale paper submit attempt, run the fail-closed preflight:

```bash
python -m quant_us.cli pre-live paper-submit-preflight \
  --data-root data \
  --strategy etf_rotation \
  --validation-state data/reports/paper_production/validation_state.json
```

This command is review-only. It does not instantiate a broker client, does not start paper runtime, and does not submit orders.

External blockers are printed explicitly:

- `market_hours`: requires the regular US equity session to be open.
- `paper_credentials`: requires `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`; if `APCA_API_BASE_URL` is set, it must be the Alpaca paper endpoint.
- `paper_review_evidence`: requires saved paper-review evidence with no pending manual review.

The preflight also reports `paper_validation`. Any blocker returns a non-zero exit code.

## Common Commands

Simulated readiness:

```bash
python -m quant_us.cli readiness --profile simulated --data-root data
```

Evidence registry status and rebuild:

```bash
python -m quant_us.cli report evidence-registry --data-root data
python -m quant_us.cli research evidence-registry-rebuild --data-root data
```

Paper validation evidence:

```bash
python -m quant_us.cli report paper-validation --data-root data
```

Paper credential/readiness review:

```bash
python -m quant_us.cli readiness \
  --profile paper \
  --data-root data \
  --validation-state data/reports/paper_production/validation_state.json \
  --check-credentials
```

Live review-only evidence:

```bash
python -m quant_us.cli readiness \
  --profile live \
  --data-root data \
  --validation-state data/reports/paper_production/validation_state.json \
  --check-credentials
```

## Boundaries

- `overview`, `readiness`, and `report` are evidence surfaces only.
- Paper requires credentials, clean validation evidence, and separate human paper review.
- Alpaca paper order submission is available only for the paper endpoint and requires both runtime submit selection and `QUANT_ALPACA_PAPER_NETWORK_SUBMIT=true`.
- Live is frozen here even if readiness evidence passes.
- Do not treat any report output as broker-write authorization.

## Paper Submit Setup

After human paper review approval, the operator still has to opt in:

```bash
export APCA_API_KEY_ID=...
export APCA_API_SECRET_KEY=...
export APCA_API_BASE_URL=https://paper-api.alpaca.markets
export QUANT_ENABLE_ALPACA_PAPER_ADAPTER=true
export QUANT_ALPACA_PAPER_NETWORK_SUBMIT=true
```

The runtime must also be configured with `paper_broker=alpaca`, `submit_orders=true`, and the explicit paper-submit selection. This enables Alpaca paper only; live remains frozen.
