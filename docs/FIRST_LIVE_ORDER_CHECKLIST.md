# First Live Order Checklist

> Print this page. Tick every box before executing the first live order.
> Do not skip any step. If any step is unclear, stop and ask.

---

## 1. Account Verification

- [ ] Broker account is funded with the expected capital
- [ ] Broker account is NOT the paper trading account
- [ ] API keys are for the LIVE account (not paper keys)
- [ ] API keys have been verified with `curl` or broker dashboard
- [ ] QUANT_LIVE_SUBMISSION_ENABLED is set to `true`
- [ ] Live endpoint returns 200 (not 403 / connection refused)

## 2. Symbol / Quantity / Price Verification

- [ ] Symbol is correct (e.g. SPY, not SPX or some illiquid symbol)
- [ ] Side is correct (buy / sell)
- [ ] Quantity is within the approved envelope
- [ ] Limit price (if limit order) is realistic and executable
- [ ] Order type is allowed by the envelope (limit only by default)
- [ ] Time in force is appropriate (DAY / GTC)

## 3. Envelope Verification

- [ ] Envelope exists and is loaded into the manager
- [ ] Max order notional >= order notional (quantity x limit_price)
- [ ] Max daily notional >= order notional
- [ ] Max gross exposure % >= position size / total capital
- [ ] Max single symbol exposure % >= position size / total capital
- [ ] Max daily loss % is within tolerance
- [ ] Max drawdown % is within tolerance
- [ ] Market orders are disabled (unless explicitly approved)
- [ ] Short selling is disabled (unless explicitly approved)
- [ ] Pre/post market trading is disabled (unless explicitly approved)

## 4. Approval Verification

- [ ] Approval ID is loaded
- [ ] Approval status is `APPROVED` (not `DRAFT` or `REJECTED`)
- [ ] Approval has not expired
- [ ] Approval strategy ID matches the executing strategy
- [ ] Approval strategy version matches the executing version
- [ ] Approved symbols include the target symbol
- [ ] Approver is a known entity (not self-approved unless policy allows)

## 5. Emergency Stop Verification

- [ ] Emergency stop controller is initialized
- [ ] Emergency stop state is `ARMED` (not `TRIGGERED`)
- [ ] No active emergency stop incidents
- [ ] Rollback plan is documented and accessible
- [ ] Operator knows how to trigger emergency stop:
      `ctrl.trigger("manual_stop", triggered_by="operator")`

## 6. Rollback Plan Ready

- [ ] Broker dashboard is open in a browser
- [ ] Operator knows how to cancel an open order on the broker dashboard
- [ ] Operator knows how to close a position on the broker dashboard
- [ ] In case of timeout: operator knows to check broker status externally
- [ ] Phone / secondary contact method for broker support is available

## 7. Real Money Risk Acknowledgement

- [ ] I understand that this order uses REAL MONEY
- [ ] I understand that losses are REAL and not simulated
- [ ] I have reviewed the maximum possible loss
- [ ] I accept the maximum possible loss
- [ ] I have confirmed with `--i-understand-this-is-real-money`

## 8. Post-Submit Freeze Understanding

- [ ] I understand that after submission, the system will freeze
- [ ] I understand that a second order is BLOCKED by `SubmitOnceLock`
- [ ] I understand that the freeze must be manually released
- [ ] I understand that the freeze persists across restarts

## 9. No-Second-Order Understanding

- [ ] I understand that G5 allows exactly ONE live order
- [ ] I understand that a second order requires manual lock release
- [ ] I understand that even after release, G5 does not auto-submit
- [ ] I understand that the dossier result is `STOP_AND_REVIEW`, not `CONTINUE`
- [ ] I understand that progressing to G6 requires full manual review

---

## Final Sign-Off

**Ticket ID**: `____________________`

**Operator Name**: `____________________`

**Date**: `____________________`

**Signature**: `____________________`

---

*Tick every box. Leave no box blank. If in doubt, stop.*
