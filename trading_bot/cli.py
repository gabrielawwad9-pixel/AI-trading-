"""Command-line interface for the Robinhood trading bot.

Safety model:
- All trade commands run in --dry-run mode by default (no real order is sent).
- To place a REAL order you must pass --live AND type "yes" at the confirmation
  prompt. There is no way to skip the prompt from the command line.
"""
import argparse
import json
import sys

from trading_bot import auth, orders


def _confirm_live_trade(description: str) -> bool:
    print(f"You are about to place a REAL order: {description}")
    answer = input('Type "yes" to confirm, anything else to abort: ')
    return answer.strip().lower() == "yes"


def cmd_quote(args):
    print(f"{args.symbol}: ${orders.get_quote(args.symbol):.2f}")


def cmd_positions(args):
    print(json.dumps(orders.get_positions(), indent=2))


def cmd_buying_power(args):
    print(f"${orders.get_buying_power():.2f}")


def cmd_buy(args):
    _trade(args, "buy")


def cmd_sell(args):
    _trade(args, "sell")


def _trade(args, action):
    live = args.live
    if live:
        desc = f"{action.upper()} {args.quantity} {args.symbol}"
        if args.limit_price:
            desc += f" @ limit ${args.limit_price}"
        if not _confirm_live_trade(desc):
            print("Aborted.")
            sys.exit(1)

    dry_run = not live
    if args.limit_price:
        fn = orders.place_limit_buy if action == "buy" else orders.place_limit_sell
        result = fn(args.symbol, args.quantity, args.limit_price, dry_run=dry_run)
    else:
        fn = orders.place_market_buy if action == "buy" else orders.place_market_sell
        result = fn(args.symbol, args.quantity, dry_run=dry_run)

    print(json.dumps(result, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Robinhood trading bot CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_quote = sub.add_parser("quote", help="Get the latest price for a symbol")
    p_quote.add_argument("symbol")
    p_quote.set_defaults(func=cmd_quote)

    p_pos = sub.add_parser("positions", help="Show current holdings")
    p_pos.set_defaults(func=cmd_positions)

    p_bp = sub.add_parser("buying-power", help="Show available buying power")
    p_bp.set_defaults(func=cmd_buying_power)

    for name, fn in (("buy", cmd_buy), ("sell", cmd_sell)):
        p = sub.add_parser(name, help=f"{name.capitalize()} a stock")
        p.add_argument("symbol")
        p.add_argument("quantity", type=float)
        p.add_argument("--limit-price", type=float, default=None, help="Use a limit order instead of market")
        p.add_argument("--live", action="store_true", help="Place a REAL order (default is a dry run/simulation)")
        p.set_defaults(func=fn)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    auth.login()
    try:
        args.func(args)
    finally:
        auth.logout()


if __name__ == "__main__":
    main()
