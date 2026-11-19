"""E*TRADE v1 REST API client (OAuth 1.0a).

Flow: request token -> user authorizes at E*TRADE and receives a verifier code -> access token.
Access tokens expire at midnight US Eastern and go inactive after ~2 hours idle (renew via
/oauth/renew_access_token). Orders must be previewed before they are placed; the preview ID is
passed to place. Use the sandbox (apisb.etrade.com) until your production key is approved.
Confirm endpoint details against the current E*TRADE developer documentation before going live."""
from __future__ import annotations

from requests_oauthlib import OAuth1Session

from brokerage.base import BrokerageClient, OrderRequest

PROD, SANDBOX = "https://api.etrade.com", "https://apisb.etrade.com"
AUTHORIZE_URL = "https://us.etrade.com/e/t/etws/authorize?key={key}&token={token}"


class ETradeAuth:
    def __init__(self, consumer_key: str, consumer_secret: str, sandbox: bool = True):
        self.key, self.secret = consumer_key, consumer_secret
        self.base = SANDBOX if sandbox else PROD

    def start(self) -> tuple[str, dict]:
        """Step 1: returns the URL the user opens in a browser, plus the temporary token to keep."""
        s = OAuth1Session(self.key, self.secret, callback_uri="oob", signature_type="AUTH_HEADER")
        tok = s.fetch_request_token(f"{PROD}/oauth/request_token")
        return AUTHORIZE_URL.format(key=self.key, token=tok["oauth_token"]), tok

    def finish(self, request_token: dict, verifier: str) -> dict:
        """Step 2: exchange the verifier code for an access token (store it encrypted, never the password)."""
        s = OAuth1Session(self.key, self.secret, resource_owner_key=request_token["oauth_token"],
                          resource_owner_secret=request_token["oauth_token_secret"], verifier=verifier)
        return s.fetch_access_token(f"{PROD}/oauth/access_token")


class ETradeClient(BrokerageClient):
    name = "etrade"

    def __init__(self, consumer_key: str, consumer_secret: str, access_token: dict, sandbox: bool = True,
                 trading_permission: bool = False):
        self.base = SANDBOX if sandbox else PROD
        self.can_trade = trading_permission
        self.s = OAuth1Session(consumer_key, consumer_secret, resource_owner_key=access_token["oauth_token"],
                               resource_owner_secret=access_token["oauth_token_secret"])

    def _get(self, path, **params):
        r = self.s.get(f"{self.base}{path}", params=params, headers={"Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        return r.json()

    def renew(self):
        self.s.get(f"{PROD}/oauth/renew_access_token", timeout=30).raise_for_status()

    def accounts(self):
        js = self._get("/v1/accounts/list.json")
        return js["AccountListResponse"]["Accounts"]["Account"]

    def balances(self, account_id):
        return self._get(f"/v1/accounts/{account_id}/balance.json", instType="BROKERAGE", realTimeNAV="true")["BalanceResponse"]

    def positions(self, account_id):
        js = self._get(f"/v1/accounts/{account_id}/portfolio.json", view="COMPLETE")
        out = []
        for acct in js.get("PortfolioResponse", {}).get("AccountPortfolio", []):
            out += acct.get("Position", [])
        return out

    def transactions(self, account_id):
        return self._get(f"/v1/accounts/{account_id}/transactions.json").get("TransactionListResponse", {}).get("Transaction", [])

    def orders(self, account_id):
        return self._get(f"/v1/accounts/{account_id}/orders.json").get("OrdersResponse", {}).get("Order", [])

    def quote(self, symbols: list[str]):
        return self._get(f"/v1/market/quote/{','.join(symbols)}.json")["QuoteResponse"]["QuoteData"]

    def option_chain(self, symbol: str, **params):
        return self._get("/v1/market/optionchains.json", symbol=symbol, **params)

    @staticmethod
    def _order_body(o: OrderRequest) -> dict:
        price_type = {"MARKET": "MARKET", "LIMIT": "LIMIT", "STOP": "STOP", "STOP_LIMIT": "STOP_LIMIT"}[o.order_type]
        order = {"allOrNone": "false", "priceType": price_type,
                 "orderTerm": "GOOD_FOR_DAY" if o.time_in_force == "DAY" else "GOOD_UNTIL_CANCEL",
                 "marketSession": "REGULAR",
                 "Instrument": [{"Product": {"securityType": "EQ", "symbol": o.symbol}, "orderAction": o.side,
                                 "quantityType": "QUANTITY", "quantity": o.quantity}]}
        if o.limit_price:
            order["limitPrice"] = o.limit_price
        if o.stop_price:
            order["stopPrice"] = o.stop_price
        return {"orderType": "EQ", "clientOrderId": o.client_order_id, "Order": [order]}

    def preview_order(self, o: OrderRequest):
        o.validate()
        body = {"PreviewOrderRequest": self._order_body(o)}
        r = self.s.post(f"{self.base}/v1/accounts/{o.account_id}/orders/preview.json", json=body,
                        headers={"Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        return r.json()["PreviewOrderResponse"]

    def place_order(self, o: OrderRequest, preview: dict):
        if not self.can_trade:
            raise PermissionError("trading permission not granted for this E*TRADE connection")
        body = {"PlaceOrderRequest": {**self._order_body(o), "PreviewIds": preview["PreviewIds"]}}
        r = self.s.post(f"{self.base}/v1/accounts/{o.account_id}/orders/place.json", json=body,
                        headers={"Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        return r.json()["PlaceOrderResponse"]

    def cancel_order(self, account_id, order_id):
        r = self.s.put(f"{self.base}/v1/accounts/{account_id}/orders/cancel.json",
                       json={"CancelOrderRequest": {"orderId": int(order_id)}}, headers={"Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        return r.json()
