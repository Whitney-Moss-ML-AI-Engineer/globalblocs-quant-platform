# GlobalBLOCS Quantitative Trading & Investment Intelligence Platform

A quantitative research workstation, portfolio-management system and AI-assisted trading-intelligence dashboard,
delivered as a **desktop app with an installation wizard** (Windows / macOS / Linux) and as a cloud deployment on AWS.

> Research outputs, forecasts and signals are **not investment advice and never guarantee returns**. Every price and
> signal shows its source, its latency label (real-time / delayed / end-of-day / **simulated**) and its timestamp.

## Repository layout

| Directory | Contents |
|---|---|
| `quant/` | Technical indicators, 12-factor composite model, signal engine (7 strategies + pairs stat-arb), portfolio optimizers, risk analytics |
| `backtesting/` | Bar-by-bar backtester with commissions, spread, slippage, market impact, ADV cap, halts; walk-forward optimizer |
| `ml/` | Walk-forward ML pipeline (13 model types), deep-learning forecasters (ANN, CNN, LSTM, GRU, BiLSTM, TCN, Transformer), financial NLP |
| `agents/` | 12 research agents + Executive Analyst, RAG retriever, knowledge base (methodology & risk policy) |
| `brokerage/` | E*TRADE (official OAuth 1.0a API), Chase read-only (Plaid / SnapTrade), paper broker, approval-gated order manager, hash-chained audit log |
| `data_pipelines/` | Market/macro/SEC data providers with validation, TimescaleDB + pgvector warehouse schema, Airflow DAGs |
| `backend/` | FastAPI REST + WebSocket API, JWT auth, RBAC, encryption |
| `frontend/` | Next.js + TypeScript + Tailwind + Recharts dashboard (static export, mobile-responsive) |
| `desktop/` | Electron shell, **NSIS installation wizard**, first-run **Setup Wizard**, OS-keychain secret storage |
| `deploy/` | Dockerfiles, docker-compose stack, AWS Terraform |
| `tests/` | Unit + API integration tests (`pytest`) |

## Two wizards

1. **Installation wizard** (`desktop/package.json` → `build.nsis`, `desktop/build/installer.nsh`): an assisted Windows installer
   with license page, install-folder choice, desktop + Start-menu shortcuts, a Python pre-check, and an uninstaller that asks before
   deleting your data. macOS ships as a DMG, Linux as AppImage/.deb.
2. **Setup Wizard** (`desktop/wizard/`): runs on first launch. Nine steps: Welcome → License & risk disclosures (must accept) →
   System check (Python 3.10+, OS keychain, disk) → Install engine (private virtualenv + dependencies, live log) → Market data keys →
   Brokerage (paper by default; E*TRADE sandbox/production; Chase read-only) → Risk limits → Security (12+ char passcode) → Finish.
   Secrets are encrypted with Electron `safeStorage` (Windows DPAPI / macOS Keychain / libsecret).

## Brokerage integration — what is and isn't possible

| | E*TRADE | Chase / J.P. Morgan Self-Directed |
|---|---|---|
| Access path | Official E*TRADE v1 REST API, OAuth 1.0a | No public developer API; aggregator (Plaid Investments or SnapTrade), OAuth consent |
| Balances, positions, transactions, orders | Yes | Balances, holdings, transactions, dividends (read-only) |
| Order placement | Yes — preview then place, only after human approval | **Not supported** (no authorized trading API) |
| Credentials | Tokens only, encrypted at rest; tokens expire nightly and need renewal | Aggregator access token only |

Verify current API terms, aggregator coverage and pricing for your account types before going live.

## Execution safety model

`PROPOSED → RISK_CHECKED → APPROVED → SUBMITTED`. AI agents (role `agent`) can only propose. Approval requires a human
`trader`/`admin` to type the exact phrase (e.g. `APPROVE BUY 10 AAPL`), after which the broker preview is fetched; submission
must be done by the same approver. Risk gate: max position $ and % of equity, max exposure, daily loss lock, orders/day,
restricted list, read-only connections, and **live trading off by default** (paper broker always available).
Every transition is written to an append-only SHA-256 hash-chained audit log (`GET /audit` verifies the chain).

## Research integrity

* Indicators are causal (unit-tested); backtests decide on bar t−1 and fill at bar t's open.
* ML uses purged `TimeSeriesSplit` (gap = horizon), reports accuracy **against a naive baseline** and adjusts significance
  for overlapping labels; PSI drift and Isolation-Forest anomaly monitoring.
* Warehouse schema keeps delisted securities and filing/vintage dates for point-in-time research.

## Quick start (developer)

```bash
pip install -r requirements.txt
pytest -q                                        # 17 tests
AUTH_DISABLED=true uvicorn backend.app.main:app --port 8000     # API docs: http://127.0.0.1:8000/docs
cd frontend && npm install && npm run dev        # dashboard: http://localhost:3000
```

See `docs/INSTALL.md` for desktop packaging and AWS deployment.

## Status and next steps

Working and tested: quant engine, backtester, ML pipeline, agents, paper trading, order approval flow, API, dashboard build.
Requires your credentials to exercise: E*TRADE (sandbox first), Plaid/SnapTrade for Chase, Polygon, FRED, Anthropic.
Scaffolded for you to complete: Airflow task bodies, database persistence (the API currently keeps proposals in memory and the
audit log in a file), Settings screen for connecting brokers after setup, index-development module UI, options analytics UI.

## Phone app (Android + iPhone)

`mobile/` wraps the same dashboard in a native app with Capacitor. The phone has no analysis engine of its own, so it connects to:

* **Your desktop over home Wi-Fi.** In the Setup Wizard, tick "Allow my phone to connect". Open the desktop's **Pair Phone** tab,
  generate a 6-digit code (single-use, expires in 5 minutes), and enter the address and code in the phone app. Unpair phones from the same tab.
  Traffic on the home network is plain HTTP, so pair only on a network you trust.
* **A cloud server (HTTPS)** once the AWS deployment is running: choose "Sign in to a server" in the app.

Builds: every push to `main` builds `GlobalBLOCS-Quant-<version>-android.apk` (debug-signed, sideload) and an iOS Xcode project
(open in Xcode, set your Apple Developer team, run on your iPhone). Store releases need a release-signing keystore (Google Play)
and an Apple Developer account (App Store/TestFlight). Local builds: `cd mobile && npm ci && npm run android:apk` or `npm run ios:init && npm run open:ios`.
