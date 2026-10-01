# G6 Micro Live Pilot Runbook

## What is G6?
G6 extends G5's single one-shot order into a controlled micro pilot episode of
up to 3-5 orders, each individually approved, executed, and reviewed.

## What G6 is NOT
- NOT full automated live trading
- NOT continuous trading
- NOT removing the one-shot constraint (each order is still one-shot)
- NOT removing freeze (system freezes after each order)
- NOT increasing capital beyond micro limits (max $300 cumulative)
- NOT removing manual approval (every order requires explicit human approval)
- NOT IBKR, Redis, WebSocket, or new strategy development

## Prerequisites
1. G5 single order successfully executed and reviewed
2. G5PostTradeDossier generated and reviewed
3. FinalHumanConfirmationGate passed for G5
4. All post-trade reconciliation clean
5. Execution quality report reviewed
6. Manual decision to proceed to G6

## Operations

### Step 1: Review G5 Results
- Locate G5 dossier: `data/live_pilot/post_trade_dossier_*.json`
- Review execution quality, slippage, commission
- Confirm no unresolved incidents

### Step 2: Create Second One-Shot Review
```bash
python3 -m quant_us.cli live-pilot second-review --ticket-id <g5_ticket_id> --manual-review approve --reviewer <your_name>
```
- If BLOCKED: resolve the blocking condition
- If APPROVED_FOR_SECOND_ONE_SHOT_REVIEW: proceed

### Step 3: Create Micro Pilot Episode
```bash
python3 -m quant_us.cli live-pilot episode create --strategy-id etf_rotation --symbols SPY
```
- Default max 3 orders, $300 cumulative notional, $10 max loss

### Step 4: Create Second Ticket
Follow G5 ticket creation process, referencing the episode.

### Step 5: Check Cumulative Risk
```bash
python3 -m quant_us.cli live-pilot risk-status --episode-id <id>
```
- If PASS: can proceed
- If BLOCK_NEW_ORDER: resolve before proceeding
- If TERMINATE_EPISODE: episode must end

### Step 6: Execute Second One-Shot
Same as G5 execution flow:
```bash
python3 -m quant_us.cli live-pilot execute --ticket-id <ticket_id> --dry-run  # ALWAYS dry-run first
# After confirming dry-run output:
python3 -m quant_us.cli live-pilot execute --ticket-id <ticket_id> --execute-live-pilot --confirm-live --i-understand-this-is-real-money --confirm-ticket <ticket_id>
```

### Step 7: Post-Order Freeze and Review
After each order, the system freezes. Review:
- Post-trade reconciliation
- Execution quality
- Cumulative risk status

### Step 8: Generate Exit Plan (if holding positions)
```bash
python3 -m quant_us.cli live-pilot exit-plan create --episode-id <id> --ticket-id <ticket_id> --symbol <sym> --qty <n> --entry-price <p>
python3 -m quant_us.cli live-pilot exit-plan inspect --exit-plan-id <id>
```

### Step 9: Execute Exit (DRY-RUN FIRST)
```bash
python3 -m quant_us.cli live-pilot exit-plan execute --exit-plan-id <id> --dry-run
# Review dry-run output, then if approved:
python3 -m quant_us.cli live-pilot exit-plan execute --exit-plan-id <id>
```

### Step 10: Generate Episode Final Dossier
```bash
python3 -m quant_us.cli live-pilot episode final-dossier --episode-id <id>
```

## Termination Conditions
- Max order count reached (default 3)
- Max cumulative loss reached ($10)
- Manual termination via CLI
- Emergency stop triggered
- Recon failure
- Unresolved incident

## Emergency Procedures
1. Trigger emergency stop: `python3 -m quant_us.cli live-pilot emergency-stop trigger --reason "..." `
2. Check status: `python3 -m quant_us.cli live-pilot emergency-stop status`
3. Generate exit plan for any open positions
4. Contact broker support if needed
