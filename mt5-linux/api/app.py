import json
import os
import sqlite3
import time
from contextlib import contextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

DB_PATH = os.getenv("DB_PATH", "/data/bridge.sqlite3")
TOKEN = os.getenv("AIFX_BRIDGE_TOKEN", "")
app = FastAPI(title="AIFX Sentinel MT5 Bridge", version="0.1.0")

class Candle(BaseModel):
    symbol: str = Field(min_length=3, max_length=20)
    timeframe: str = Field(min_length=2, max_length=5)
    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread: int = 0
    source: str = "mt5-ea"

class Heartbeat(BaseModel):
    terminal: str = "MetaTrader 5"
    account_login: str = ""
    server: str = ""
    connected: bool = False
    note: str = ""

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

@app.on_event("startup")
def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS candles (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
          candle_time INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL,
          tick_volume INTEGER, spread INTEGER, source TEXT,
          UNIQUE(symbol,timeframe,candle_time))""")
        con.execute("""CREATE TABLE IF NOT EXISTS heartbeats (
          id INTEGER PRIMARY KEY, received_at INTEGER NOT NULL, terminal TEXT,
          account_login TEXT, server TEXT, connected INTEGER, note TEXT)""")

def authorize(token: str | None):
    if not TOKEN or len(TOKEN) < 32:
        raise HTTPException(503, "Bridge token is not configured (minimum 32 characters)")
    if token != TOKEN:
        raise HTTPException(401, "Invalid bridge token")

@app.get("/health")
def health():
    with db() as con:
        con.execute("SELECT 1")
    return {"status": "ok", "service": "aifx-mt5-bridge", "execution": "disabled"}

@app.post("/v1/heartbeat")
def heartbeat(payload: Heartbeat, x_aifx_token: str | None = Header(default=None)):
    authorize(x_aifx_token)
    with db() as con:
        con.execute("INSERT INTO heartbeats(received_at,terminal,account_login,server,connected,note) VALUES(?,?,?,?,?,?)",
                    (int(time.time()), payload.terminal, payload.account_login, payload.server, int(payload.connected), payload.note[:240]))
    return {"accepted": True}

@app.post("/v1/candle")
def candle(payload: Candle, x_aifx_token: str | None = Header(default=None)):
    authorize(x_aifx_token)
    if payload.high < max(payload.open, payload.close, payload.low) or payload.low > min(payload.open, payload.close, payload.high):
        raise HTTPException(422, "Invalid OHLC range")
    with db() as con:
        con.execute("""INSERT INTO candles(symbol,timeframe,candle_time,open,high,low,close,tick_volume,spread,source)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,timeframe,candle_time) DO UPDATE SET
          open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
          tick_volume=excluded.tick_volume,spread=excluded.spread,source=excluded.source""",
          (payload.symbol.upper(),payload.timeframe.upper(),payload.time,payload.open,payload.high,payload.low,payload.close,payload.tick_volume,payload.spread,payload.source))
    return {"accepted": True, "execution": "disabled"}

@app.get("/v1/latest")
def latest(symbol: str = "EURUSD", timeframe: str = "M5", limit: int = 100):
    limit = max(1, min(limit, 500))
    with db() as con:
        rows = con.execute("SELECT * FROM candles WHERE symbol=? AND timeframe=? ORDER BY candle_time DESC LIMIT ?",
                           (symbol.upper(), timeframe.upper(), limit)).fetchall()
        hb = con.execute("SELECT * FROM heartbeats ORDER BY id DESC LIMIT 1").fetchone()
    return {"candles": [dict(r) for r in reversed(rows)], "last_heartbeat": dict(hb) if hb else None,
            "execution": "disabled"}

@app.get("/metrics")
def metrics():
    with db() as con:
        count = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        hb = con.execute("SELECT received_at,connected FROM heartbeats ORDER BY id DESC LIMIT 1").fetchone()
    age = int(time.time()) - hb["received_at"] if hb else None
    return {"candles_total": count, "heartbeat_age_seconds": age,
            "terminal_connected": bool(hb["connected"]) if hb else False,
            "execution_enabled": False}

@app.get("/v1/status")
def status():
    return metrics()
