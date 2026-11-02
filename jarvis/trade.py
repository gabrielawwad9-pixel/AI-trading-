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
    jarvis backtest                   test the strategies on 15+ years of real prices (--capital 100 --start 2011)
    jarvis backtest --years           ...plus a year-by-year table
    jarvis strategy                   list strategies and what each one would hold today
    jarvis strategy use KEY           choose the strategy for autotrade (e.g. jarvis strategy use momentum)
    jarvis autotrade                  rebalance the PAPER account to the chosen strategy (run once a day)
    jarvis schedule [16:15]           run autotrade every weekday at that time (Windows Task Scheduler)
    jarvis unschedule                 stop the daily autotrade
    jarvis connect                    link your Robinhood account (asks for your login, saves it, logs in)
    jarvis login                      log in to Robinhood again (approve on your phone if asked)
    jarvis mode                       paper or live?
    jarvis paper reset                start the paper account over
"""

import argparse
import json
import re
import sys
import time

from jarvis_core.config import load_config
from jarvis_core.errors import FriendlyError, report


def set_env_values(path, values: dict):
    """Update KEY=value lines in a .env file (adding any that are missing), keeping everything else."""
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        example = path.with_name(".env.example")
        path.write_text(example.read_text(encoding="utf-8") if example.exists() else "", encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in values:
            lines[i] = f"{key}={_env_quote(values[key])}"
            done.add(key)
    for key, val in values.items():
        if key not in done:
            lines.append(f"{key}={_env_quote(val)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_quote(value: str) -> str:
    if value == "":
        return ""
    if "'" not in value:
        return f"'{value}'"                       # single quotes: taken literally (safe for # $ spaces)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def connect(cfg):
    import getpass
    import os
    from jarvis_core.config import ROOT
    from jarvis_core.trading import RobinhoodBroker, friendly, money, pct_phrase

    print("Link your Robinhood account")
    print("-" * 40)
    print("Your login is saved ONLY in the .env file in this folder on this laptop, and is only")
    print("ever sent to Robinhood. JARVIS stays in PAPER mode until you choose live trading.\n")
    user = input(f"Robinhood email{f' [{cfg.robinhood_username}]' if cfg.robinhood_username else ''}: ").strip()
    user = user or cfg.robinhood_username
    try:
        pw = getpass.getpass("Robinhood password (hidden as you type, then press Enter): ")
    except Exception:
        pw = input("Robinhood password: ")
    if not user or not pw:
        print("Cancelled - email and password are both needed.")
        return 1
    print("\nDo you use an authenticator app (like Google Authenticator) for Robinhood 2FA?")
    print("If so, paste the SETUP SECRET (the long code shown when you set it up - not the 6-digit")
    print("code). If you get texts or approve logins in the Robinhood app, just press Enter.")
    totp = input("Authenticator secret (or Enter to skip): ").strip().replace(" ", "")

    env_path = ROOT / ".env"
    set_env_values(env_path, {"ROBINHOOD_USERNAME": user, "ROBINHOOD_PASSWORD": pw,
                              "ROBINHOOD_TOTP_SECRET": totp})
    print(f"\n[OK] Saved to {env_path}")

    print("\nLogging in to Robinhood... if it asks for a code, or to approve the login in the")
    print("Robinhood app on your phone, do that now.\n")
    broker = RobinhoodBroker(user, pw, totp)
    broker.rh()
    print("[OK] Logged in!\n")
    snap = broker.snapshot()
    print(f"Account value:  {money(snap.total)}   (today {money(snap.day_change)})")
    print(f"Buying power:   {money(snap.cash)}")
    if snap.positions:
        print("Positions:")
        for p in sorted(snap.positions, key=lambda p: p.value, reverse=True):
            print(f"  {p.symbol:6} {p.quantity:>10.4g} shares  {money(p.value):>12}  "
                  f"{pct_phrase(p.total_gain_pct)} overall   {friendly(p.symbol)}")
    else:
        print("Positions:      none")
    mode = os.getenv("TRADING_MODE", cfg.trading_mode)
    print(f"\nJARVIS can now see your account and uses Robinhood's real-time prices.")
    if mode != "live":
        print("You're still in PAPER mode: 'buy'/'sell' use practice money. To trade for real, run")
        print("  jarvis settings   and set TRADING_MODE=live (and check MAX_ORDER_USD).")
    return 0


def _price_cache():
    from jarvis_core.config import ROOT
    return ROOT / "data" / "prices"


def backtest_cmd(capital, start, show_years, refresh=False):
    from jarvis_core import backtest as bt
    strategies = bt.all_strategies()
    symbols = sorted({c for st in strategies for c in st.symbols})
    print(f"Downloading daily prices for {', '.join(symbols)} (cached after the first run)...")
    px = bt.load_prices(symbols, start=start, cache_dir=_price_cache(), refresh=refresh)
    results = bt.run_all(strategies, px, capital=capital, start=start)
    print()
    print(bt.report(results, capital))
    if show_years:
        print()
        print(bt.year_table(results))
    print("\nStrategy keys (for 'jarvis strategy use KEY'): " + ", ".join(st.key for st in strategies))
    return 0


def strategy_cmd(desk, words):
    from jarvis_core import backtest as bt
    if len(words) >= 2 and words[0] == "use":
        try:
            st = bt.get_strategy(words[1])
        except KeyError:
            print("Unknown strategy. Options: " + ", ".join(x.key for x in bt.all_strategies()))
            return 1
        desk.state["strategy"] = st.key
        desk._save_state()
        print(f"Autotrade will now follow: {st.name} ({st.risk} risk)\n  {st.description}")
        return 0
    chosen = desk.state.get("strategy")
    strategies = bt.all_strategies()
    px = bt.load_prices({c for st in strategies for c in st.symbols}, cache_dir=_price_cache())
    print(f"Prices as of {px.index[-1]:%a %d %b %Y}\n")
    for st in strategies:
        t = bt.todays_targets(st, px)
        hold = ", ".join(f"{int(v * 100)}% {k}" for k, v in t.items()) or "100% cash"
        mark = "  <-- autotrade" if st.key == chosen else ""
        print(f"[{st.key}] {st.name} - {st.risk} risk{mark}\n    wants to hold: {hold}\n    {st.description}\n")
    if not chosen:
        print("Pick one with:  jarvis strategy use KEY")
    return 0


def autotrade_cmd(desk):
    """Rebalance the paper account to the chosen strategy's target. Paper only."""
    from jarvis_core import backtest as bt
    from jarvis_core.trading import Order, money
    if desk.broker.live:
        print("Autotrade only runs on the PAPER account in this version. Set TRADING_MODE=paper to use it.")
        print("(Real-money automation comes after the strategy has proven itself on paper.)")
        return 1
    key = desk.state.get("strategy")
    if not key:
        print("No strategy chosen yet. See them with  jarvis strategy  and pick one with  jarvis strategy use KEY")
        return 1
    st = bt.get_strategy(key)
    px = bt.load_prices(st.symbols, cache_dir=_price_cache(), refresh=True)
    targets = bt.todays_targets(st, px)
    snap = desk.broker.snapshot()
    total = snap.total
    have = {p.symbol: p for p in snap.positions}
    print(f"{st.name}: target = " + (", ".join(f"{int(v * 100)}% {k}" for k, v in targets.items()) or "100% cash")
          + f"   (paper account {money(total)})")
    # sells first (frees cash), then buys
    actions = []
    for sym, pos in have.items():
        want = targets.get(sym, 0.0) * total
        if pos.value - want > max(1.0, 0.02 * total):
            qty = pos.quantity if want < 1 else round((pos.value - want) / pos.price, 6)
            actions.append(Order("sell", sym, quantity=qty, est_price=pos.price))
    for sym, wt in targets.items():
        cur = have[sym].value if sym in have else 0.0
        diff = wt * total - cur
        if diff > max(1.0, 0.02 * total):
            actions.append(Order("buy", sym, dollars=round(diff * 0.995, 2)))   # small buffer for price moves
    if not actions:
        print("Already on target - nothing to do.")
        return 0
    for order in actions:
        result = desk.broker.place(order)
        desk._log_trade(order, result)
        print("  " + result)
    print(f"Paper account now: {money(desk.broker.snapshot().total)}")
    return 0


