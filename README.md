# AIFX Sentinel

Local-first SMC signal research system for TradingView + FastAPI + SQLite.

## Current package

The initial source package is being added in this repository. It generates flexible BUY/SELL candidate signals in Pine Script and sends closed-candle data to a local FastAPI webhook. When configured, an OpenAI-compatible AI reviewer evaluates candidates and returns VALID, REJECT, or WAIT. AI confidence is a qualitative score, not a win probability.

## Safety

This project does not execute broker orders. `VALID` means accepted for paper-trading consideration only. It is not a guarantee of profit. Test the Pine Script in TradingView and verify webhook/API configuration before relying on signals.

## Setup

1. Install Python 3.11+.
2. Copy `.env.example` to `.env` and configure a strong webhook token. Configure AI API settings if desired.
3. Run `run_local.bat` on Windows, then open http://127.0.0.1:8000.
4. Add the Pine Script from `pine/` to TradingView and create an alert using `Any alert() function call`.
5. Expose the local webhook through a secured HTTPS tunnel if TradingView needs to reach it.

See the project README in the source package for detailed setup and endpoints.
