"""JARVIS trading commands for the terminal.

    jarvis quote AAPL TSLA            prices (names work too: jarvis quote apple)
    jarvis portfolio                  account value, today's change, biggest movers
    jarvis positions                  everything you own
    jarvis cash                       buying power
    jarvis market                     is the market open?
    jarvis buy 5 AAPL                 buy shares        (also: jarvis buy $100 of NVDA)
    jarvis sell 2 TSLA --limit 300    limit order       (also: jarvis sell all TSLA)
    jarvis orders cancel              cancel open orders (live mode)
    jarvis watch                      show your watchlist   (jarvis watch add AMD / jarvis watch remove AMD)
    jarvis alerts                     list price alerts     (jarvis alert TSLA above 300 / jarvis alerts cancel)
    jarvis dashboard                  live-updating screen of your portfolio + watchlist (Ctrl+C to stop)
    jarvis trades                     history of orders JARVIS has placed
    jarvis login                      log in to Robinhood (do this once; approve on your phone if asked)
    jarvis mode                       paper or live?
    jarvis paper reset                start the paper account over
"""

import argparse
import json
import sys
import time

from jarvis_core.config import load_config
from jarvis_core.errors import FriendlyError, report


def make_desk(cfg):
    from jarvis_core.trading import TradingDesk
    return TradingDesk(cfg, notify=lambda m: print(f"\n*** {m}\n"))


def place(desk, side, words):
    text = " ".join(words)
    reply = desk.prepare_order(side, text, original=text)
    print(reply)
    if desk.pending is None:
        return 1
    if desk.broker.live:
        print("\n  !!! This is a REAL order with REAL money. !!!")
        answer = input('  Type "yes" to place it, anything else to cancel: ').strip().lower()
        ok = answer == "yes"
    else:
        answer = input("  Place this paper trade? (y/n): ").strip().lower()
        ok = answer in ("y", "yes")
    if not ok:
        desk.pending = None
        print("Cancelled. Nothing was placed.")
        return 1
    print(desk.confirm("yes", typed_yes=True))
    return 0


def dashboard(desk, seconds):
    from jarvis_core.trading import friendly, money, pct_phrase
    while True:
        lines = []
        try:
            snap = desk.snapshot(max_age=0)
            lines.append(f" {'LIVE' if desk.broker.live else 'PAPER'} ACCOUNT   value {money(snap.total)}   "
                         f"today {money(snap.day_change)}   cash {money(snap.cash)}")
            lines.append("")
            lines.append(f" {'SYMBOL':8}{'QTY':>10}{'PRICE':>12}{'TODAY':>12}{'VALUE':>14}{'TOTAL P/L':>14}")
            for p in sorted(snap.positions, key=lambda p: p.value, reverse=True):
                day = pct_phrase((p.price - p.prev_close) / p.prev_close * 100) if p.prev_close else "-"
                lines.append(f" {p.symbol:8}{p.quantity:>10.4g}{money(p.price):>12}{day:>12}{money(p.value):>14}"
                             f"{money(p.total_gain):>14}")
            if not snap.positions:
                lines.append("   (no positions)")
        except FriendlyError as e:
            lines.append(str(e))
        if desk.state["watchlist"]:
            lines.append("")
            lines.append(" WATCHLIST")
            for sym in desk.state["watchlist"]:
                try:
                    q = desk.data.quote(sym)
                    lines.append(f"   {sym:8}{money(q.price):>12}{pct_phrase(q.change_pct):>14}   {friendly(sym)}")
                except Exception:
                    lines.append(f"   {sym:8}  unavailable")
        if desk.state["alerts"]:
            desk.check_alerts()
            lines.append("")
            lines.append(" " + desk.alerts_reply())
        from jarvis_core.trading import market_status
        lines.append("")
        lines.append(" " + market_status()[1])
        lines.append(f" Updated {time.strftime('%H:%M:%S')}  -  refreshing every {seconds}s  -  Ctrl+C to stop")
        sys.stdout.write("\033[2J\033[H" + "\n".join(lines) + "\n")
        sys.stdout.flush()
        time.sleep(seconds)


