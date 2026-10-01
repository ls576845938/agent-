# Exchange API Key Permission Policy

Purpose: prevent a personal BTC trading system from turning API credentials into a single point of catastrophic loss.

## Key classes

- `data_readonly`: market/account read-only where needed.
- `paper_trade`: demo or sandbox trading.
- `live_trade`: live trading without withdrawal permission.
- `admin_manual`: manually held account administration; never loaded by the bot.

## Hard rules

1. A trading bot must never use API keys with withdrawal permission.
2. Live trade keys must use IP allowlisting where the venue supports it.
3. Data, paper, and live keys must be separate.
4. Keys must be scoped to the minimum venue, account, and permission set.
5. Keys must not be committed to git, notes, screenshots, logs, crash reports, or markdown.
6. Secrets must be loaded from environment variables or a local secret store.
7. Production logs must redact API key, secret, passphrase, JWT, signature, and auth headers.
8. If a key leaks or is suspected to leak, revoke first and investigate after.

## Runtime checks

At startup, the system must verify:

- active mode: `read_only`, `paper`, or `live`;
- key permission;
- withdrawal disabled;
- IP allowlist expected/enforced if available;
- environment target matches mode;
- account id and venue id match config;
- no live order tool is registered under read-only mode.

## Rotation policy

Minimum rotation triggers:

- suspected leak;
- machine compromise;
- public repo exposure;
- unexplained order/fill/account activity;
- switching hosting environment;
- changing live-trading operator;
- exchange security notice;
- periodic review interval reached.

## Incident response

If credentials may be compromised:

1. Revoke the key on the exchange.
2. Cancel open orders manually or through a fresh trusted channel.
3. Disable the bot.
4. Export account activity.
5. Reconcile fills, balances, and withdrawals.
6. Rotate related secrets.
7. Write incident review.
8. Add a test or control that would have detected the issue earlier.

## Development constraints

- Never print full config when config may contain secrets.
- Never store secrets in Obsidian.
- Never pass secrets into LLM prompts.
- Never create a live key for testing adapter parsing.
- Any code path that enables live trading must make read-only/paper/live mode explicit.

