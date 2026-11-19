"""Apache Airflow DAGs for the recurring workflows (times are US/Eastern, NYSE trading days)."""
from __future__ import annotations

import pendulum
from airflow.decorators import dag, task

ET = pendulum.timezone("America/New_York")
DEFAULT = {"retries": 2, "retry_delay": pendulum.duration(minutes=5)}


@dag(schedule="0 6 * * 1-5", start_date=pendulum.datetime(2026, 1, 1, tz=ET), catchup=False, default_args=DEFAULT, tags=["premarket"])
def premarket():
    @task
    def update_market_data(): ...          # pull overnight bars, futures, FX, commodities -> mkt.bar
    @task
    def economic_calendar(): ...           # FRED releases due today, Fed speakers
    @task
    def overnight_moves(): ...             # gaps vs prior close, premarket volume
    @task
    def screen_and_rank(): ...             # quant.factors.composite + signals.best_signals -> research.signal
    @task
    def premarket_report(): ...            # agents.orchestrator.run_all -> PDF/email
    update_market_data() >> [economic_calendar(), overnight_moves()] >> screen_and_rank() >> premarket_report()


@dag(schedule="*/5 9-16 * * 1-5", start_date=pendulum.datetime(2026, 1, 1, tz=ET), catchup=False, default_args=DEFAULT, tags=["intraday"])
def intraday():
    @task
    def refresh_signals(): ...             # watchlist signals, unusual volume (rvol > 3), VWAP crosses
    @task
    def evaluate_positions(): ...          # stop-loss distance, drawdown, exposure vs limits
    @task
    def risk_alerts(): ...                 # push/email when a limit is near or breached
    refresh_signals() >> evaluate_positions() >> risk_alerts()


@dag(schedule="30 16 * * 1-5", start_date=pendulum.datetime(2026, 1, 1, tz=ET), catchup=False, default_args=DEFAULT, tags=["close"])
def after_close():
    @task
    def daily_performance(): ...           # broker snapshots -> trading.position_snapshot, P/L
    @task
    def record_trades(): ...               # reconcile fills vs proposals, journal
    @task
    def model_accuracy(): ...              # score yesterday's predictions vs realized
    @task
    def daily_summary(): ...
    daily_performance() >> record_trades() >> model_accuracy() >> daily_summary()


@dag(schedule="0 10 * * 6", start_date=pendulum.datetime(2026, 1, 1, tz=ET), catchup=False, default_args=DEFAULT, tags=["weekly"])
def weekly_review():
    @task
    def allocation_review(): ...
    @task
    def factor_performance(): ...
    @task
    def strategy_comparison(): ...
    @task
    def model_drift(): ...                 # ml.pipeline.psi on features; retrain if PSI > 0.25
    @task
    def weekly_report(): ...
    [allocation_review(), factor_performance(), strategy_comparison(), model_drift()] >> weekly_report()


premarket(); intraday(); after_close(); weekly_review()
