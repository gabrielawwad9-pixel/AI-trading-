"""Trading desk for JARVIS: prices, your Robinhood portfolio, paper trading, watchlist and price alerts.

SAFETY RULES (built in, not optional):
  * TRADING_MODE=paper (the default) uses a practice account with fake money and real prices.
  * Real Robinhood orders need TRADING_MODE=live in .env AND an explicit confirmation
    ("confirm order" by voice, typing "yes" in the terminal).
  * Live orders bigger than MAX_ORDER_USD are refused (paper orders are limited by your practice cash).
  * Only YOUR explicit commands create orders. The AI can't place trades.
"""

import datetime as dt
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import FriendlyError

# ---------------------------------------------------------------------------
# Company names -> tickers (so you can say "Apple" instead of "A A P L")
# ---------------------------------------------------------------------------
NAMES = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL", "amazon": "AMZN",
    "tesla": "TSLA", "nvidia": "NVDA", "meta": "META", "facebook": "META", "netflix": "NFLX",
    "amd": "AMD", "intel": "INTC", "disney": "DIS", "coca cola": "KO", "coca-cola": "KO", "coke": "KO",
    "pepsi": "PEP", "pepsico": "PEP", "walmart": "WMT", "costco": "COST", "nike": "NKE",
    "starbucks": "SBUX", "mcdonald's": "MCD", "mcdonalds": "MCD", "boeing": "BA", "ford": "F",
    "general motors": "GM", "jpmorgan": "JPM", "jp morgan": "JPM", "bank of america": "BAC",
    "visa": "V", "mastercard": "MA", "paypal": "PYPL", "uber": "UBER", "airbnb": "ABNB",
    "spotify": "SPOT", "palantir": "PLTR", "robinhood": "HOOD", "coinbase": "COIN",
    "gamestop": "GME", "berkshire": "BRK.B", "berkshire hathaway": "BRK.B", "exxon": "XOM",
    "chevron": "CVX", "pfizer": "PFE", "johnson and johnson": "JNJ", "johnson & johnson": "JNJ",
    "oracle": "ORCL", "salesforce": "CRM", "adobe": "ADBE", "ibm": "IBM", "broadcom": "AVGO",
    "qualcomm": "QCOM", "micron": "MU", "sofi": "SOFI", "rivian": "RIVN", "lucid": "LCID",
    "snowflake": "SNOW", "shopify": "SHOP", "home depot": "HD", "verizon": "VZ", "at&t": "T",
    "at and t": "T", "t-mobile": "TMUS", "taiwan semiconductor": "TSM", "tsmc": "TSM",
    "super micro": "SMCI", "supermicro": "SMCI", "arm": "ARM", "dell": "DELL", "hp": "HPQ",
    "s&p 500": "SPY", "s and p 500": "SPY", "s&p": "SPY", "the s&p": "SPY", "the s and p": "SPY",
    "nasdaq": "QQQ", "the nasdaq": "QQQ", "dow jones": "DIA", "the dow": "DIA",
    "total market": "VTI", "vanguard s&p 500": "VOO",
}
FRIENDLY = {}
for _name, _sym in NAMES.items():
    FRIENDLY.setdefault(_sym, _name.title())
FRIENDLY.update({"SPY": "the S&P 500 ETF", "QQQ": "the Nasdaq 100 ETF", "DIA": "the Dow ETF",
                 "AMD": "AMD", "IBM": "IBM", "HP": "HP", "JPM": "JPMorgan", "KO": "Coca-Cola",
                 "MCD": "McDonald's", "GOOGL": "Google", "META": "Meta", "BRK.B": "Berkshire Hathaway",
                 "TSM": "TSMC", "T": "AT&T", "TMUS": "T-Mobile", "SMCI": "Super Micro", "HPQ": "HP"})

# Short all-caps words that are NOT tickers when they appear in a sentence
_NOT_TICKERS = {"I", "A", "OK", "AM", "PM", "US", "USA", "UK", "TV", "AI", "CEO", "CFO", "ETF", "IPO",
                "EPS", "GDP", "CPI", "FED", "PE", "YES", "NO", "JARVIS", "USD", "IRA", "ID", "FAQ"}


def friendly(symbol: str) -> str:
    return FRIENDLY.get(symbol, symbol)


def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def pct_phrase(p: float) -> str:
    if abs(p) < 0.005:
        return "flat"
    return f"{'up' if p > 0 else 'down'} {abs(p):.2f}%"


# ---------------------------------------------------------------------------
# Market hours (NYSE / Nasdaq regular session)
# ---------------------------------------------------------------------------
_HOLIDAYS = {  # full-day closures
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
}


def _eastern_now(now=None):
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    except Exception:  # tzdata missing - approximate with a fixed offset
        tz = dt.timezone(dt.timedelta(hours=-5))
    if now is None:
        return dt.datetime.now(tz)
    return now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)


