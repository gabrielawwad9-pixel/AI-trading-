"""Backtester and strategies: test trading rules on past prices before risking money.

How it avoids fooling you:
  * Signals use only data up to day t's close; the trade earns returns from day t+1 (no look-ahead).
  * Prices are adjusted for splits and dividends (total return).
  * Every trade pays a cost (default 0.10% of the amount traded) for spread/slippage.
  * Results always show the worst drawdown and worst week, not just the ending value.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TRADING_DAYS = 252

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def load_prices(symbols, start="2010-01-01", cache_dir: Path = None, refresh=False):
    """Daily split- and dividend-adjusted closes (DataFrame, one column per symbol). Cached as CSV for 12 hours."""
    import pandas as pd
    symbols = sorted(set(symbols))
    frames, missing = {}, []
    for s in symbols:
        f = cache_dir / f"{s}.csv" if cache_dir else None
        if f is not None and f.exists() and not refresh and \
                dt.datetime.now().timestamp() - f.stat().st_mtime < 12 * 3600:
            frames[s] = pd.read_csv(f, index_col=0, parse_dates=True).iloc[:, 0]
        else:
            missing.append(s)
    if missing:
        try:
            import yfinance as yf
            data = yf.download([m.replace(".", "-") for m in missing], start="1993-01-01", auto_adjust=True,
                               progress=False, threads=True)
            closes = data["Close"]
            if not hasattr(closes, "columns"):
                closes = closes.to_frame(missing[0])
            closes.columns = [str(c).replace("-", ".") for c in closes.columns]
        except Exception:
            closes = None
        for s in missing:
            ser = closes[s].dropna() if closes is not None and s in closes else None
            f = cache_dir / f"{s}.csv" if cache_dir else None
            if ser is None or ser.empty:
                if f is not None and f.exists():          # offline: fall back to the saved copy
                    frames[s] = pd.read_csv(f, index_col=0, parse_dates=True).iloc[:, 0]
                    continue
                from .errors import FriendlyError
                raise FriendlyError(f"Couldn't download price history for {s}.\n"
                                    "  Fix: check your internet connection and try again (prices come from Yahoo Finance).")
            frames[s] = ser
            if f is not None:
                cache_dir.mkdir(parents=True, exist_ok=True)
                ser.to_frame(s).to_csv(f)
    df = pd.DataFrame(frames).sort_index()
    return df[df.index >= pd.Timestamp(start) - pd.Timedelta(days=400)]   # extra year to warm up indicators


# ---------------------------------------------------------------------------
# Strategies: each returns a DataFrame of target weights (rows = days, cols = symbols, sum <= 1)
# Weights on day t are decided with data up to and including day t's close.
# ---------------------------------------------------------------------------
@dataclass
class Strategy:
    key: str
    name: str
    risk: str
    symbols: list
    description: str

    def weights(self, px):
        raise NotImplementedError


class BuyHold(Strategy):
    def __init__(self, symbol, risk):
        super().__init__(f"hold_{symbol.lower()}", f"Buy & hold {symbol}", risk, [symbol],
                         f"Put everything in {symbol} and never sell.")
        self.symbol = symbol

    def weights(self, px):
        w = px[self.symbols] * 0
        w[self.symbol] = 1.0
        return w.where(px[self.symbols].notna(), 0.0)


class TrendLeverage(Strategy):
    """Hold a 3x fund only while its underlying index is above its 200-day average; otherwise cash."""

    def __init__(self, lev="TQQQ", base="QQQ", sma=200, risk="Very high"):
        super().__init__(f"trend_{lev.lower()}", f"{lev} with {sma}-day trend filter", risk, [lev, base],
                         f"Hold {lev} (3x) when {base} is above its {sma}-day average, otherwise sit in cash. "
                         "Aims to skip the worst crashes; gets whipsawed in choppy markets.")
        self.lev, self.base, self.sma = lev, base, sma

    def weights(self, px):
        base = px[self.base]
        on = (base > base.rolling(self.sma).mean()).astype(float)
        w = px[self.symbols] * 0.0
        w[self.lev] = on.where(px[self.lev].notna(), 0.0)
        return w.fillna(0.0)


class MomentumRotation(Strategy):
    """Every week, go all-in on the leveraged fund with the strongest recent momentum (if it's trending up)."""

    def __init__(self, universe=("TQQQ", "SOXL", "UPRO", "TECL"), lookback=20, trend=50):
        super().__init__("momentum", "Leveraged momentum rotation", "Extreme", list(universe),
                         f"Each Friday, buy whichever of {', '.join(universe)} rose most over the last {lookback} "
                         f"trading days, if it's above its {trend}-day average; otherwise cash. "
                         "Chases the hottest 3x fund - huge swings both ways.")
        self.lookback, self.trend = lookback, trend

    def weights(self, px):
        import pandas as pd
        u = px[self.symbols]
        mom = u / u.shift(self.lookback) - 1
        ok = u > u.rolling(self.trend).mean()
        score = mom.where(ok)
        w = pd.DataFrame(0.0, index=u.index, columns=u.columns)
        fridays = u.index.to_series().dt.weekday == 4
        current = None
        for day in u.index:
            if fridays[day] or current is None:
                row = score.loc[day].dropna()
                current = row.idxmax() if not row.empty and row.max() > 0 else ""
            if current:
                w.at[day, current] = 1.0
        return w


def all_strategies():
    return [
        BuyHold("SPY", "Medium"),
        BuyHold("QQQ", "Medium-high"),
        TrendLeverage("TQQQ", "QQQ", 200, "Very high"),
        BuyHold("TQQQ", "Extreme"),
        BuyHold("SOXL", "Extreme"),
        TrendLeverage("SOXL", "SOXX", 200, "Extreme"),
        MomentumRotation(),
    ]


def get_strategy(key):
    for s in all_strategies():
        if s.key == key:
            return s
    raise KeyError(key)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
@dataclass
class Result:
    strategy: Strategy
    equity: object          # pandas Series, starting at `capital`
    start: object
    end: object
    trades: int
    capital: float

    @property
    def years(self):
        return max((self.end - self.start).days / 365.25, 1e-9)

    @property
    def final(self):
        return float(self.equity.iloc[-1])

    @property
    def cagr(self):
        return (self.final / self.capital) ** (1 / self.years) - 1

    @property
    def weekly(self):
        return self.equity.resample("W-FRI").last().pct_change().dropna()

    @property
    def avg_week(self):
        """Compound average weekly return."""
        return (self.final / self.capital) ** (1 / (self.years * 52)) - 1

    @property
    def max_drawdown(self):
        e = self.equity
        return float((e / e.cummax() - 1).min())

    @property
    def pct_weeks_5(self):
        w = self.weekly
        return float((w >= 0.05).mean()) if len(w) else 0.0

    @property
    def pct_weeks_down_5(self):
        w = self.weekly
        return float((w <= -0.05).mean()) if len(w) else 0.0

    @property
    def worst_week(self):
        w = self.weekly
        return float(w.min()) if len(w) else 0.0

    @property
    def best_week(self):
        w = self.weekly
        return float(w.max()) if len(w) else 0.0

    def year_returns(self):
        y = self.equity.resample("YE").last()
        first = self.equity.iloc[0]
        prev = [first] + list(y.values[:-1])
        return {d.year: v / p - 1 for d, v, p in zip(y.index, y.values, prev)}


def common_start(strategies, px, start):
    """First date when every strategy has data and a warmed-up 200-day average (so the comparison is fair)."""
    import pandas as pd
    cols = sorted({c for st in strategies for c in st.symbols})
    first = max(px[c].first_valid_index() for c in cols)
    idx = px.index[px.index >= first]
    warm = idx[min(200, len(idx) - 2)]
    return max(warm, pd.Timestamp(start))


def run(strategy: Strategy, px, capital=100.0, cost=0.001, start=None):
    """Simulate a strategy. cost = fraction of each traded dollar lost to spread/slippage."""
    sub = px[strategy.symbols]
    w = strategy.weights(px).reindex(sub.index).fillna(0.0)
    rets = sub.pct_change().fillna(0.0)
    held = w.shift(1).fillna(0.0)                 # decided at yesterday's close, earns today's return
    if start is not None:
        held, rets = held[held.index >= start], rets[rets.index >= start]
    prev = held.shift(1)
    prev.iloc[0] = 0.0                            # buying in on day one costs too
    turnover = (held - prev).abs().sum(axis=1)
    port = (held * rets).sum(axis=1) - turnover * cost
    equity = capital * (1 + port).cumprod()
    return Result(strategy, equity, equity.index[0], equity.index[-1], int((turnover > 1e-9).sum()), capital)


def run_all(strategies, px, capital=100.0, cost=0.001, start="2010-01-01"):
    s0 = common_start(strategies, px, start)
    return [run(st, px, capital, cost, s0) for st in strategies]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def pct(x, signed=True):
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def report(results, capital, goal_weekly=0.05):
    lines = []
    spy = next((r for r in results if r.strategy.key == "hold_spy"), None)
    span = f"{results[0].start:%b %Y} - {results[0].end:%b %Y}" if results else ""
    lines.append(f"BACKTEST  {span}   starting with ${capital:,.0f}   (costs included, dividends reinvested)")
    lines.append("")
    hdr = f"{'Strategy':38}{'Risk':12}{'Ends at':>12}{'Per year':>10}{'Avg week':>10}{'Worst drop':>12}{'Worst week':>12}{'Weeks +5%':>11}{'Weeks -5%':>11}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for r in sorted(results, key=lambda r: r.final, reverse=True):
        lines.append(f"{r.strategy.name[:37]:38}{r.strategy.risk:12}{'$' + format(r.final, ',.0f'):>12}"
                     f"{pct(r.cagr):>10}{pct(r.avg_week, True):>10}{pct(r.max_drawdown):>12}"
                     f"{pct(r.worst_week):>12}{pct(r.pct_weeks_5, False):>11}{pct(r.pct_weeks_down_5, False):>11}")
    lines.append("")
    years = results[0].years if results else 1
    need = capital * (1 + goal_weekly) ** (52 * years)
    need_txt = f"${need:,.0f}" if need < 1e12 else f"about ${need:.1e} - more money than exists on Earth"
    lines.append(f"Your goal of {goal_weekly * 100:.0f}% a week over the same {years:.1f} years would turn ${capital:,.0f} into "
                 f"{need_txt}.")
    best = max(results, key=lambda r: r.avg_week) if results else None
    if best:
        lines.append(f"The best strategy here averaged {pct(best.avg_week)} a week ({best.strategy.name}), "
                     f"with a worst drop of {pct(best.max_drawdown)}.")
    if spy:
        lines.append(f"Plain S&P 500 (SPY) averaged {pct(spy.cagr)} a year with a worst drop of {pct(spy.max_drawdown)}.")
    lines.append("")
    lines.append("Past results don't predict the future, and 3x funds can lose most of their value in a bad year.")
    return "\n".join(lines)


def year_table(results):
    years = sorted({y for r in results for y in r.year_returns()})
    hdr = f"{'Year':6}" + "".join(f"{r.strategy.key[:12]:>14}" for r in results)
    lines = [hdr, "-" * len(hdr)]
    for y in years:
        row = f"{y:<6}"
        for r in results:
            v = r.year_returns().get(y)
            row += f"{(pct(v) if v is not None else '-'):>14}"
        lines.append(row)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live signal + paper rebalancing
# ---------------------------------------------------------------------------
def todays_targets(strategy: Strategy, px):
    """Target weights the strategy wants to hold from the next trading session."""
    w = strategy.weights(px)
    last = w.iloc[-1]
    return {s: float(v) for s, v in last.items() if v > 1e-9}
