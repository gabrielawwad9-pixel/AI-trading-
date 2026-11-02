"""Trading tests with fake prices and a fake Robinhood - no network, no real orders."""

import sys
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_core.config import load_config  # noqa: E402
from jarvis_core.memory import LongTermMemory  # noqa: E402
from jarvis_core.skills import Skills, Timers  # noqa: E402
from jarvis_core.trading import (Quote, RobinhoodBroker, TradingDesk, explicit_tickers,  # noqa: E402
                                 market_status, names_in)

PRICES = {"AAPL": (200.0, 196.0), "TSLA": (250.0, 260.0), "NVDA": (100.0, 98.0), "GME": (20.0, 20.0),
          "AMD": (150.0, 140.0), "F": (12.0, 12.0)}


class FakeData:
    name = "Fake"

    def __init__(self):
        self.prices = dict(PRICES)

    def quote(self, symbol):
        if symbol not in self.prices:
            raise LookupError(symbol)
        p, prev = self.prices[symbol]
        return Quote(symbol, p, prev)

    def search(self, text):
        return {"advanced micro devices": "AMD"}.get(text)


def make_cfg(**kw):
    cfg = load_config()
    base = dict(trading_mode="paper", max_order_usd=5000, paper_starting_cash=10000, market_data="auto",
                robinhood_username="", robinhood_password="", robinhood_totp="", alert_check_seconds=60)
    base.update(kw)
    return replace(cfg, **base)


def make_desk(**kw):
    tmp = Path(tempfile.mkdtemp())
    cfg = make_cfg(**kw)
    notes = []
    desk = TradingDesk(cfg, notify=notes.append, data=FakeData(), state_dir=tmp)
    return desk, notes, tmp


