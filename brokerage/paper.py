"""Paper-trading broker. Same interface as live brokers; required before live execution is enabled."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from brokerage.base import BrokerageClient, OrderRequest


class PaperBroker(BrokerageClient):
    name = "paper"
    can_trade = True

    def __init__(self, cash: float = 100_000.0, price_fn=None, slippage_bps: float = 2.0):
        self.cash, self.pos, self.avg, self._orders, self._tx = cash, {}, {}, [], []
        self.realized = 0.0
        self.price_fn = price_fn or (lambda s: 100.0)
        self.slip = slippage_bps / 1e4

    def accounts(self):
        return [{"accountId": "PAPER-1", "type": "SIMULATED"}]

    def balances(self, account_id="PAPER-1"):
        mv = sum(q * self.price_fn(s) for s, q in self.pos.items())
        return {"cash": round(self.cash, 2), "buying_power": round(self.cash, 2), "market_value": round(mv, 2),
                "total_value": round(self.cash + mv, 2), "realized_pl": round(self.realized, 2)}

    def positions(self, account_id="PAPER-1"):
        return [{"symbol": s, "quantity": q, "avg_cost": round(self.avg[s], 4), "price": self.price_fn(s),
                 "unrealized_pl": round(q * (self.price_fn(s) - self.avg[s]), 2)} for s, q in self.pos.items() if q]

    def transactions(self, account_id="PAPER-1"):
        return list(self._tx)

    def orders(self, account_id="PAPER-1"):
        return list(self._orders)

    def preview_order(self, o: OrderRequest):
        o.validate()
        px = self.price_fn(o.symbol)
        est = px * (1 + self.slip if o.side == "BUY" else 1 - self.slip)
        return {"preview_id": uuid.uuid4().hex, "estimated_price": round(est, 4), "estimated_value": round(est * o.quantity, 2)}

    def place_order(self, o: OrderRequest, preview: dict):
        px = self.price_fn(o.symbol)
        marketable = (o.order_type == "MARKET" or (o.side == "BUY" and o.limit_price and o.limit_price >= px)
                      or (o.side == "SELL" and o.limit_price and o.limit_price <= px))
        rec = {"order_id": uuid.uuid4().hex[:12], "symbol": o.symbol, "side": o.side, "quantity": o.quantity,
               "type": o.order_type, "limit": o.limit_price, "status": "OPEN",
               "time": datetime.now(timezone.utc).isoformat()}
        if marketable:
            fill = px * (1 + self.slip if o.side == "BUY" else 1 - self.slip)
            q = o.quantity if o.side == "BUY" else -o.quantity
            if o.side == "BUY":
                if fill * o.quantity > self.cash:
                    raise ValueError("insufficient buying power")
                held = self.pos.get(o.symbol, 0)
                self.avg[o.symbol] = (self.avg.get(o.symbol, 0) * held + fill * o.quantity) / (held + o.quantity)
            else:
                if self.pos.get(o.symbol, 0) < o.quantity:
                    raise ValueError("short selling disabled in paper account")
                self.realized += o.quantity * (fill - self.avg[o.symbol])
            self.pos[o.symbol] = self.pos.get(o.symbol, 0) + q
            self.cash -= q * fill
            rec.update(status="FILLED", fill_price=round(fill, 4))
            self._tx.append(rec)
        self._orders.append(rec)
        return rec

    def cancel_order(self, account_id, order_id):
        for r in self._orders:
            if r["order_id"] == order_id and r["status"] == "OPEN":
                r["status"] = "CANCELLED"
                return r
        raise KeyError("open order not found")