def market_status(now=None):
    """Returns (is_open: bool, spoken description)."""
    et = _eastern_now(now)
    open_t = et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = et.replace(hour=16, minute=0, second=0, microsecond=0)
    trading_day = et.weekday() < 5 and et.strftime("%Y-%m-%d") not in _HOLIDAYS
    if trading_day and open_t <= et < close_t:
        mins = int((close_t - et).total_seconds() // 60)
        return True, f"The stock market is open. It closes in {mins // 60} hours and {mins % 60} minutes, at 4 PM Eastern."
    # find next open
    nxt = et
    if trading_day and et < open_t:
        when = "today"
    else:
        nxt = et + dt.timedelta(days=1)
        while nxt.weekday() >= 5 or nxt.strftime("%Y-%m-%d") in _HOLIDAYS:
            nxt += dt.timedelta(days=1)
        when = "tomorrow" if (nxt.date() - et.date()).days == 1 else nxt.strftime("on %A")
    why = "" if trading_day or et.weekday() >= 5 else " for a holiday"
    return False, f"The stock market is closed{why}. It opens {when} at 9:30 AM Eastern."


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------
@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float

    @property
    def change_pct(self) -> float:
        return (self.price - self.prev_close) / self.prev_close * 100 if self.prev_close else 0.0


class YahooData:
    """Free delayed prices from Yahoo Finance (no account needed)."""
    name = "Yahoo Finance"

    def quote(self, symbol: str) -> Quote:
        import yfinance as yf
        fi = yf.Ticker(symbol.replace(".", "-")).fast_info
        try:
            price = float(fi["last_price"])
            prev = float(fi["previous_close"] or 0)
        except (KeyError, TypeError, ValueError):
            raise LookupError(f"No price found for {symbol}") from None
        if price != price or price <= 0:  # NaN
            raise LookupError(f"No price found for {symbol}")
        return Quote(symbol, price, prev)

    def search(self, text: str):
        import yfinance as yf
        for q in yf.Search(text, max_results=5).quotes:
            if q.get("quoteType") in ("EQUITY", "ETF") and q.get("symbol"):
                return q["symbol"].replace("-", ".")
        return None


class RobinhoodData:
    """Real-time prices from your Robinhood login."""
    name = "Robinhood"

    def __init__(self, broker):
        self.broker = broker

    def quote(self, symbol: str) -> Quote:
        rh = self.broker.rh()
        qs = rh.stocks.get_quotes(symbol)
        q = qs[0] if qs else None
        if not q:
            raise LookupError(f"No price found for {symbol}")
        price = float(q.get("last_extended_hours_trade_price") or q["last_trade_price"])
        prev = float(q.get("adjusted_previous_close") or q.get("previous_close") or 0)
        return Quote(symbol, price, prev)

    def search(self, text: str):
        rh = self.broker.rh()
        try:
            res = rh.stocks.find_instrument_data(text)
        except Exception:
            return None
        for r in res or []:
            if r and r.get("tradeable") and r.get("symbol"):
                return r["symbol"]
        return None


# ---------------------------------------------------------------------------
# Orders and positions
# ---------------------------------------------------------------------------
@dataclass
class Order:
    side: str                      # "buy" or "sell"
    symbol: str
    quantity: float = 0.0          # shares (0 if ordering by dollars)
    dollars: float = 0.0           # dollar amount (0 if ordering by shares)
    limit_price: float = 0.0       # 0 = market order
    est_price: float = 0.0
    created: float = field(default_factory=time.time)

    @property
    def est_shares(self) -> float:
        if self.quantity:
            return self.quantity
        p = self.limit_price or self.est_price
        return self.dollars / p if p else 0.0

    @property
    def est_value(self) -> float:
        return self.dollars or self.quantity * (self.limit_price or self.est_price)

    def describe(self) -> str:
        what = (f"{_fmt_qty(self.quantity)} share{'s' if self.quantity != 1 else ''} of {friendly(self.symbol)}"
                if self.quantity else f"{money(self.dollars)} of {friendly(self.symbol)}")
        how = f"with a limit of {money(self.limit_price)}" if self.limit_price else "at market price"
        return f"{self.side} {what} {how}"


def _fmt_qty(q: float) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:.4f}".rstrip("0").rstrip(".")


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_price: float
    price: float = 0.0
    prev_close: float = 0.0

    @property
    def value(self):
        return self.quantity * self.price

    @property
    def total_gain(self):
        return (self.price - self.avg_price) * self.quantity

    @property
    def total_gain_pct(self):
        return (self.price - self.avg_price) / self.avg_price * 100 if self.avg_price else 0.0

    @property
    def day_change(self):
        return (self.price - self.prev_close) * self.quantity if self.prev_close else 0.0


@dataclass
class AccountSnapshot:
    cash: float
    positions: list
    equity: float = 0.0
    prev_equity: float = 0.0

    @property
    def total(self):
        return self.equity or (self.cash + sum(p.value for p in self.positions))

    @property
    def day_change(self):
        if self.prev_equity:
            return self.total - self.prev_equity
        return sum(p.day_change for p in self.positions)


