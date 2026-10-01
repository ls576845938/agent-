# Live Pilot Runbook (G3)

## What is Small Live Pilot?

Small Live Pilot (G3) is the governance and readiness phase that establishes the human approval, risk envelope, and emergency response framework required before ANY real money can be traded.

**G3 does NOT submit real orders.** It only prepares the system for eventual live trading under strict controls.

## Why G3 Does Not Auto-Start Live Trading

Even after G2 (shadow live validation passes), the live profile remains NOT READY. G3 adds:
1. **Human approval** — no machine-only decision to trade real money
2. **Risk envelope** — ultra-conservative limits ($1,000 max capital, $100 max order)
3. **Emergency stop** — rapid response to any anomaly
4. **Dry-run proof** — full simulation of first live order without real submission
5. **Go/No-Go dossier** — comprehensive evidence package for human review

## CLI Commands

### Approval Management

```bash
# Create an approval request
python3 -m quant_us.cli live-pilot approval-create \
  --approval-id pilot-001 \
  --strategy etf_rotation \
  --strategy-version 1.0.0 \
  --symbols SPY,QQQ \
  --requested-by "trader-name" \
  --capital 1000

# List all approvals
python3 -m quant_us.cli live-pilot approval-list

# Inspect an approval
python3 -m quant_us.cli live-pilot approval-inspect --approval-id pilot-001

# Approve (human action required)
python3 -m quant_us.cli live-pilot approval-approve \
  --approval-id pilot-001 \
  --manual "approver-name"

# Reject
python3 -m quant_us.cli live-pilot approval-reject \
  --approval-id pilot-001 \
  --reason "Risk limits need adjustment"
```

### Risk Envelope Management

```bash
# Create ultra-conservative risk envelope
python3 -m quant_us.cli live-pilot risk-envelope-create \
  --envelope-id env-001 \
  --symbols SPY,QQQ

# Inspect envelope
python3 -m quant_us.cli live-pilot risk-envelope-inspect --envelope-id env-001

# Validate an order against envelope
python3 -m quant_us.cli live-pilot risk-envelope-validate \
  --envelope-id env-001 \
  --notional 100
```

### Dry-Run Execution

```bash
# Run live pilot dry-run (NO real orders)
python3 -m quant_us.cli live-pilot dry-run \
  --approval-id pilot-001 \
  --envelope-id env-001 \
  --symbols SPY,QQQ
```

### Emergency Stop

```bash
# Trigger emergency stop
python3 -m quant_us.cli live-pilot emergency-stop-trigger \
  --reason manual_stop

# Check status
python3 -m quant_us.cli live-pilot emergency-stop-status

# Acknowledge (required before resolution)
python3 -m quant_us.cli live-pilot emergency-stop-acknowledge

# Resolve when safe
python3 -m quant_us.cli live-pilot emergency-stop-resolve

# Generate rollback plan
python3 -m quant_us.cli live-pilot rollback-plan --reason recon_fail
```

### Go/No-Go Dossier

```bash
# Generate G3 dossier
python3 -m quant_us.cli live-pilot dossier \
  --output reports/live_pilot_go_no_go.md
```

## Default Risk Limits

| Limit | Value |
|-------|-------|
| Max Total Capital | $1,000 |
| Max Order Notional | $100 |
| Max Daily Notional | $300 |
| Max Daily Orders | 3 |
| Max Gross Exposure | 10% |
| Max Single Symbol | 5% |
| Max Daily Loss | 0.5% |
| Market Orders | BLOCKED |
| Pre/Post Market | BLOCKED |
| Short Selling | BLOCKED |
| Margin | BLOCKED |
| Options | BLOCKED |

## Emergency Stop Trigger Reasons

- `manual_stop` — human operator triggers stop
- `recon_fail` — reconciliation failure
- `broker_error` — broker connectivity error
- `data_stale` — market data is stale
- `daily_loss_limit` — daily loss limit hit
- `drawdown_limit` — drawdown limit hit
- `duplicate_order_detected` — idempotency violation
- `unknown_order_state` — order in unexpected state
- `external_order_detected` — order detected outside system
- `kill_switch_triggered` — kill switch activated
- `max_consecutive_losses` — consecutive loss limit
- `risk_envelope_breach` — any envelope limit breached

## Important Safety Notes

- **NEVER** bypass the approval gate
- **NEVER** increase risk limits without human review
- **ALWAYS** acknowledge emergency stops before resolving
- **ALWAYS** generate rollback plan after an incident
- G3 dry-run NEVER submits real orders
- Live profile remains NOT READY even after G3 completes
- Human review is REQUIRED for G4 entry
