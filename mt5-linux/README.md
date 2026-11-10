# AIFX Sentinel — Linux Docker MT5 telemetry bridge

This adds **telemetry-only** MT5 connectivity to the existing FastAPI/SQLite AIFX Sentinel project. It does not place, modify, or close broker orders. It does not use the official MetaTrader5 Python package: that package is Windows-oriented. The MT5 terminal runs under Wine + Xvfb, and an MQL5 Expert Advisor posts closed candles and heartbeats to the Linux FastAPI service over Docker's private network.

## Important platform limitation

This is a compatibility deployment, not a vendor-supported native Linux/headless MT5 server. MT5 is a Windows desktop terminal running under Wine and a virtual X server. First-time broker login, terminal setup, WebRequest allow-listing, and EA attachment may require an interactive session. Validate your broker's MT5 build under Wine before relying on it. A container restart restarts the process, but does not guarantee broker reconnection or data continuity.

## 1. Configure

From this directory:

```bash
cp .env.example .env
openssl rand -hex 32
```

Put the generated value in `AIFX_BRIDGE_TOKEN`. Set `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` and a broker installer URL in `MT5_INSTALLER_URL`, or mount a prepared MT5 terminal installation into the `mt5-data` volume at `/opt/mt5`. Do not commit `.env`.

The included installer bootstrap uses the MT5 setup executable's unattended option; installer behavior can vary by broker. For a broker-branded terminal, prepare the installation in a persistent volume if unattended installation does not work.

## 2. Build and start

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f sentinel-api mt5-terminal
```

API is bound to localhost only: `http://127.0.0.1:8000`. Keep it behind an authenticated reverse proxy/VPN if remote access is required. Never expose the unauthenticated read endpoints directly to the public internet.

## 3. Install and configure the EA

Compile `ea/AIFX_MarketBridge.mq5` in MetaEditor to produce `AIFX_MarketBridge.ex5`. Copy it to the terminal's `MQL5/Experts` directory in the persistent MT5 data volume, then attach it to an EURUSD chart. Set:
- API base: `http://sentinel-api:8000`
- Bridge token: same value as `AIFX_BRIDGE_TOKEN`
- Symbol/timeframe: broker's exact symbol (e.g. EURUSD or EURUSD.a), M5 initially.

In MT5, add `http://sentinel-api:8000` to Tools → Options → Expert Advisors → Allow WebRequest for listed URL. Enable Algo Trading for the telemetry EA. **Do not enable live trading**. The EA has no order execution code. If using an existing MT5 data directory, ensure the EA is attached and its inputs are saved in the chart profile.

## 4. Verify

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS 'http://127.0.0.1:8000/v1/latest?symbol=EURUSD&timeframe=M5&limit=5'
curl -fsS http://127.0.0.1:8000/metrics
docker compose ps
docker compose logs --tail=100 mt5-terminal
```

A successful heartbeat reports `terminal_connected: true`; candle count should increase as closed M5 candles arrive. The terminal healthcheck only verifies that the process exists, not that the broker is logged in. Use `/metrics` for the latter.

## 5. Tests

```bash
cd api
python -m pip install -r requirements.txt
python -m pip install httpx
python -m unittest -v test_app.py
```

## Operational notes

- Docker restart policy is `unless-stopped`; SQLite persists in `sentinel-data`.
- MT5 files persist in `mt5-data`. Back up both volumes.
- Keep Docker, the host, Wine, and the broker terminal patched.
- Use a dedicated demo/cent account during validation.
- The API token protects writes. Add authentication/rate limiting before exposing read endpoints.
- This bridge only transports telemetry. AIFX signal scoring/AI review integration is a separate adapter and is not wired to order execution.
- No live trading, order submission, SL/TP modification, or position management is implemented.