class TestParsing(unittest.TestCase):
    def test_tickers_and_names(self):
        self.assertEqual(explicit_tickers("Should I buy AAPL or $tsla, I think?"), ["AAPL", "TSLA"])
        self.assertEqual(explicit_tickers("A.M.D. looks good"), ["AMD"])
        self.assertEqual(names_in("is apple better than the s&p 500 or tesla"), ["SPY", "AAPL", "TSLA"])

    def test_order_parsing(self):
        desk, _, _ = make_desk()
        cases = {
            "5 shares of apple": ("AAPL", 5, 0, 0, False),
            "five shares of tesla": ("TSLA", 5, 0, 0, False),
            "$100 of nvidia": ("NVDA", 0, 100, 0, False),
            "100 dollars of nvidia": ("NVDA", 0, 100, 0, False),
            "2 tesla at 240": ("TSLA", 2, 0, 240, False),
            "AAPL 3": ("AAPL", 3, 0, 0, False),
            "3 shares of AMD with a limit of 145.50": ("AMD", 3, 0, 145.5, False),
            "all my tesla": ("TSLA", 0, 0, 0, True),
            "10 ford": ("F", 10, 0, 0, False),
            "2 shares of advanced micro devices": ("AMD", 2, 0, 0, False),
        }
        for text, want in cases.items():
            side = "sell" if "all" in text else "buy"
            self.assertEqual(desk.parse_order(side, text.lower(), text), want, text)

    def test_market_hours(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        self.assertTrue(market_status(dt.datetime(2026, 11, 2, 10, 0, tzinfo=ny))[0])       # Monday
        self.assertFalse(market_status(dt.datetime(2026, 11, 2, 17, 0, tzinfo=ny))[0])
        self.assertIn("tomorrow", market_status(dt.datetime(2026, 11, 2, 17, 0, tzinfo=ny))[1])
        sat = market_status(dt.datetime(2026, 11, 7, 12, 0, tzinfo=ny))
        self.assertFalse(sat[0])
        self.assertIn("on Monday", sat[1])
        self.assertIn("holiday", market_status(dt.datetime(2026, 11, 26, 12, 0, tzinfo=ny))[1])  # Thanksgiving


class TestPaperTrading(unittest.TestCase):
    def setUp(self):
        self.desk, self.notes, self.tmp = make_desk()

    def say(self, text):
        from jarvis_core.skills import normalize
        return self.desk.handle(normalize(text), text)

    def test_quotes(self):
        self.assertEqual(self.say("What's Apple trading at?"), "Apple is at $200.00, up 2.04% today.")
        self.assertEqual(self.say("price of TSLA"), "Tesla is at $250.00, down 3.85% today.")
        self.assertEqual(self.say("how's nvidia doing today"), "Nvidia is at $100.00, up 2.04% today.")
        self.assertIsNone(self.say("how's the weather looking"))
        self.assertIsNone(self.say("how is it going"))
        self.assertIsNone(self.say("what's the capital of France"))

    def test_buy_confirm_and_portfolio(self):
        r = self.say("buy 5 shares of apple")
        self.assertIn("Paper trade: buy 5 shares of Apple at market price, about $1,000.00", r)
        self.assertIn("Shall I go ahead?", r)
        r = self.say("yes")
        self.assertIn("Bought 5 shares of Apple at $200.00", r)
        self.assertIn("$9,000.00", r)
        self.assertIn("worth $10,000.00, up $20.00 today", self.say("how's my portfolio doing"))
        self.assertIn("5 Apple worth $1,000.00", self.say("what stocks do I own"))
        self.assertIn("$9,000.00", self.say("what's my buying power"))
        self.assertTrue((self.tmp / "trade_log.jsonl").exists())

    def test_decline_and_unrelated_reply_cancel(self):
        self.say("buy 1 tesla")
        self.assertEqual(self.say("no"), "Order cancelled. Nothing was placed.")
        self.say("buy 1 tesla")
        self.assertIsNone(self.desk.confirm("what's the weather"))   # unrelated -> order dropped
        self.assertIsNone(self.desk.pending)
        self.assertIn("You don't own any", self.say("what do I own"))

    def test_safety_checks(self):
        self.assertIn("only have $10,000.00 of buying power", self.say("buy 100 shares of apple"))  # $20,000
        self.assertIn("only have 0 shares", self.say("sell 3 shares of tesla"))
        self.assertIn("don't own any", self.say("sell all my tesla"))
        self.assertIn("How many shares", self.say("buy apple"))
        self.assertIn("Which stock", self.say("buy 5 shares"))
        self.assertIsNone(self.desk.pending)

    def test_sell_all_and_dollar_orders(self):
        self.say("buy $1000 of nvidia")
        self.assertIn("Bought 10 shares of Nvidia", self.say("yes"))
        self.say("sell all my nvidia")
        self.assertIn("Sold 10 shares of Nvidia", self.say("go ahead"))
        self.assertIn("$10,000.00", self.say("buying power"))

    def test_limit_order_paper(self):
        self.say("buy 2 tesla at 240")
        self.assertIn("wouldn't fill", self.say("yes"))
        self.say("buy 2 tesla at 255")
        self.assertIn("Bought 2 shares of Tesla at $250.00", self.say("yes"))

    def test_watchlist_and_alerts(self):
        self.assertEqual(self.say("add AMD to my watchlist"), "Added AMD to your watchlist.")
        self.assertIn("AMD $150.00, up 7.14%", self.say("how's my watchlist"))
        self.assertEqual(self.say("remove AMD from my watchlist"), "Removed AMD from your watchlist.")
        r = self.say("alert me if Tesla goes above 300")
        self.assertIn("if Tesla goes above $300.00. It's at $250.00", r)
        self.assertIn("Tesla above $300.00", self.say("what alerts do I have"))
        self.desk.check_alerts()
        self.assertEqual(self.notes, [])
        self.desk.data.prices["TSLA"] = (305.0, 260.0)
        self.desk.check_alerts()
        self.assertIn("Tesla just went above $300.00", self.notes[0])
        self.assertIn("don't have any", self.say("list my alerts"))
        self.say("alert me when apple drops below 190")
        self.assertIn("Cancelled 1 alert", self.say("cancel my alerts"))

    def test_misc(self):
        self.assertIn("paper trading", self.say("am I paper trading?"))
        self.assertIn("stock market is", self.say("is the market open"))
        self.say("buy 1 apple")
        self.say("yes")
        self.assertIn("reset", self.say("reset my paper account"))
        self.assertIn("all in cash", self.say("how's my portfolio"))

    def test_ai_context(self):
        self.say("buy 1 apple")
        self.say("yes")
        ctx = self.desk.context_for("should I sell some apple and buy more nvidia?")
        self.assertIn("holds 1 AAPL", ctx)
        self.assertIn("quote NVDA", ctx)
        self.assertEqual(self.desk.context_for("tell me a joke about cats"), "")


class TestThroughSkills(unittest.TestCase):
    def test_skills_route_trading_and_confirmation_first(self):
        desk, _, tmp = make_desk()
        skills = Skills(LongTermMemory(tmp / "m.json"), Timers(), launcher=lambda u: True, trading=desk)
        self.assertIn("Apple is at", skills.handle("Jarvis, what's apple trading at?"))
        self.assertIn("Paper trade", skills.handle("Buy two shares of Apple."))
        self.assertIn("Bought 2 shares", skills.handle("Yes, please."))
        self.assertTrue(skills.handle("What time is it?").startswith("It's"))
        self.assertIsNone(skills.handle("What's the capital of France?"))


class FakeRH:
    """Stands in for robin_stocks.robinhood and records orders instead of sending them."""

    def __init__(self):
        self.calls = []
        outer = self
        self.stocks = types.SimpleNamespace(
            get_quotes=lambda syms: [{"symbol": s, "last_trade_price": str(PRICES[s][0]),
                                      "adjusted_previous_close": str(PRICES[s][1])}
                                     for s in ([syms] if isinstance(syms, str) else syms)],
            find_instrument_data=lambda q: [])
        self.profiles = types.SimpleNamespace(
            load_portfolio_profile=lambda: {"equity": "2500.00", "extended_hours_equity": None,
                                            "equity_previous_close": "2450.00"},
            load_account_profile=lambda info=None: "1500.00")
        self.build_holdings = lambda: {"TSLA": {"price": "250.0", "quantity": "4.0", "average_buy_price": "200.0"}}

        def rec(name):
            def f(*args, **kw):
                outer.calls.append((name, args))
                return {"id": "abc123", "state": "queued"}
            return f
        self.orders = types.SimpleNamespace(**{n: rec(n) for n in [
            "order_buy_market", "order_sell_market", "order_buy_limit", "order_sell_limit",
            "order_buy_fractional_by_price", "order_sell_fractional_by_price",
            "order_buy_fractional_by_quantity", "order_sell_fractional_by_quantity"]},
            get_all_open_stock_orders=lambda: [], cancel_all_stock_orders=lambda: None)


class TestLiveMode(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cfg = make_cfg(trading_mode="live", max_order_usd=500, robinhood_username="me", robinhood_password="pw")
        self.fake = FakeRH()
        broker = RobinhoodBroker("me", "pw")
        broker._rh = self.fake        # pretend we're logged in
        self.desk = TradingDesk(cfg, notify=lambda m: None, data=FakeData(), broker=broker, state_dir=self.tmp)

    def say(self, text):
        from jarvis_core.skills import normalize
        return self.desk.handle(normalize(text), text)

    def test_live_needs_explicit_confirm(self):
        r = self.say("buy 2 shares of apple")
        self.assertIn("Live order with real money", r)
        self.assertIn("confirm order", r)
        r = self.say("yes")                                   # "yes" is NOT enough for real money
        self.assertIn("say the words 'confirm order'", r)
        self.assertEqual(self.fake.calls, [])
        self.say("buy 2 shares of apple")
        self.assertIn("Order sent to Robinhood", self.say("confirm order"))
        self.assertEqual(self.fake.calls, [("order_buy_market", ("AAPL", 2))])

    def test_live_limits_and_holdings(self):
        self.assertIn("safety limit of $500.00", self.say("buy 3 shares of apple"))
        self.assertIn("only have 4 shares", self.say("sell 5 tesla"))
        self.assertIn("safety limit", self.say("sell all my tesla"))   # 4 x $250 = $1,000 > $500
        self.say("sell 2 tesla")                                          # $500 is allowed
        self.say("confirm")
        self.assertEqual(self.fake.calls[-1], ("order_sell_market", ("TSLA", 2)))
        self.say("buy $50 of nvidia")
        self.say("confirm order")
        self.assertEqual(self.fake.calls[-1], ("order_buy_fractional_by_price", ("NVDA", 50.0)))
        self.say("buy 1 tesla at 240")
        self.say("confirm order")
        self.assertEqual(self.fake.calls[-1], ("order_buy_limit", ("TSLA", 1, 240.0)))

    def test_live_portfolio(self):
        r = self.say("how's my portfolio")
        self.assertIn("Your Robinhood account is worth $2,500.00, up $50.00 today", r)
        self.assertIn("Tesla down 3.85%", r)
        self.assertIn("$1,500.00 of buying power", self.say("buying power"))


if __name__ == "__main__":
    unittest.main()
