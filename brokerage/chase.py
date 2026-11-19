"""Chase / J.P. Morgan Self-Directed Investing — READ-ONLY.

Chase does not publish a public trading or account API for self-directed investors. Account data
is reached through licensed aggregators the account holder authorizes via OAuth (no password is
ever seen or stored by this app). Two adapters are provided:

* PlaidChaseClient   — Plaid Investments (holdings, investment transactions, balances).
* SnapTradeChaseClient — SnapTrade, which lists Chase as a read-only connection.

Trading through Chase is intentionally unsupported; preview/place raise NotSupported.
Verify aggregator coverage, pricing and field names for your account type before relying on them."""
from __future__ import annotations

import os
from datetime import date, timedelta

import httpx

from brokerage.base import BrokerageClient

PLAID_HOSTS = {"sandbox": "https://sandbox.plaid.com", "production": "https://production.plaid.com"}


class PlaidChaseClient(BrokerageClient):
    name = "chase"
    can_trade = False

    def __init__(self, access_token: str, client_id: str | None = None, secret: str | None = None, env: str = "sandbox"):
        self.host = PLAID_HOSTS[env]
        self.auth = {"client_id": client_id or os.environ["PLAID_CLIENT_ID"], "secret": secret or os.environ["PLAID_SECRET"],
                     "access_token": access_token}

    def _post(self, path, **body):
        r = httpx.post(f"{self.host}{path}", json={**self.auth, **body}, timeout=30)
        r.raise_for_status()
        return r.json()

    def accounts(self):
        return self._post("/accounts/get")["accounts"]

    def balances(self, account_id):
        accts = self._post("/accounts/balance/get", options={"account_ids": [account_id]})["accounts"]
        return accts[0]["balances"] if accts else {}

    def positions(self, account_id):
        js = self._post("/investments/holdings/get", options={"account_ids": [account_id]})
        sec = {s["security_id"]: s for s in js["securities"]}
        return [{**h, "ticker": sec.get(h["security_id"], {}).get("ticker_symbol"),
                 "name": sec.get(h["security_id"], {}).get("name"),
                 "type": sec.get(h["security_id"], {}).get("type"),
                 "unrealized_pl": (h.get("institution_value") or 0) - (h.get("cost_basis") or 0)} for h in js["holdings"]]

    def transactions(self, account_id, days: int = 730):
        end = date.today()
        js = self._post("/investments/transactions/get", start_date=str(end - timedelta(days=days)), end_date=str(end),
                        options={"account_ids": [account_id], "count": 500})
        return js["investment_transactions"]

    def dividends(self, account_id):
        return [t for t in self.transactions(account_id) if t.get("subtype") in ("dividend", "qualified dividend")]


class SnapTradeChaseClient(BrokerageClient):
    """Thin wrapper over the official `snaptrade-python-sdk`. Method names follow the SDK's
    account_information namespace; check them against the SDK version you install."""
    name = "chase"
    can_trade = False

    def __init__(self, user_id: str, user_secret: str):
        from snaptrade_client import SnapTrade
        self.api = SnapTrade(consumer_key=os.environ["SNAPTRADE_CONSUMER_KEY"], client_id=os.environ["SNAPTRADE_CLIENT_ID"])
        self.u = {"user_id": user_id, "user_secret": user_secret}

    def accounts(self):
        return self.api.account_information.list_user_accounts(**self.u).body

    def balances(self, account_id):
        return self.api.account_information.get_user_account_balance(account_id=account_id, **self.u).body

    def positions(self, account_id):
        return self.api.account_information.get_user_account_positions(account_id=account_id, **self.u).body

    def transactions(self, account_id):
        return self.api.account_information.get_account_activities(account_id=account_id, **self.u).body