TASK_NAME = "JARVIS paper autotrade"


def schedule_cmd(when="16:15", remove=False):
    import subprocess
    from jarvis_core.config import ROOT
    if not sys.platform.startswith("win"):
        print("Automatic scheduling uses Windows Task Scheduler. On Mac/Linux add this to 'crontab -e':")
        print(f"  15 16 * * 1-5 cd {ROOT} && {sys.executable} trade.py autotrade >> autotrade.log 2>&1")
        return 1
    if remove:
        r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
        print("Daily autotrade stopped." if r.returncode == 0 else f"Couldn't remove it: {r.stderr.strip()}")
        return r.returncode
    if not re.fullmatch(r"\d{1,2}:\d{2}", when):
        print("Give the time as HH:MM in 24-hour format, e.g.  jarvis schedule 16:15")
        return 1
    log = ROOT / "autotrade.log"
    action = f'cmd /c cd /d "{ROOT}" && "{sys.executable}" trade.py autotrade >> "{log}" 2>&1'
    r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI",
                        "/TN", TASK_NAME, "/TR", action, "/ST", when.zfill(5)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Windows refused to create the task: {r.stderr.strip() or r.stdout.strip()}")
        return 1
    print(f"[OK] Paper autotrade will run every weekday at {when} (your laptop's time) while you're logged in.")
    print(f"     Results are written to {log} and 'jarvis trades'. Stop it with:  jarvis unschedule")
    return 0


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
    p.add_argument("--capital", type=float, default=100.0, help="backtest starting money")
    p.add_argument("--start", default="2011-01-01", help="backtest start date")
    p.add_argument("--years", action="store_true", help="backtest: show year-by-year returns")
    p.add_argument("--refresh", action="store_true", help="backtest: re-download prices")
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
        elif cmd == "backtest":
            return backtest_cmd(a.capital, a.start, a.years, a.refresh)
        elif cmd in ("strategy", "strategies"):
            return strategy_cmd(desk, words)
        elif cmd == "autotrade":
            print(time.strftime("[%Y-%m-%d %H:%M] autotrade"))
            return autotrade_cmd(desk)
        elif cmd == "schedule":
            return schedule_cmd(words[0] if words else "16:15")
        elif cmd == "unschedule":
            return schedule_cmd(remove=True)
        elif cmd in ("connect", "link"):
            return connect(cfg)
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
