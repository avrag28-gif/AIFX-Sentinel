# AIFX Sentinel V4

Local-first SMC market-data and signal-review system for TradingView + FastAPI + SQLite.

## Features
- Pine Script v6 detects BOS/CHoCH, FVG, heuristic order blocks, liquidity sweeps, EQH/EQL, premium/discount, EMA, MACD, RSI and ADX.
- Flexible BUY/SELL candidate signals use a configurable score threshold (default 3/6) and cooldown. Candidates are not trading approvals.
- TradingView sends closed candles and candidate direction to the FastAPI webhook.
- Backend stores candles/signals in SQLite and automatically requests AI review when a candidate arrives and AI credentials are configured.
- AI decision: VALID, REJECT or WAIT, with rationale, risks and invalidation.
- Dashboard, signal history, simple close-to-close outcome evaluation, CSV/JSON export.
- No broker integration and no order execution.

## Windows setup
1. Install Python 3.11 or newer.
2. Clone this repository.
3. Copy `.env.example` to `.env`.
4. Set a long random `AIFX_WEBHOOK_TOKEN`. Set `AI_API_KEY`, `AI_BASE_URL` and `AI_MODEL` if AI review is wanted.
5. Run `run_local.bat`; dashboard: http://127.0.0.1:8000.
6. Open `pine/aifx_sentinel_v4_flexible_ai_review.pine` in TradingView Pine Editor and add it to a chart.
7. Create an alert with condition **Any alert() function call**. Set webhook URL to `https://YOUR_TUNNEL/webhook?token=YOUR_TOKEN`. TradingView cannot reach localhost directly; use a secured HTTPS tunnel.

## API
- `GET /health`
- `POST /webhook?token=...`
- `GET /api/summary`
- `GET /api/candles?symbol=EURUSD&timeframe=5`
- `GET /api/signals?symbol=EURUSD&timeframe=5`
- `GET /api/performance?symbol=EURUSD&timeframe=5`
- `GET /api/score?symbol=EURUSD&timeframe=5`
- `GET /export/csv?symbol=EURUSD&timeframe=5`
- `GET /export/json?symbol=EURUSD&timeframe=5`

## Signal logic and limitations
The Pine candidate engine counts six lightweight factors: EMA20/EMA50 alignment, close vs EMA20, MACD histogram, RSI vs 50, candle direction, and an SMC event. Default threshold is 3/6. Lower thresholds create more candidates but also more false positives. Cooldown limits repeated same-direction labels.

AI reviews supplied market data only. AI confidence is subjective and is not a calibrated win probability. VALID means the candidate passed a technical review for paper-trading consideration only. It is not a guarantee of profit.

Performance is a basic close-to-close directional hit rate after the configured number of subsequent candles. It excludes spread, commissions, slippage, swaps, position sizing, stop-loss, take-profit and realistic fills. It is not a proper backtest.

## Security
- Never commit `.env`, API keys, webhook tokens, SQLite databases or personal account data.
- Keep the dashboard local or add authentication before exposing it publicly.
- Protect the webhook with a strong random token and HTTPS.
- Keep live trading disabled; this repository does not send broker orders.

## Validation
Run `python -m unittest discover -s tests -v`. Pine Script must still be compiled and tested in TradingView before use.
