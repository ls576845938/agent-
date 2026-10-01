# BTC API Key Permission Audit Runbook

## Purpose

This runbook closes the only remaining BTC attachment blocker once redacted permission facts are available.

Do not paste, store, commit, or send any real API key, secret, passphrase, token, signature, authorization header, private account id, or exchange login data.

## Current Gate

`artifacts/btc_completion_audit/latest/btc_completion_audit.json` currently shows:

- `total=9`
- `complete=8`
- `blocked=1`
- remaining blocker: `P0-4 api_key_permission_audit`

This is expected until redacted records prove:

- `data_readonly`, `paper_trade`, and `live_trade` are separate records.
- withdraw permission is disabled for all bot-usable keys.
- live trade key has IP allowlist configured where the venue supports it.
- `mode` matches `environment_target`.
- no secret-like fields are present in the input or output artifact.

## Generate Template

Run from repository root:

```powershell
python scripts/build_btc_api_key_permission_audit.py --write-template artifacts/btc_security/latest/btc_api_key_permission_records.template.json
```

The generated template is ignored by git under `artifacts/`. Copy it to a local non-committed path before filling it.

## Allowed Record Fields

Only these fields are allowed:

- `key_class`: one of `data_readonly`, `paper_trade`, `live_trade`.
- `venue`: exchange venue label, for example `okx` or `binance_usdm`.
- `mode`: one of `read_only`, `paper`, `live`.
- `permission_read`: boolean.
- `permission_trade`: boolean.
- `permission_withdraw`: boolean. Must be `false`.
- `ip_allowlist_configured`: boolean.
- `environment_target`: must match `mode`.
- `account_label`: optional redacted label.
- `redacted_identifier`: redacted identifier such as `paper-****1234`; it must not be a real key.
- `raw_metadata`: optional non-secret notes only.

## Forbidden Input

Never include fields or values containing:

- API key
- secret
- passphrase
- token
- signature
- authorization header
- private account identifiers

The loader intentionally blocks secret-like field names and keeps the audit blocked.

## Build Audit

After filling a redacted local records file:

```powershell
python scripts/build_btc_api_key_permission_audit.py --records <local-redacted-records.json>
python scripts/build_btc_gate_dashboard.py
python scripts/build_btc_completion_audit.py
```

## Expected Result

The API key audit can become `complete` only if the input includes all three key classes and all checks pass.

Even when this audit completes, `live_order_allowed` remains `false`; live promotion still requires separate human authorization and live gate review.
