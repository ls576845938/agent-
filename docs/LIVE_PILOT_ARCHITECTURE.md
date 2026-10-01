# Live Pilot Architecture (G3)

## Overview

G3 establishes the governance layer required before any real money can be traded. It does NOT submit real orders — it only provides approval, risk envelope, emergency response, and evidence generation.

## Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    Human Approval Layer                       │
│  ┌─────────────────┐    ┌──────────────────────┐             │
│  │HumanApprovalGate │    │LivePilotApprovalRequest│           │
│  │ - check()        │    │ - approval_id         │           │
│  │ - approve()      │    │ - strategy_id         │           │
│  │ - reject()       │    │ - symbols             │           │
│  │ - inspect()      │    │ - status              │           │
│  └────────┬─────────┘    │ - expires_at           │           │
│           │              └──────────────────────┘            │
│           │  ✓ status=APPROVED  ✓ not expired                │
│           │  ✓ strategy_version match  ✓ symbols match        │
└───────────┼──────────────────────────────────────────────────┘
            │
┌───────────▼──────────────────────────────────────────────────┐
│                    Risk Envelope Layer                        │
│  ┌──────────────────┐  ┌────────────┐  ┌───────────────┐    │
│  │LivePilotRiskEnvelope│ │CapitalLimiter│ │NotionalLimiter│   │
│  │ - max_capital       │ │ - check()   │ │ - check()     │    │
│  │ - max_order_notional│ └────────────┘ └───────────────┘    │
│  │ - max_daily_loss    │  ┌────────────┐  ┌───────────────┐  │
│  │ - allowed_types     │  │ExposureLimiter│ │OrderTypeValidator│ │
│  │ - allowed_sessions  │  │ - check()   │ │ - check()     │    │
│  └──────────────────┘  └────────────┘ └───────────────┘    │
└──────────────────────────────────────────────────────────────┘
            │
┌───────────▼──────────────────────────────────────────────────┐
│                    Dry-Run Executor                           │
│  LivePilotDryRunExecutor (14 steps)                           │
│  1. Load approval    5. Check dossier    9. Signal calc      │
│  2. Load envelope    6. Live endpoint   10. Target pos        │
│  3. Paper 30d        7. Env gate        11. Order intent     │
│  4. Shadow 5d        8. Confirm-live    12. Risk check       │
│                          ALL: real_submit=False               │
└──────────────────────────────────────────────────────────────┘
            │
┌───────────▼──────────────────────────────────────────────────┐
│                    Emergency Response                         │
│  ┌─────────────────────┐  ┌─────────────────┐                │
│  │EmergencyStopController│  │RollbackPlanGenerator│           │
│  │ ARMED → TRIGGERED    │  │ - 10 action steps  │           │
│  │ → ACKNOWLEDGED       │  │ - reduce-only inst. │           │
│  │ → RESOLVED           │  │ - manual review req. │           │
│  └─────────────────────┘  └─────────────────┘               │
└──────────────────────────────────────────────────────────────┘
            │
┌───────────▼──────────────────────────────────────────────────┐
│                    Go/No-Go Dossier                           │
│  LivePilotGoNoGoDossier                                      │
│  1. Paper Evidence      4. Risk Envelope                     │
│  2. Shadow Evidence     5. Safety Evidence                   │
│  3. Approval Evidence   6. Decision                          │
│  Decision: NOT_READY / READY_FOR_HUMAN_REVIEW / BLOCKED      │
└──────────────────────────────────────────────────────────────┘
```

## Key Safety Invariants

1. **No real orders through G3 modules** — all modules are read-only or governance-only
2. **Human approval required** — no machine-only decision
3. **Risk envelope enforced** — even during dry-run, all limits are checked
4. **Emergency stop armed** — always available, blocks new positions when triggered
5. **Dry-run only** — real_submit=False at every level
6. **Approval expires** — 7-day expiry, must be renewed
7. **Reduce-only on fail** — any anomaly forces reduce-only mode
