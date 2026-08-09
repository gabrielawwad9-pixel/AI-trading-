"""Robinhood authentication helpers."""
import os

import pyotp
import robin_stocks.robinhood as rh
from dotenv import load_dotenv

load_dotenv()


def login():
    """Log in to Robinhood using credentials from environment variables.

    Required env vars: ROBINHOOD_USERNAME, ROBINHOOD_PASSWORD.
    Optional: ROBINHOOD_TOTP_SECRET (for authenticator-app 2FA).
    """
    username = os.environ.get("ROBINHOOD_USERNAME")
    password = os.environ.get("ROBINHOOD_PASSWORD")
    totp_secret = os.environ.get("ROBINHOOD_TOTP_SECRET")

    if not username or not password:
        raise RuntimeError(
            "ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD must be set "
            "(e.g. in a .env file, see .env.example)."
        )

    mfa_code = pyotp.TOTP(totp_secret).now() if totp_secret else None

    return rh.login(username=username, password=password, mfa_code=mfa_code)


def logout():
    rh.logout()
