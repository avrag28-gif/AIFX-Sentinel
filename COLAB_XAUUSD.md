# AIFX Sentinel — XAUUSD Hybrid AI Ensemble (Google Colab)

## Direct Google Colab
Open this notebook directly:
https://colab.research.google.com/github/avrag28-gif/AIFX-Sentinel/blob/feature/xauusd-colab-pipeline/notebooks/AIFX_XAUUSD_Hybrid_Ensemble.ipynb

## What it does
- Colab T4 GPU setup and Google Drive mount
- Downloads XAUUSD M1 BID and ASK via the third-party dukascopy-node CLI (Dukascopy public feed)
- Builds BID/ASK quote dataset, approximate MID OHLC, and M5 candles
- Chronological splits: train 2015-2020, validation 2021-2023, final test 2024-2026-11-13 (UTC)
- Trains XGBoost, LSTM and Transformer models
- Fits a probabilistic meta ensemble for DOWN / FLAT / UP
- Reports accuracy, balanced accuracy, log loss, multiclass Brier score, confusion matrix
- Runs a baseline BID/ASK backtest and saves artifacts

## Important
The notebook and code are hosted in GitHub; the large historical market dataset is downloaded at runtime from Dukascopy, not stored in GitHub. This avoids committing multi-gigabyte market files and keeps the raw quote provenance clear. Dukascopy-node is a third-party downloader, not official Dukascopy software.

MID candle OHLC is an approximation formed by averaging BID and ASK candle OHLC. Backtest entries/exits use side-specific quotes: BUY enters ASK/exits BID; SELL enters BID/exits ASK. The baseline does not yet model commissions, swaps, dynamic slippage, intrabar SL/TP or broker-specific contract sizing. Research only; no live trading and no profit guarantee.

Run: choose Runtime > Change runtime type > T4 GPU, then run cells from top to bottom.