class PaperBroker:
    """A practice account: real prices, fake money. Saved in paper_account.json."""
    live = False

    def __init__(self, path: Path, starting_cash: float, data):
        self.path = Path(path)
        self.starting_cash = starting_cash
        self.data = data
        self.state = self._load()

    def _load(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {"cash": self.starting_cash, "starting_cash": self.starting_cash, "positions": {},
                "created": dt.date.today().isoformat()}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def reset(self):
        self.state = {"cash": self.starting_cash, "starting_cash": self.starting_cash, "positions": {},
                      "created": dt.date.today().isoformat()}
        self._save()

    def snapshot(self) -> AccountSnapshot:
        positions = []
        for sym, p in self.state["positions"].items():
            try:
                q = self.data.quote(sym)
                price, prev = q.price, q.prev_close
            except Exception:
                price, prev = p["avg_price"], 0.0
            positions.append(Position(sym, p["qty"], p["avg_price"], price, prev))
        return AccountSnapshot(cash=self.state["cash"], positions=positions)

    def buying_power(self) -> float:
        return self.state["cash"]

    def held(self, symbol) -> float:
        return self.state["positions"].get(symbol, {}).get("qty", 0.0)

    def place(self, order: Order) -> str:
        price = self.data.quote(order.symbol).price
        if order.limit_price:
            if (order.side == "buy" and price > order.limit_price) or (order.side == "sell" and price < order.limit_price):
                return (f"Not filled: {friendly(order.symbol)} is at {money(price)}, so your limit of "
                        f"{money(order.limit_price)} wouldn't fill right now. Paper mode only fills limit orders that "
                        f"would execute immediately.")
            # marketable limit orders fill at the current (better or equal) market price
        shares = order.quantity or round(order.dollars / price, 6)
        cost = shares * price
        pos = self.state["positions"].get(order.symbol, {"qty": 0.0, "avg_price": 0.0})
        if order.side == "buy":
            if cost > self.state["cash"] + 1e-6:
                return f"Not filled: that costs {money(cost)} but your paper account only has {money(self.state['cash'])}."
            new_qty = pos["qty"] + shares
            pos["avg_price"] = (pos["qty"] * pos["avg_price"] + cost) / new_qty
            pos["qty"] = new_qty
            self.state["cash"] -= cost
            self.state["positions"][order.symbol] = pos
        else:
            if shares > pos["qty"] + 1e-9:
                return f"Not filled: you only have {_fmt_qty(pos['qty'])} shares of {friendly(order.symbol)}."
            pos["qty"] -= shares
            self.state["cash"] += cost
            if pos["qty"] <= 1e-9:
                self.state["positions"].pop(order.symbol, None)
            else:
                self.state["positions"][order.symbol] = pos
        self._save()
        verb = "Bought" if order.side == "buy" else "Sold"
        return (f"Done. {verb} {_fmt_qty(round(shares, 6))} share{'s' if shares != 1 else ''} of "
                f"{friendly(order.symbol)} at {money(price)}, for {money(cost)}. "
                f"Paper cash is now {money(self.state['cash'])}.")

    def cancel_all(self) -> str:
        return "Paper trades fill instantly, so there are no open orders to cancel."


class RobinhoodBroker:
    """Your real Robinhood account (via the robin_stocks library)."""
    live = True

    def __init__(self, username, password, totp_secret=""):
        self.username = username
        self.password = password
        self.totp_secret = totp_secret
        self._rh = None
        self._lock = threading.Lock()

    @property
    def configured(self):
        return bool(self.username and self.password)

    def rh(self):
        """Log in once (Robinhood remembers the session for about a day) and return the API module."""
        with self._lock:
            if self._rh is not None:
                return self._rh
            if not self.configured:
                raise FriendlyError(
                    "Robinhood isn't connected yet.\n"
                    "  Fix: add ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD to .env, then run:  jarvis login")
            import robin_stocks.robinhood as rh
            mfa = None
            if self.totp_secret:
                import pyotp
                mfa = pyotp.TOTP(self.totp_secret.replace(" ", "")).now()
            try:
                result = rh.login(username=self.username, password=self.password, mfa_code=mfa,
                                  store_session=True, expiresIn=86400 * 7)
            except Exception as e:
                raise FriendlyError(
                    "Robinhood login failed.\n"
                    "  Check ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD in .env. If you use an authenticator app,\n"
                    "  ROBINHOOD_TOTP_SECRET must be the setup SECRET (letters/numbers), not a 6-digit code.\n"
                    "  If Robinhood sent a code or a 'confirm it's you' prompt to your phone, run  jarvis login\n"
                    f"  in the terminal and approve it there.\n  (Detail: {e})") from None
            if not result or "access_token" not in result:
                raise FriendlyError(
                    "Robinhood didn't accept the login. Run  jarvis login  in the terminal to see what it needs\n"
                    "  (it may be waiting for you to approve the login in the Robinhood app).")
            self._rh = rh
            return rh

    def snapshot(self) -> AccountSnapshot:
        rh = self.rh()
        profile = rh.profiles.load_portfolio_profile() or {}
        equity = float(profile.get("extended_hours_equity") or profile.get("equity") or 0)
        prev = float(profile.get("equity_previous_close") or 0)
        cash = self.buying_power()
        holdings = rh.build_holdings() or {}
        symbols = list(holdings)
        prevs = {}
        if symbols:
            for q in rh.stocks.get_quotes(symbols) or []:
                if q:
                    prevs[q["symbol"]] = float(q.get("adjusted_previous_close") or q.get("previous_close") or 0)
        positions = [Position(sym, float(h["quantity"]), float(h["average_buy_price"]), float(h["price"]),
                              prevs.get(sym, 0.0)) for sym, h in holdings.items()]
        return AccountSnapshot(cash=cash, positions=positions, equity=equity, prev_equity=prev)

    def buying_power(self) -> float:
        return float(self.rh().profiles.load_account_profile(info="buying_power") or 0)

    def held(self, symbol) -> float:
        for p in self.snapshot().positions:
            if p.symbol == symbol:
                return p.quantity
        return 0.0

    def place(self, order: Order) -> str:
        rh = self.rh()
        o = rh.orders
        s, q = order.symbol, order.quantity
        if order.limit_price:
            fn = o.order_buy_limit if order.side == "buy" else o.order_sell_limit
            result = fn(s, q, round(order.limit_price, 2))
        elif order.dollars:
            fn = o.order_buy_fractional_by_price if order.side == "buy" else o.order_sell_fractional_by_price
            result = fn(s, round(order.dollars, 2))
        elif float(q).is_integer():
            fn = o.order_buy_market if order.side == "buy" else o.order_sell_market
            result = fn(s, int(q))
        else:
            fn = o.order_buy_fractional_by_quantity if order.side == "buy" else o.order_sell_fractional_by_quantity
            result = fn(s, q)
        if isinstance(result, dict) and result.get("id"):
            state = result.get("state", "submitted")
            return f"Order sent to Robinhood: {order.describe()}. Status: {state}."
        detail = ""
        if isinstance(result, dict):
            detail = result.get("detail") or result.get("non_field_errors") or json.dumps(result)[:200]
        return f"Robinhood rejected the order. {detail or 'No reason given.'}"

    def cancel_all(self) -> str:
        rh = self.rh()
        open_orders = rh.orders.get_all_open_stock_orders() or []
        if not open_orders:
            return "You don't have any open orders."
        rh.orders.cancel_all_stock_orders()
        return f"Cancelled {len(open_orders)} open order{'s' if len(open_orders) != 1 else ''}."


# ---------------------------------------------------------------------------
# Parsing what you said
# ---------------------------------------------------------------------------
def _num(word: str):
    from .skills import _word_to_number
    w = word.replace(",", "").replace("$", "").strip()
    n = _word_to_number(w)
    return n if n else None


_NUMWORD = (r"(?:\d[\d,]*(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"fifteen|twenty|twenty-five|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|a hundred|"
            r"one hundred|two hundred|five hundred|a thousand|one thousand)")


def _number_phrase(s: str):
    s = s.strip().lower()
    mult = {"hundred": 100, "a hundred": 100, "one hundred": 100, "two hundred": 200, "five hundred": 500,
            "a thousand": 1000, "one thousand": 1000}
    if s in mult:
        return float(mult[s])
    return _num(s)


def explicit_tickers(original_text: str):
    """Tickers written in capitals or as cashtags: 'AAPL', '$TSLA', 'A.A.P.L.'."""
    found = []
    for m in re.finditer(r"\$([A-Za-z]{1,5})\b|\b((?:[A-Z]\.){2,5})|\b([A-Z]{1,5}(?:\.[A-Z])?)\b", original_text):
        if m.group(1):
            sym = m.group(1).upper()
        elif m.group(2):
            sym = m.group(2).replace(".", "")
        else:
            sym = m.group(3)
        if sym and sym not in _NOT_TICKERS and sym not in found:
            found.append(sym)
    return found


def names_in(text: str):
    """Company names mentioned anywhere in a sentence -> tickers."""
    t = " " + re.sub(r"[^a-z0-9&'.\- ]", " ", text.lower()) + " "
    found = []
    for name in sorted(NAMES, key=len, reverse=True):
        if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", t):
            sym = NAMES[name]
            if sym not in found:
                found.append(sym)
            t = t.replace(name, " ")
    return found


# ---------------------------------------------------------------------------
# The desk: everything JARVIS can say/do about trading
# ---------------------------------------------------------------------------
_PORTFOLIO_RE = re.compile(
    r"\b(?:how(?:'s| is| are)|what(?:'s| is)|check|show|give me|update on|summary of|tell me about)\b.*\b(?:my )?(?:portfolio|account|investments)\b|"
    r"^(?:my )?portfolio(?: summary| update| value)?$|^how am i doing\b|\bhow much (?:money )?(?:am i|have i|did i) (?:up|down|made|lost|make|lose)\b|"
    r"\bhow much is my (?:portfolio|account) worth\b")
_POSITIONS_RE = re.compile(
    r"\b(?:what|which|show|list|tell me)\b.*\b(?:positions|holdings|stocks do i (?:own|have|hold)|do i own|shares do i)\b|"
    r"^(?:my )?(?:positions|holdings)$|\bhow are my (?:stocks|positions|holdings) doing\b")
_BP_RE = re.compile(r"\bbuying power\b|\bhow much (?:cash|money) (?:do i have|have i got|is available)\b|\bcash balance\b")
_MARKET_RE = re.compile(r"\bis the (?:stock )?market (?:open|closed)\b|\bmarket (?:status|hours)\b|"
                        r"\bwhen does the (?:stock )?market (?:open|close)\b|\bis wall street open\b|\bare markets? open\b")
_QUOTE_STRICT = [
    re.compile(r"^(?:what(?:'s| is)|check|get(?: me)?|give me|tell me|show me)?\s*(?:the\s+)?(?:current\s+|latest\s+)?(?:stock\s+|share\s+)?(?:price|quote)\s+(?:of|for|on)\s+(.+?)(?:\s+stock)?(?: right now| now| today)?$"),
    re.compile(r"^(?:quote|price)\s+(.+)$"),
    re.compile(r"^(?:what(?:'s| is)|where(?:'s| is))\s+(.+?)\s+(?:stock|shares)\s*(?:price|trading at|at|trading)?(?: right now| now| today)?$"),
    re.compile(r"^(.+?)\s+(?:stock price|share price|price)$"),
]
_QUOTE_LOOSE = [
    re.compile(r"^(?:what(?:'s| is)|where(?:'s| is))\s+(.+?)\s+(?:trading at|at|trading)(?: right now| now| today)?$"),
    re.compile(r"^how(?:'s| is)\s+(.+?)\s+(?:doing|trading|looking)(?: today| right now| now)?$"),
    re.compile(r"^(?:what(?:'s| is))\s+(.+?)\s+(?:up|down)\s+today$"),
]
_ORDER_RE = re.compile(r"^(?:(?:place|put in|make) an? (?:order|trade) to\s+|go ahead and\s+|let's\s+)?(buy|purchase|sell)\s+(.+)$")
_CANCEL_ORDERS_RE = re.compile(r"^cancel (?:all )?(?:of )?(?:my )?(?:open |pending )?(?:stock )?orders$")
_WATCH_ADD_RE = re.compile(r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:my |the )?watch ?list$|^watch\s+(.+)$")
_WATCH_DEL_RE = re.compile(r"^(?:remove|take|delete|drop)\s+(.+?)\s+(?:from|off)\s+(?:my |the )?watch ?list$")
_WATCH_SHOW_RE = re.compile(r"\bwatch ?list\b")
_ALERT_RE = re.compile(
    r"^(?:alert|tell|notify|warn|ping|let) me(?: know)? (?:if|when) (.+?) (?:goes |gets |trades |is |hits |rises |falls |drops |climbs |moves |breaks )?"
    r"(above|over|below|under|past|beneath|to|hits?)\s+(.+?)(?: dollars| bucks)?$|"
    r"^set (?:a |an )?(?:price )?alert (?:for|on) (.+?) (?:at|if it goes|when it goes|when it's|if it's)?\s*(above|over|below|under)\s+(.+?)(?: dollars)?$")
_ALERT_LIST_RE = re.compile(r"\b(?:what|which|show|list|my)\b.*\balerts\b|^alerts$")
_ALERT_CANCEL_RE = re.compile(r"^(?:cancel|clear|delete|remove|stop) (?:all )?(?:my |the )?(?:price )?alerts?(?: for (.+))?$")
_MODE_RE = re.compile(r"\b(?:am i|are we) (?:paper|live|real)(?: money)? trading\b|\btrading mode\b|\bwhich mode\b|\bis this real money\b")
_RESET_PAPER_RE = re.compile(r"^reset (?:my |the )?paper (?:account|portfolio|trading)$")
_TRADING_WORDS = re.compile(r"\b(?:stocks?|shares?|portfolio|positions?|holdings?|invest\w*|market|trade|trading|"
                            r"ticker|earnings|buy|sell|bull\w*|bear\w*|dividends?|etf|options?|gain|loss|profit)\b")
_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|confirm(?:ed)?|do it|go ahead|place it|proceed|affirmative|ok|okay)\b")
_NO = re.compile(r"^(?:no|nope|nah|cancel|stop|don't|never mind|wait|hold on|abort)\b")


