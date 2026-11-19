# GlobalBLOCS Investment Methodology and Risk Policy

All signals are research outputs, not orders and not guarantees of return. Live orders require a human
trader or admin to approve with an exact confirmation phrase after an automated risk check and broker preview.

Default limits: maximum single position 10% of equity and $10,000; maximum gross exposure 95%; daily loss
limit $1,000 locks new orders for the rest of the day; 25 orders per day. Paper trading is the default mode and
live trading stays disabled until it is switched on in settings after at least ten paper-trading days.

Research must avoid look-ahead bias (decisions at bar t use data through t-1 for fills at t), survivorship bias
(use point-in-time universes including delisted names), and data leakage (purged time-series splits). Backtests
include commissions, half-spread, slippage, square-root market impact and a 5% ADV participation cap.

Every price and signal shows its source, latency label (real-time, delayed, end-of-day, simulated) and timestamp.
