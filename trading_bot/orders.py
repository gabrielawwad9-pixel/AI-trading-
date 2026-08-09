"""Order placement and account inspection helpers, all built on robin_stocks."""
import robin_stocks.robinhood as rh


def get_quote(symbol: str) -> float:
    price = rh.stocks.get_latest_price(symbol)[0]
    return float(price)


def get_buying_power() -> float:
    profile = rh.profiles.load_account_profile()
    return float(profile["buying_power"])


def get_positions():
    holdings = rh.build_holdings()
    return holdings


def place_market_buy(symbol: str, quantity: float, dry_run: bool = True):
    if dry_run:
        price = get_quote(symbol)
        return {
            "dry_run": True,
            "action": "buy",
            "symbol": symbol,
            "quantity": quantity,
            "estimated_price": price,
            "estimated_cost": price * quantity,
        }
    return rh.orders.order_buy_market(symbol, quantity)


def place_market_sell(symbol: str, quantity: float, dry_run: bool = True):
    if dry_run:
        price = get_quote(symbol)
        return {
            "dry_run": True,
            "action": "sell",
            "symbol": symbol,
            "quantity": quantity,
            "estimated_price": price,
            "estimated_proceeds": price * quantity,
        }
    return rh.orders.order_sell_market(symbol, quantity)


def place_limit_buy(symbol: str, quantity: float, limit_price: float, dry_run: bool = True):
    if dry_run:
        return {
            "dry_run": True,
            "action": "buy",
            "symbol": symbol,
            "quantity": quantity,
            "limit_price": limit_price,
        }
    return rh.orders.order_buy_limit(symbol, quantity, limit_price)


def place_limit_sell(symbol: str, quantity: float, limit_price: float, dry_run: bool = True):
    if dry_run:
        return {
            "dry_run": True,
            "action": "sell",
            "symbol": symbol,
            "quantity": quantity,
            "limit_price": limit_price,
        }
    return rh.orders.order_sell_limit(symbol, quantity, limit_price)


def cancel_all_open_orders():
    return rh.orders.cancel_all_stock_orders()
