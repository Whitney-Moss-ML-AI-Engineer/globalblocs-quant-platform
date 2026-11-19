"""Order management with hard separation between research and execution.

Lifecycle: PROPOSED (by a user or an AI agent) -> RISK_CHECKED -> PREVIEWED -> APPROVED (human only,
with explicit confirmation) -> SUBMITTED. Agents can propose but can never approve or submit.
Every transition is written to a hash-chained, append-only audit log."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from brokerage.base import BrokerageClient, OrderRequest

HUMAN_APPROVER_ROLES = {"admin", "trader"}


@dataclass
class RiskLimits:
    max_position_value: float = 10_000.0
    max_position_pct: float = 0.10
    max_portfolio_exposure_pct: float = 0.95
    daily_loss_limit: float = 1_000.0
    max_orders_per_day: int = 25
    restricted_symbols: set = field(default_factory=set)
    live_trading_enabled: bool = False
    require_paper_history_days: int = 10


class AuditLog:
    def __init__(self, path: str = "data/audit.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _last_hash(self) -> str:
        lines = self.path.read_text().strip().splitlines()
        return json.loads(lines[-1])["hash"] if lines else "GENESIS"

    def write(self, actor: str, action: str, detail: dict) -> dict:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "actor": actor, "action": action, "detail": detail,
                 "prev": self._last_hash()}
        entry["hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True, default=str).encode()).hexdigest()
        with self.path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def verify(self) -> bool:
        prev = "GENESIS"
        for line in self.path.read_text().strip().splitlines():
            e = json.loads(line)
            h = e.pop("hash")
            if e["prev"] != prev or hashlib.sha256(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest() != h:
                return False
            prev = h
        return True

    def tail(self, n: int = 100) -> list[dict]:
        return [json.loads(x) for x in self.path.read_text().strip().splitlines()[-n:]]


class OrderManager:
    def __init__(self, brokers: dict[str, BrokerageClient], limits: RiskLimits, audit: AuditLog):
        self.brokers, self.limits, self.audit = brokers, limits, audit
        self.proposals: dict[str, dict] = {}
        self.daily_pl: dict[date, float] = {}
        self.orders_today: dict[date, int] = {}

    # ---------- research side ----------
    def propose(self, broker: str, order: OrderRequest, actor: str, actor_role: str, rationale: str = "",
                signal_ref: dict | None = None) -> dict:
        order.validate()
        pid = uuid.uuid4().hex[:12]
        p = {"id": pid, "broker": broker, "order": asdict(order), "status": "PROPOSED", "proposed_by": actor,
             "proposed_by_role": actor_role, "rationale": rationale, "signal": signal_ref,
             "label": "RESEARCH RECOMMENDATION - NOT AN ORDER", "created": datetime.now(timezone.utc).isoformat()}
        self.proposals[pid] = p
        self.audit.write(actor, "order.proposed", {"id": pid, "order": p["order"]})
        return self.risk_check(pid, equity=None)

    def risk_check(self, pid: str, equity: float | None) -> dict:
        p = self.proposals[pid]
        o = OrderRequest(**p["order"])
        b = self.brokers[p["broker"]]
        bal = b.balances(o.account_id or (b.accounts()[0].get("accountId", "")))
        equity = equity or float(bal.get("total_value") or bal.get("Computed", {}).get("RealTimeValues", {}).get("totalAccountValue", 0) or 0)
        px = o.limit_price or b.preview_order(o).get("estimated_price", 0) if b.can_trade else (o.limit_price or 0)
        value = px * o.quantity
        L, today = self.limits, date.today()
        fails = []
        if o.symbol in L.restricted_symbols: fails.append("symbol restricted")
        if value > L.max_position_value: fails.append(f"order value {value:.0f} > max {L.max_position_value:.0f}")
        if equity and value > L.max_position_pct * equity: fails.append("exceeds max position % of equity")
        if equity and o.side == "BUY":
            mv = float(bal.get("market_value", 0) or 0)
            if (mv + value) / equity > L.max_portfolio_exposure_pct: fails.append("exceeds max portfolio exposure")
        if -self.daily_pl.get(today, 0) >= L.daily_loss_limit: fails.append("daily loss limit reached; trading locked")
        if self.orders_today.get(today, 0) >= L.max_orders_per_day: fails.append("max orders per day reached")
        if b.name != "paper" and not L.live_trading_enabled: fails.append("live trading disabled (paper mode)")
        if not b.can_trade: fails.append(f"{b.name} connection is read-only")
        p.update(status="REJECTED" if fails else "RISK_CHECKED", risk_failures=fails, est_value=round(value, 2))
        self.audit.write("risk-engine", "order.risk_checked", {"id": pid, "failures": fails})
        return p

    # ---------- human approval + execution side ----------
    def approve(self, pid: str, user: str, role: str, confirm_text: str) -> dict:
        p = self.proposals[pid]
        if role not in HUMAN_APPROVER_ROLES:
            self.audit.write(user, "order.approval_denied", {"id": pid, "reason": f"role {role}"})
            raise PermissionError("only a human trader or admin can approve orders; AI agents cannot")
        if p["status"] != "RISK_CHECKED":
            raise ValueError(f"cannot approve order in status {p['status']}")
        expected = f"APPROVE {p['order']['side']} {p['order']['quantity']} {p['order']['symbol']}"
        if confirm_text.strip().upper() != expected:
            raise ValueError(f"confirmation text must be exactly: {expected}")
        o = OrderRequest(**p["order"])
        p["preview"] = self.brokers[p["broker"]].preview_order(o)
        p.update(status="APPROVED", approved_by=user, approved_at=datetime.now(timezone.utc).isoformat())
        self.audit.write(user, "order.approved", {"id": pid, "preview": p["preview"]})
        return p

    def submit(self, pid: str, user: str, role: str) -> dict:
        p = self.proposals[pid]
        if role not in HUMAN_APPROVER_ROLES:
            raise PermissionError("AI agents cannot submit orders")
        if p["status"] != "APPROVED" or p.get("approved_by") != user:
            raise PermissionError("order must be approved by the submitting user first")
        res = self.brokers[p["broker"]].place_order(OrderRequest(**p["order"]), p["preview"])
        today = date.today()
        self.orders_today[today] = self.orders_today.get(today, 0) + 1
        p.update(status="SUBMITTED", broker_response=res, submitted_at=datetime.now(timezone.utc).isoformat())
        self.audit.write(user, "order.submitted", {"id": pid, "response": res})
        return p

    def record_pl(self, amount: float):
        self.daily_pl[date.today()] = self.daily_pl.get(date.today(), 0) + amount