class TradingDesk:
    def __init__(self, cfg, notify=None, data=None, broker=None, state_dir: Path = None):
        self.cfg = cfg
        self.mode = cfg.trading_mode
        self.max_order = cfg.max_order_usd
        state_dir = Path(state_dir or cfg.personality_file.parent)
        self.state_path = state_dir / "trading_state.json"
        self.log_path = state_dir / "trade_log.jsonl"
        self.notify = notify or (lambda msg: print(f"\n[ALERT] {msg}"))
        self.robinhood = RobinhoodBroker(cfg.robinhood_username, cfg.robinhood_password, cfg.robinhood_totp)
        if data is None:
            use_rh = cfg.market_data == "robinhood" or (cfg.market_data == "auto" and self.robinhood.configured)
            data = RobinhoodData(self.robinhood) if use_rh else YahooData()
        self.data = data
        if broker is None:
            if self.mode == "live":
                broker = self.robinhood
            else:
                broker = PaperBroker(state_dir / "paper_account.json", cfg.paper_starting_cash, data)
        self.broker = broker
        self.pending = None           # Order waiting for confirmation
        self.state = self._load_state()
        self._snap_cache = (0.0, None)
        self._alert_thread = None
        self._stop = threading.Event()

    # -- persistence --------------------------------------------------------
    def _load_state(self):
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"watchlist": [], "alerts": []}

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _log_trade(self, order: Order, result: str):
        rec = {"time": dt.datetime.now().isoformat(timespec="seconds"), "mode": self.mode, **asdict(order),
               "result": result}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    # -- symbols ------------------------------------------------------------------
    def resolve(self, phrase: str, original: str = "", strict=False):
        """Turn 'apple' / 'AAPL' / 'a a p l' / 'tesla stock' into a ticker, or None."""
        p = phrase.lower().strip(" .?!,")
        p = re.sub(r"^(?:the |shares of |stock of )", "", p)
        p = re.sub(r"\s+(?:stock|shares|share|inc|corp|corporation|company)$", "", p).strip()
        if p in NAMES:
            return NAMES[p]
        caps = [t for t in explicit_tickers(original) if t.lower() in p.replace(" ", "").replace(".", "") or
                t.lower() == p.replace(" ", "")]
        if caps:
            return caps[0]
        spelled = re.fullmatch(r"(?:[a-z][ .]+){1,4}[a-z]\.?", p)          # "a a p l" / "a.a.p.l."
        if spelled:
            return re.sub(r"[ .]", "", p).upper()
        if p.startswith("$"):
            return p[1:].upper()
        if strict:
            if re.fullmatch(r"[a-z]{1,5}(?:\.[a-z])?", p):
                return p.upper()
            try:
                return self.data.search(p)
            except Exception:
                return None
        return None

    # -- spoken replies -----------------------------------------------------------
    def quote_reply(self, symbol: str) -> str:
        q = self.data.quote(symbol)
        return f"{friendly(symbol)} is at {money(q.price)}, {pct_phrase(q.change_pct)} today."

    def snapshot(self, max_age=60) -> AccountSnapshot:
        t, snap = self._snap_cache
        if snap is None or time.time() - t > max_age:
            snap = self.broker.snapshot()
            self._snap_cache = (time.time(), snap)
        return snap

    def _account_label(self):
        return "Your Robinhood account" if self.broker.live else "Your paper account"

    def portfolio_reply(self) -> str:
        s = self.snapshot(max_age=15)
        parts = [f"{self._account_label()} is worth {money(s.total)}"]
        if s.positions or s.prev_equity:
            base = s.total - s.day_change
            pct = s.day_change / base * 100 if base else 0
            if abs(s.day_change) >= 0.01:
                parts[0] += f", {'up' if s.day_change > 0 else 'down'} {money(abs(s.day_change))} today ({pct_phrase(pct)})"
            else:
                parts[0] += ", flat today"
        parts[0] += "."
        if not self.broker.live:
            start = self.broker.state.get("starting_cash", self.cfg.paper_starting_cash)
            gain = s.total - start
            if abs(gain) < 0.01:
                parts.append(f"You're even with the {money(start)} you started with.")
            else:
                parts.append(f"That's {'a gain' if gain > 0 else 'a loss'} of {money(abs(gain))} since you started with {money(start)}.")
        movers = sorted((p for p in s.positions if p.prev_close), key=lambda p: abs(p.day_change), reverse=True)[:2]
        if movers:
            bits = [f"{friendly(p.symbol)} {pct_phrase((p.price - p.prev_close) / p.prev_close * 100)}" for p in movers]
            parts.append("Biggest movers: " + " and ".join(bits) + ".")
        elif not s.positions:
            parts.append(f"You're all in cash, with {money(s.cash)} to invest.")
        return " ".join(parts)

    def positions_reply(self) -> str:
        s = self.snapshot(max_age=15)
        if not s.positions:
            return "You don't own any stocks right now" + ("" if self.broker.live else " in your paper account") + "."
        top = sorted(s.positions, key=lambda p: p.value, reverse=True)
        bits = [f"{_fmt_qty(p.quantity)} {friendly(p.symbol)} worth {money(p.value)}, {pct_phrase(p.total_gain_pct)} overall"
                for p in top[:5]]
        more = f" and {len(top) - 5} more" if len(top) > 5 else ""
        return f"You hold {len(top)} position{'s' if len(top) != 1 else ''}: " + "; ".join(bits) + more + "."

    def buying_power_reply(self) -> str:
        return f"You have {money(self.broker.buying_power())} of buying power" + ("." if self.broker.live else " in your paper account.")

    def mode_reply(self) -> str:
        if self.broker.live:
            return (f"We're in live mode, sir: orders use real money in your Robinhood account, with a safety limit of "
                    f"{money(self.max_order)} per order.")
        return "We're paper trading: real prices, pretend money. To trade for real, set TRADING_MODE=live in the settings file."

    # -- orders ---------------------------------------------------------------------
    def parse_order(self, side: str, rest: str, original: str = ""):
        r = " " + rest.lower().strip(" .!?") + " "
        limit = dollars = qty = 0.0
        sell_all = False
        m = re.search(r"\s(?:at|@|with a limit(?: price)? of|limit(?: price)?(?: of)?|for no more than|for at least)\s+\$?(" + _NUMWORD + r")(?:\s*(?:dollars|bucks))?(?:\s+(?:a|per) share)?\s", r)
        if m:
            limit = _number_phrase(m.group(1)) or 0.0
            r = r[:m.start()] + " " + r[m.end():]
        m = re.search(r"\s\$\s?([\d,]+(?:\.\d+)?)\s*(?:worth\s+)?(?:of\s+)?|\s(" + _NUMWORD + r")\s+(?:dollars?|bucks|usd)\s+(?:worth\s+)?(?:of\s+)?", r)
        if m:
            dollars = _number_phrase(m.group(1) or m.group(2)) or 0.0
            r = r[:m.start()] + " " + r[m.end():]
        m = re.search(r"\s(all|everything|all of|all my|all of my|my entire)\s", r)
        if m and side == "sell":
            sell_all = True
            r = r[:m.start()] + " " + r[m.end():]
        if not dollars:
            m = re.search(r"\s(" + _NUMWORD + r")\s+(?:shares?\s+(?:of\s+)?|of\s+)?", r)
            if m:
                qty = _number_phrase(m.group(1)) or 0.0
                r = r[:m.start()] + " " + r[m.end():]
        r = re.sub(r"\b(?:shares?|of|my|some|stock|please|for me|right now|now)\b", " ", r)
        sym_phrase = re.sub(r"\s+", " ", r).strip()
        symbol = self.resolve(sym_phrase, original, strict=True) if sym_phrase else None
        return symbol, qty, dollars, limit, sell_all

    def prepare_order(self, side: str, rest: str, original: str = "") -> str:
        side = "buy" if side in ("buy", "purchase") else "sell"
        symbol, qty, dollars, limit, sell_all = self.parse_order(side, rest, original)
        if not symbol:
            return f"Which stock would you like to {side}? Say something like: {side} 5 shares of Apple."
        try:
            q = self.data.quote(symbol)
        except Exception:
            return f"I couldn't find a price for {symbol}, so I won't place that order. Is that the right ticker?"
        if sell_all:
            qty = self.broker.held(symbol)
            if not qty:
                return f"You don't own any {friendly(symbol)}."
        if not qty and not dollars:
            return f"How many shares of {friendly(symbol)}, or how many dollars' worth? For example: {side} 2 shares of {friendly(symbol)}."
        if dollars and limit:
            return "For limit orders, please give a number of shares rather than a dollar amount."
        order = Order(side, symbol, quantity=qty, dollars=dollars, limit_price=limit, est_price=q.price)
        value = order.est_value
        if side == "sell" and not sell_all:
            held = self.broker.held(symbol)
            if order.est_shares > held + 1e-9:
                return f"You only have {_fmt_qty(held)} shares of {friendly(symbol)}, so I can't sell that many."
        if self.broker.live and value > self.max_order:
            return (f"That order would be about {money(value)}, which is over your safety limit of {money(self.max_order)}. "
                    f"You can change MAX_ORDER_USD in the settings file if you really mean it.")
        if side == "buy":
            bp = self.broker.buying_power()
            if value > bp + 0.01:
                return f"That would cost about {money(value)}, but you only have {money(bp)} of buying power."
        self.pending = order
        per_share = f" at {money(q.price)} a share" if order.quantity != 1 else ""
        approx = f"about {money(value)}{per_share}" if not dollars else f"about {_fmt_qty(round(order.est_shares, 4))} shares at {money(q.price)}"
        closed = "" if market_status()[0] else " The market's closed, so it would fill when it next opens."
        if self.broker.live:
            return (f"Live order with real money: {order.describe()}, {approx}.{closed} "
                    f"Say 'confirm order' to place it, or 'cancel'.")
        return f"Paper trade: {order.describe()}, {approx}.{closed} Shall I go ahead?"

    def confirm(self, text: str, typed_yes=False):
        """Handle the reply to an order confirmation. Returns a reply, or None if it wasn't about the order."""
        order = self.pending
        if order is None:
            return None
        if time.time() - order.created > 120:
            self.pending = None
            return "That order expired, so I didn't place it. Ask again if you still want it."
        t = text.strip().lower()
        if _NO.match(t):
            self.pending = None
            return "Order cancelled. Nothing was placed."
        approved = typed_yes or (re.search(r"\bconfirm(?:ed)?\b", t) if self.broker.live else _YES.match(t))
        if not approved:
            self.pending = None
            if self.broker.live and _YES.match(t):
                return "For real-money orders I need you to say the words 'confirm order'. I've cancelled it to be safe. Ask again if you'd like."
            return None  # something unrelated: drop the order and handle the new request normally
        self.pending = None
        try:
            result = self.broker.place(order)
        except FriendlyError:
            raise
        except Exception as e:
            result = f"The order failed: {e}"
        self._snap_cache = (0.0, None)
        self._log_trade(order, result)
        return result

    def cancel_orders_reply(self) -> str:
        return self.broker.cancel_all()

    # -- watchlist ------------------------------------------------------------------
    def watch_add(self, symbol):
        if symbol in self.state["watchlist"]:
            return f"{friendly(symbol)} is already on your watchlist."
        self.state["watchlist"].append(symbol)
        self._save_state()
        return f"Added {friendly(symbol)} to your watchlist."

    def watch_remove(self, symbol):
        if symbol not in self.state["watchlist"]:
            return f"{friendly(symbol)} isn't on your watchlist."
        self.state["watchlist"].remove(symbol)
        self._save_state()
        return f"Removed {friendly(symbol)} from your watchlist."

    def watchlist_reply(self):
        wl = self.state["watchlist"]
        if not wl:
            return "Your watchlist is empty. Say, add Nvidia to my watchlist, to start one."
        bits = []
        for sym in wl[:8]:
            try:
                q = self.data.quote(sym)
                bits.append(f"{friendly(sym)} {money(q.price)}, {pct_phrase(q.change_pct)}")
            except Exception:
                bits.append(f"{friendly(sym)} unavailable")
        return "Your watchlist: " + "; ".join(bits) + "."

    # -- price alerts -------------------------------------------------------------------
    def add_alert(self, symbol, direction, price):
        op = "above" if direction in ("above", "over", "past", "to", "hit", "hits") else "below"
        try:
            now = self.data.quote(symbol).price
            if direction in ("to", "hit", "hits"):
                op = "above" if price >= now else "below"
        except Exception:
            now = None
        self.state["alerts"].append({"symbol": symbol, "op": op, "price": price})
        self._save_state()
        self.start_alerts()
        extra = f" It's at {money(now)} now." if now else ""
        return f"I'll let you know if {friendly(symbol)} goes {op} {money(price)}.{extra}"

    def alerts_reply(self):
        a = self.state["alerts"]
        if not a:
            return "You don't have any price alerts set."
        return "Your alerts: " + "; ".join(f"{friendly(x['symbol'])} {x['op']} {money(x['price'])}" for x in a) + "."

    def cancel_alerts(self, symbol=None):
        before = len(self.state["alerts"])
        self.state["alerts"] = [a for a in self.state["alerts"] if symbol and a["symbol"] != symbol]
        self._save_state()
        n = before - len(self.state["alerts"])
        return f"Cancelled {n} alert{'s' if n != 1 else ''}." if n else "There weren't any alerts to cancel."

    def check_alerts(self):
        """Check all alerts once; announce and remove the ones that triggered."""
        remaining = []
        for a in list(self.state["alerts"]):
            try:
                q = self.data.quote(a["symbol"])
            except Exception:
                remaining.append(a)
                continue
            hit = q.price >= a["price"] if a["op"] == "above" else q.price <= a["price"]
            if hit:
                self.notify(f"Price alert: {friendly(a['symbol'])} just went {a['op']} {money(a['price'])}. "
                            f"It's at {money(q.price)}.")
            else:
                remaining.append(a)
        if len(remaining) != len(self.state["alerts"]):
            self.state["alerts"] = remaining
            self._save_state()

    def start_alerts(self):
        if self._alert_thread is not None and self._alert_thread.is_alive():
            return

        def loop():
            while not self._stop.wait(self.cfg.alert_check_seconds):
                if not self.state["alerts"]:
                    continue
                try:
                    self.check_alerts()
                except Exception:
                    pass

        self._alert_thread = threading.Thread(target=loop, daemon=True)
        self._alert_thread.start()

    # -- context for the AI ---------------------------------------------------------------
    def context_for(self, text: str) -> str:
        """Fresh market/account data to include when you ask the AI about stocks."""
        syms = names_in(text) + [s for s in explicit_tickers(text) if s not in names_in(text)]
        related = bool(_TRADING_WORDS.search(text.lower())) or bool(syms)
        if not related:
            return ""
        lines = [f"Trading mode: {'LIVE (real money, Robinhood)' if self.broker.live else 'PAPER (practice money)'}.",
                 market_status()[1]]
        try:
            s = self.snapshot()
            lines.append(f"Account value {money(s.total)}, cash/buying power {money(s.cash)}, change today {money(s.day_change)}.")
            for p in sorted(s.positions, key=lambda p: p.value, reverse=True)[:10]:
                day = f", today {pct_phrase((p.price - p.prev_close) / p.prev_close * 100)}" if p.prev_close else ""
                lines.append(f"- holds {_fmt_qty(p.quantity)} {p.symbol} @ avg {money(p.avg_price)}, now {money(p.price)} "
                             f"(value {money(p.value)}, {pct_phrase(p.total_gain_pct)} total{day})")
        except Exception as e:
            lines.append(f"(Couldn't load account data: {str(e).splitlines()[0][:120]})")
        for sym in syms[:5]:
            try:
                q = self.data.quote(sym)
                lines.append(f"- quote {sym} ({friendly(sym)}): {money(q.price)}, {pct_phrase(q.change_pct)} today")
            except Exception:
                pass
        if self.state["watchlist"]:
            lines.append("Watchlist: " + ", ".join(self.state["watchlist"]))
        return "\n".join(lines)

    # -- router ---------------------------------------------------------------------------
    def handle(self, t: str, original: str = ""):
        """t = normalized (lower-case) text. Returns a spoken reply, or None if it's not a trading command."""
        original = original or t
        if self.pending is not None:
            r = self.confirm(t)
            if r is not None:
                return r
        if _MODE_RE.search(t):
            return self.mode_reply()
        if _MARKET_RE.search(t):
            return market_status()[1]
        if _RESET_PAPER_RE.match(t):
            if self.broker.live:
                return "There's no paper account in live mode."
            self.broker.reset()
            self._snap_cache = (0.0, None)
            return f"Paper account reset to {money(self.cfg.paper_starting_cash)} in cash."
        if _BP_RE.search(t):
            return self.buying_power_reply()
        if _POSITIONS_RE.search(t):
            return self.positions_reply()
        if _PORTFOLIO_RE.search(t):
            return self.portfolio_reply()
        if _CANCEL_ORDERS_RE.match(t):
            return self.cancel_orders_reply()

        m = _ALERT_CANCEL_RE.match(t)
        if m:
            sym = self.resolve(m.group(1), original, strict=True) if m.group(1) else None
            return self.cancel_alerts(sym)
        m = _ALERT_RE.match(t)
        if m:
            name, direction, price = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
            sym = self.resolve(name, original, strict=True)
            value = _number_phrase(price.replace("$", ""))
            if not sym or not value:
                return "Tell me the stock and the price, like: alert me if Tesla goes above 300."
            return self.add_alert(sym, direction, value)
        if _ALERT_LIST_RE.search(t):
            return self.alerts_reply()

        m = _WATCH_DEL_RE.match(t)
        if m:
            sym = self.resolve(m.group(1), original, strict=True)
            return self.watch_remove(sym) if sym else "Which stock should I remove?"
        m = _WATCH_ADD_RE.match(t)
        if m:
            sym = self.resolve(m.group(1) or m.group(2), original, strict=True)
            if sym:
                return self.watch_add(sym)
            if m.group(1):
                return "I couldn't work out which stock that is."
        if _WATCH_SHOW_RE.search(t):
            return self.watchlist_reply()

        m = _ORDER_RE.match(t)
        if m:
            return self.prepare_order(m.group(1), m.group(2), original)

        for pattern in _QUOTE_STRICT:
            m = pattern.match(t)
            if m:
                sym = self.resolve(m.group(1), original, strict=True)
                if sym:
                    return self._safe_quote(sym)
        for pattern in _QUOTE_LOOSE:
            m = pattern.match(t)
            if m:
                sym = self.resolve(m.group(1), original, strict=False)
                if sym:
                    return self._safe_quote(sym)
        return None

    def _safe_quote(self, sym):
        try:
            return self.quote_reply(sym)
        except LookupError:
            return f"I couldn't find a price for {sym}. Is that the right ticker?"