def main(argv=None):
    p = argparse.ArgumentParser(prog="jarvis", description="JARVIS trading commands",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("command")
    p.add_argument("args", nargs="*")
    p.add_argument("--limit", type=float, default=None, help="limit price for buy/sell")
    p.add_argument("--every", type=int, default=15, help="dashboard refresh seconds")
    p.add_argument("--debug", action="store_true")
    a = p.parse_args(argv)
    cfg = load_config()
    cmd = a.command.lower()
    words = list(a.args)

    try:
        desk = make_desk(cfg)
        if cmd in ("quote", "price", "quotes"):
            if not words:
                print("Which stock? e.g.  jarvis quote AAPL")
                return 1
            for w in words:
                sym = desk.resolve(w, w, strict=True)
                print(desk._safe_quote(sym) if sym else f"I don't recognise '{w}'.")
        elif cmd in ("portfolio", "account", "summary"):
            print(desk.portfolio_reply())
        elif cmd in ("positions", "holdings"):
            print(desk.positions_reply())
        elif cmd in ("cash", "buying-power", "bp"):
            print(desk.buying_power_reply())
        elif cmd == "market":
            from jarvis_core.trading import market_status
            print(market_status()[1])
        elif cmd in ("buy", "sell"):
            if a.limit:
                words += ["at", str(a.limit)]
            return place(desk, cmd, words)
        elif cmd == "orders":
            if words and words[0] == "cancel":
                print(desk.cancel_orders_reply())
            else:
                if desk.broker.live:
                    orders = desk.broker.rh().orders.get_all_open_stock_orders() or []
                    print(f"{len(orders)} open order(s).")
                    for o in orders:
                        print(f"  {o.get('side')} {o.get('quantity')} @ {o.get('price')}  state={o.get('state')}")
                else:
                    print("Paper trades fill instantly - there are no open orders.")
        elif cmd in ("watch", "watchlist"):
            if len(words) >= 2 and words[0] in ("add", "remove", "rm", "del"):
                sym = desk.resolve(words[1], words[1], strict=True)
                if not sym:
                    print(f"I don't recognise '{words[1]}'.")
                    return 1
                print(desk.watch_add(sym) if words[0] == "add" else desk.watch_remove(sym))
            else:
                print(desk.watchlist_reply())
        elif cmd in ("alert", "alerts"):
            if words and words[0] in ("cancel", "clear"):
                sym = desk.resolve(words[1], words[1], strict=True) if len(words) > 1 else None
                print(desk.cancel_alerts(sym))
            elif len(words) >= 3:
                sym = desk.resolve(words[0], words[0], strict=True)
                if not sym or words[1] not in ("above", "below", "over", "under"):
                    print("Usage:  jarvis alert TSLA above 300")
                    return 1
                print(desk.add_alert(sym, words[1], float(words[2].replace("$", ""))))
                print("(Alerts are checked while JARVIS or 'jarvis dashboard' is running.)")
            else:
                print(desk.alerts_reply())
        elif cmd in ("dashboard", "dash", "ticker"):
            dashboard(desk, max(5, a.every))
        elif cmd in ("trades", "history", "log"):
            if not desk.log_path.exists():
                print("No trades yet.")
            else:
                for line in desk.log_path.read_text(encoding="utf-8").splitlines()[-25:]:
                    r = json.loads(line)
                    print(f"{r['time']}  [{r['mode']}]  {r['side']} {r['quantity'] or ('$' + str(r['dollars']))} "
                          f"{r['symbol']}  ->  {r['result']}")
        elif cmd == "login":
            print("Logging in to Robinhood... (if Robinhood asks for a code or app approval, do it now)")
            desk.robinhood.rh()
            print("[OK] Logged in. Robinhood remembers this login for a while, so JARVIS can use it.")
            print(desk.portfolio_reply() if desk.broker.live else "Tip: set TRADING_MODE=live in .env to trade "
                  "for real. Prices now come from Robinhood.")
        elif cmd == "mode":
            print(desk.mode_reply())
        elif cmd == "paper":
            if words and words[0] == "reset":
                if input("Reset the paper account to its starting cash? (y/n): ").strip().lower().startswith("y"):
                    print(desk.handle("reset my paper account") or "")
            else:
                print(desk.portfolio_reply())
        else:
            print(__doc__)
            return 1
    except KeyboardInterrupt:
        print()
        return 0
    except Exception as e:
        report(e, cmd, show_trace=a.debug)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
