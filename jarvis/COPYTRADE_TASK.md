# Daily copy-trade task (McCaul + Khanna)

Create this as a scheduled task on claude.ai, with the **Robinhood connector attached**:

- **Schedule:** weekdays at 1:17 PM Eastern (during market hours, so $10 dollar-amount orders can fill)
- **Connector:** robinhood
- **Prompt:** everything in the box below

```
You are running a daily copy-trading check for the user, using the Robinhood connector. The user asked for
this: copy the publicly disclosed stock trades of two US politicians, with every order requiring the user's
manual approval in the Robinhood app. If the Robinhood tools are not available, place nothing and report that.

ACCOUNT: only ever use Robinhood account_number 469431811 (nickname "MCP"). Never touch any other account.

STEP 1 - Safety gate. Call get_trade_approval_setting for 469431811.
- If human_must_approve_trades is FALSE: do NOT place any orders today. Still do steps 2-4, report what you
  WOULD have proposed, and remind the user to turn on trade approvals for the MCP account in the Robinhood app.
- If TRUE: you may place orders as described below; each one goes to the user's Robinhood app to approve.

STEP 2 - New disclosures. Call get_politician_trades for "Michael McCaul" and for "Ro Khanna". Keep only
entries with asset_type EQUITY whose disclosure_date is within the last 4 calendar days (today included).
Ignore options and anything older.

STEP 3 - Current state. Call get_portfolio (buying power), get_equity_positions, get_equity_orders and
get_trade_approvals for 469431811.

STEP 4 - Decide (rules set by the user; do not deviate):
- BUY: for each new disclosed BUY, propose a market BUY of exactly $10.00 (dollar_amount "10.00", type
  market, regular_hours). Skip a symbol if the account already holds it, has an open order or pending
  approval for it, or it isn't tradable. At most 5 new buys per day, most recent disclosures first. Never
  exceed buying power; if buying power is below $10, propose nothing and say so.
- SELL: if a new disclosed SELL is for a symbol this account holds, propose selling the entire position
  (market, full quantity) unless a sell order/approval for it is already pending.
- Never trade anything except these copy rules. Never place more than 6 orders in a run.

STEP 5 - Place (only if approvals are ON). For each proposed order call review_equity_order first. If it
reports customer_approval_required true and no order_checks alerts, call place_equity_order with the same
parameters and a fresh UUID ref_id. If review shows any order_checks alert, don't place it; report it.

STEP 6 - Report a short plain-English summary: today's new disclosures from each politician (source: Tip
Ranks; disclosures lag the real trade by up to 45 days), what was sent for approval, what was skipped and
why, current buying power, and whether trade approvals are on. If nothing new, say so in one line. These
are copies of public disclosures the user chose to follow, not recommendations.
```

## Before the first run

1. **Turn ON trade approvals** for the MCP account in the Robinhood app. Right now they're OFF, so the
   task will only report what it would buy, never place orders, until you do.
2. **Move money into the MCP account.** It has $1, and each copied buy is $10.
