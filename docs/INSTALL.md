# Installation and Packaging

## A. End user: install the desktop app

1. Install **Python 3.10+** from python.org (Windows: tick "Add python.exe to PATH").
2. Run the installer for your platform:
   * Windows: `GlobalBLOCS-Quant-Setup-1.0.0.exe` → accept license → choose folder → shortcuts → Finish (launches the app).
   * macOS: open the `.dmg`, drag **GlobalBLOCS Quant** to Applications.
   * Linux: `chmod +x GlobalBLOCS*.AppImage && ./GlobalBLOCS*.AppImage`, or `sudo apt install ./globalblocs-quant-desktop_1.0.0_amd64.deb`.
3. The **Setup Wizard** opens on first launch. Follow its nine steps; the engine install takes a few minutes.
4. Afterwards the app starts the local engine on `127.0.0.1:8765` and opens the dashboard. Data, encrypted secrets, the audit
   log and `engine.log` live in the app data folder (Windows `%APPDATA%\GlobalBLOCS Quant`, macOS `~/Library/Application Support/GlobalBLOCS Quant`).
5. To re-run the wizard, delete `config.json` from that folder.

## B. Build the installers

**Easiest (Windows):** install Node.js 20 LTS, unzip the project, and double-click `build-windows-installer.bat`.
About 5–10 minutes later, `desktop\dist\GlobalBLOCS-Quant-Setup-1.0.0.exe` opens in File Explorer. Run it to start the installation wizard.

Manual:

```bash
cd frontend && npm ci && npm run build      # produces frontend/out (bundled into the app)
cd ../desktop && npm install
npm run dist:win     # on Windows  -> desktop/dist/GlobalBLOCS-Quant-Setup-1.0.0.exe (NSIS wizard)
npm run dist:mac     # on macOS    -> .dmg (sign + notarize with your Apple Developer ID for distribution)
npm run dist:linux   # on Linux    -> .AppImage and .deb
```

Code signing: set `CSC_LINK`/`CSC_KEY_PASSWORD` (Windows Authenticode) or `CSC_NAME` + `APPLE_ID`/`APPLE_APP_SPECIFIC_PASSWORD`
(macOS) before running electron-builder. Unsigned Windows installers trigger SmartScreen warnings.
CI (`.github/workflows/ci.yml`) builds all three installers when you push a tag like `v1.0.0`.

## C. Server / Docker

```bash
cp .env.example .env    # fill in keys; generate GB_ENCRYPTION_KEY, JWT_SECRET, ADMIN_PASSWORD_HASH as noted inside
docker compose -f deploy/docker-compose.yml --env-file .env up --build
# API http://localhost:8000/docs   Dashboard http://localhost:3000   TimescaleDB localhost:5432 (schema auto-loaded)
```

## D. AWS

1. Push the backend image to ECR (`deploy/Dockerfile.backend`).
2. Put secrets in Secrets Manager `globalblocs/app` (keys listed in `deploy/aws/main.tf`).
3. `cd deploy/aws && terraform init && terraform apply -var vpc_id=... -var 'private_subnets=["..."]' -var api_image=...`
4. Add the ALB/ECS service and CloudFront distribution for your network, then upload `frontend/out` to the web bucket.

## E. Connecting brokerages

* **E*TRADE:** request a consumer key at E*TRADE's developer portal. Start in sandbox. The OAuth flow
  (`brokerage/etrade.py: ETradeAuth.start/finish`) opens E*TRADE's authorization page and you paste back the verifier code.
  Trading permission stays off until you enable it; live trading also requires `LIVE_TRADING_ENABLED=true`.
* **Chase:** create a Plaid account with Investments enabled (or SnapTrade), complete Plaid Link for your Chase account, and
  store the resulting access token. The connection is read-only by design.
