# US V3 Paper OMS Reconciliation Contract

Goal: `US-V3-PAPER-OMS-RECONCILIATION-01`

This US-only application service hardens paper OMS engineering behavior without
starting paper execution. It accepts only injected fixture callbacks and
broker-state snapshots. It does not import a broker SDK, inspect credentials,
write the paper queue, or call private/order/live endpoints.

## Lifecycle

The durable lifecycle covers `created`, `risk_checked`, `accepted`, `partial`,
`filled`, `cancel`, `rejected`, `expired`, `unknown`, and `reconciled`.
`cancel_pending` remains a distinct operational state: a cancel request is not
a cancel confirmation, and new orders stay halted until injected reconciliation
or a terminal confirmation resolves it.

Invalid or out-of-order callbacks transition the local order to `unknown`,
record a structured blocker, create no fill, and halt new orders. Duplicate
callback IDs and fill IDs cannot change fill, position, or cash accounting.

## Atomic persistence and recovery

Every mutation uses `quant_us.live.paper_ledger_uow` to commit order, fill,
position, cash, audit, and OMS state bytes within one recoverable transaction.
A failed multi-file replacement rolls all files back. On restart, incomplete
transactions are recovered before any new event is accepted.

All JSONL files are parsed strictly. A truncated or malformed row blocks
recovery rather than being silently ignored. Cash and positions are recomputed
from fills and compared with the persisted state hash and ledger counts.

## Reconciliation and credential review

Reconciliation consumes an injected snapshot. Cash, positions, and order state
breaks halt new orders and remain fail-closed. A later matching snapshot may
mark terminal or previously unknown orders `reconciled`.

Credential review evidence contains only reviewer, reviewed time, broker,
hashed account identity, approval ticket, and permission conclusion. Secret,
token, password, passphrase, raw account, private endpoint, and order endpoint
access are outside this contract.

## Evidence boundary

Fixture execution drills may be classified `quality_checked`; they are not real
paper evidence or a production event ledger. Full temporary ledgers are deleted
with the system temporary directory. The durable bounded report binds the code
commit/tree, configuration hash, scenario results, and safety flags.

Paper runner, paper queue, broker calls, private/order endpoints, real orders,
paper permission, and live permission all remain disabled.
