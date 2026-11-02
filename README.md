# AI Trading — Robinhood CLI Bot

A small CLI for checking quotes/positions and placing stock orders on Robinhood,
built on [robin_stocks](https://github.com/jmfernandes/robin_stocks).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your Robinhood credentials
```

If you have 2FA via an authenticator app, set `ROBINHOOD_TOTP_SECRET` in `.env`
to the base32 secret shown when you set up the authenticator (not the 6-digit code).

## Usage

```bash
python -m trading_bot.cli quote AAPL
python -m trading_bot.cli positions
python -m trading_bot.cli buying-power

# Dry run (default) — simulates the trade, places nothing
python -m trading_bot.cli buy AAPL 1

# Real order — requires --live and a typed "yes" confirmation
python -m trading_bot.cli buy AAPL 1 --live
python -m trading_bot.cli sell AAPL 1 --live --limit-price 150.00
```

## Safety notes

- Every trade command defaults to `--dry-run` behavior: no order is sent, you
  just see the estimated price/cost. Real orders require the explicit `--live`
  flag *and* typing `yes` at a confirmation prompt.
- Your `.env` file is git-ignored. Never commit real credentials.
- This code places real financial orders when run with `--live`. Test with
  small quantities first and understand Robinhood's order types before
  relying on it.

## JARVIS voice assistant

The [`jarvis/`](jarvis/) folder contains a separate project: a Windows voice assistant
(wake word, local speech recognition, Claude/Ollama brain, natural voice, memory).
See [jarvis/SETUP_GUIDE.md](jarvis/SETUP_GUIDE.md).
