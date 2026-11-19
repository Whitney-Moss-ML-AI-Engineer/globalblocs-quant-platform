from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


class NotSupported(Exception):
    """Raised when a brokerage does not expose a capability through an authorized API."""


@dataclass
class OrderRequest:
    symbol: str
    side: str                 # BUY | SELL
    quantity: int
    order_type: str = "LIMIT"  # MARKET | LIMIT | STOP | STOP_LIMIT
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "DAY"  # DAY | GTC
    account_id: str = ""
    client_order_id: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("GB%Y%m%d%H%M%S%f")[:20])

    def validate(self):
        if self.side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type in ("LIMIT", "STOP_LIMIT") and not self.limit_price:
            raise ValueError("limit price required")
        if self.order_type in ("STOP", "STOP_LIMIT") and not self.stop_price:
            raise ValueError("stop price required")


class BrokerageClient(ABC):
    name: str
    can_trade: bool = False

    @abstractmethod
    def accounts(self) -> list[dict]: ...

    @abstractmethod
    def balances(self, account_id: str) -> dict: ...

    @abstractmethod
    def positions(self, account_id: str) -> list[dict]: ...

    @abstractmethod
    def transactions(self, account_id: str) -> list[dict]: ...

    def orders(self, account_id: str) -> list[dict]:
        raise NotSupported(f"{self.name}: orders not available")

    def preview_order(self, order: OrderRequest) -> dict:
        raise NotSupported(f"{self.name}: trading is not available through an authorized API")

    def place_order(self, order: OrderRequest, preview: dict) -> dict:
        raise NotSupported(f"{self.name}: trading is not available through an authorized API")

    def cancel_order(self, account_id: str, order_id: str) -> dict:
        raise NotSupported(f"{self.name}: order cancellation not available")
