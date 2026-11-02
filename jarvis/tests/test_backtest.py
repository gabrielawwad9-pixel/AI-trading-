"""Backtester tests on synthetic prices where the right answer is known."""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_core import backtest as bt  # noqa: E402


def days(n, start="2015-01-01"):
    return pd.bdate_range(start, periods=n)


class TestEngine(unittest.TestCase):
    def test_buy_and_hold_math(self):
        idx = days(300)
        px = pd.DataFrame({"SPY": np.linspace(100, 200, 300)}, index=idx)
        r = bt.run(bt.BuyHold("SPY", "Medium"), px, capital=100, cost=0.001, start=idx[0])
        # held from day 2 (decided at day 1's close); pays 0.1% to buy in
        expected = 100 * (1 - 0.001) * (200 / px["SPY"].iloc[0])
        self.assertAlmostEqual(r.final, expected, delta=0.6)
        self.assertEqual(r.trades, 1)

    def test_no_lookahead(self):
        # Flat price that jumps 50% on one day. A rule that switches on THAT day must not earn the jump.
        idx = days(300)
        p = np.full(300, 100.0)
        p[250:] = 150.0
        px = pd.DataFrame({"X": p}, index=idx)

        class Cheater(bt.Strategy):
            def __init__(self):
                super().__init__("cheat", "cheat", "-", ["X"], "")

            def weights(self, px):
                return (px[["X"]].pct_change() > 0.2).astype(float)   # "on" only on the jump day itself

        r = bt.run(Cheater(), px, capital=100, cost=0.0, start=idx[1])
        self.assertAlmostEqual(r.final, 100.0, places=6)

    def test_trend_filter_goes_to_cash(self):
        idx = days(600)
        up = np.linspace(100, 200, 300)
        down = np.linspace(200, 80, 300)
        base = np.concatenate([up, down])
        lev = base ** 3 / 10000.0
        px = pd.DataFrame({"QQQ": base, "TQQQ": lev}, index=idx)
        st = bt.TrendLeverage("TQQQ", "QQQ", 50)
        w = st.weights(px)
        self.assertEqual(w["TQQQ"].iloc[250], 1.0)       # uptrend -> invested
        self.assertEqual(w["TQQQ"].iloc[-1], 0.0)        # downtrend -> cash
        r = bt.run(st, px, capital=100, cost=0.0, start=idx[60])
        hold = bt.run(bt.BuyHold("TQQQ", "x"), px, capital=100, cost=0.0, start=idx[60])
        self.assertGreater(r.final, hold.final)          # filter avoided most of the crash
        self.assertGreater(r.max_drawdown, hold.max_drawdown)

    def test_momentum_picks_strongest(self):
        idx = days(400)
        t = np.arange(400)
        px = pd.DataFrame({"A": 100 + t * 0.1, "B": 100 * 1.003 ** t, "C": 100 - t * 0.05}, index=idx)
        st = bt.MomentumRotation(universe=("A", "B", "C"), lookback=20, trend=50)
        w = st.weights(px)
        self.assertEqual(w.iloc[-1].idxmax(), "B")
        self.assertAlmostEqual(w.iloc[-1].sum(), 1.0)
        self.assertEqual(w["C"].sum(), 0.0)              # falling fund never held

    def test_report_and_metrics(self):
        idx = days(800)
        px = pd.DataFrame({"SPY": 100 * 1.0004 ** np.arange(800)}, index=idx)
        res = [bt.run(bt.BuyHold("SPY", "Medium"), px, capital=100, cost=0.0, start=idx[0])]
        text = bt.report(res, 100)
        self.assertIn("5% a week", text)
        self.assertIn("Buy & hold SPY", text)
        self.assertAlmostEqual(res[0].max_drawdown, 0.0, places=6)
        self.assertAlmostEqual(res[0].cagr, 1.0004 ** 252 - 1, delta=0.01)
        self.assertEqual(res[0].pct_weeks_5, 0.0)


class TestAutotradePaper(unittest.TestCase):
    def test_rebalance_paper_account(self):
        import tempfile
        from dataclasses import replace

        import trade
        from jarvis_core.config import load_config
        from jarvis_core.trading import Quote, TradingDesk

        idx = days(300)
        px = pd.DataFrame({"QQQ": np.linspace(100, 200, 300), "TQQQ": np.linspace(10, 80, 300)}, index=idx)

        class Data:
            name = "fake"

            def quote(self, s):
                return Quote(s, float(px[s].iloc[-1]), float(px[s].iloc[-2]))

            def search(self, t):
                return None

        cfg = replace(load_config(), trading_mode="paper", paper_starting_cash=100.0,
                      robinhood_username="", robinhood_password="")
        tmp = Path(tempfile.mkdtemp())
        desk = TradingDesk(cfg, notify=lambda m: None, data=Data(), state_dir=tmp)
        desk.state["strategy"] = "trend_tqqq"
        orig = bt.load_prices
        bt.load_prices = lambda *a, **k: px
        try:
            self.assertEqual(trade.autotrade_cmd(desk), 0)
            pos = desk.broker.state["positions"]
            self.assertIn("TQQQ", pos)
            self.assertGreater(pos["TQQQ"]["qty"] * 80, 98)          # ~all-in
            self.assertEqual(trade.autotrade_cmd(desk), 0)             # second run: already on target
            # trend breaks -> sell everything
            px.loc[:, "QQQ"] = np.linspace(200, 100, 300)
            trade.autotrade_cmd(desk)
            self.assertNotIn("TQQQ", desk.broker.state["positions"])
        finally:
            bt.load_prices = orig


if __name__ == "__main__":
    unittest.main()
