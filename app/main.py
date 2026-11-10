from __future__ import annotations
import csv, io, json, os, sqlite3, time
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ConfigDict

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DB = Path(os.getenv("AIFX_DB_PATH", str(ROOT / "data" / "aifx_sentinel.db")))
DB.parent.mkdir(parents=True, exist_ok=True)
HOOK = os.getenv("AIFX_WEBHOOK_TOKEN", "")
DASH = os.getenv("AIFX_DASHBOARD_TOKEN", "")
AI_KEY = os.getenv("AI_API_KEY", "")
AI_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4.1-mini")
HORIZON = int(os.getenv("SIGNAL_EVAL_HORIZON", "10"))
app = FastAPI(title="AIFX Sentinel", version="4.0.0", description="SMC candidate signals with AI review. Broker execution is disabled.")

class Candle(BaseModel):
    model_config = ConfigDict(extra="allow")
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    ema20: float | None = None
    ema50: float | None = None
    ema100: float | None = None
    ema200: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    rsi: float | None = None
    atr: float | None = None
    adx: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None
    events: dict[str, Any] = Field(default_factory=dict)

class Batch(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str = Field(min_length=1, max_length=80)
    market: str = "unknown"
    timeframe: str
    candles: list[Candle] = Field(min_length=1, max_length=200)

def db():
    c = sqlite3.connect(DB, timeout=20); c.row_factory = sqlite3.Row; return c

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS candles(symbol TEXT,timeframe TEXT,market TEXT,t INTEGER,open REAL,high REAL,low REAL,close REAL,volume REAL,ind TEXT,events TEXT,PRIMARY KEY(symbol,timeframe,t));
        CREATE TABLE IF NOT EXISTS signals(symbol TEXT,timeframe TEXT,t INTEGER,direction TEXT,bull INTEGER,bear INTEGER,entry REAL,ai_decision TEXT,ai_confidence INTEGER,ai_rationale TEXT,outcome TEXT,exit REAL,created INTEGER,PRIMARY KEY(symbol,timeframe,t));
        CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY,symbol TEXT,timeframe TEXT,count INTEGER,received INTEGER);
        """)
init()

def auth(token):
    if DASH and token != DASH: raise HTTPException(401, "Invalid dashboard token")

def score(c: Candle):
    e=c.events or {}; bull=bear=0; br=[]; sr=[]
    def add_b(flag, pts, reason):
        nonlocal bull
        if flag: bull+=pts; br.append(reason)
    def add_s(flag, pts, reason):
        nonlocal bear
        if flag: bear+=pts; sr.append(reason)
    add_b(e.get("structure") in ("HH_HL","BULLISH"),20,"bullish structure")
    add_s(e.get("structure") in ("LH_LL","BEARISH"),20,"bearish structure")
    add_b(e.get("bull_bos") or e.get("bull_choch"),15,"bullish BOS/CHoCH")
    add_s(e.get("bear_bos") or e.get("bear_choch"),15,"bearish BOS/CHoCH")
    add_b(e.get("bull_fvg") and not e.get("bull_fvg_mitigated"),15,"active bullish FVG")
    add_s(e.get("bear_fvg") and not e.get("bear_fvg_mitigated"),15,"active bearish FVG")
    add_b(e.get("bull_ob") and not e.get("bull_ob_invalidated"),15,"bullish order block")
    add_s(e.get("bear_ob") and not e.get("bear_ob_invalidated"),15,"bearish order block")
    add_b(e.get("sweep_low"),10,"sell-side sweep")
    add_s(e.get("sweep_high"),10,"buy-side sweep")
    if c.ema20 is not None and c.ema50 is not None:
        add_b(c.close>c.ema20>c.ema50,10,"EMA bullish")
        add_s(c.close<c.ema20<c.ema50,10,"EMA bearish")
    if c.macd is not None and c.macd_signal is not None:
        add_b(c.macd>c.macd_signal,5,"MACD bullish")
        add_s(c.macd<c.macd_signal,5,"MACD bearish")
    if c.rsi is not None:
        add_b(50<c.rsi<70,5,"RSI bullish")
        add_s(30<c.rsi<50,5,"RSI bearish")
    if c.adx is not None and c.adx>=20 and c.plus_di is not None and c.minus_di is not None:
        add_b(c.plus_di>c.minus_di,5,"ADX positive DI")
        add_s(c.minus_di>c.plus_di,5,"ADX negative DI")
    if e.get("premium_discount")=="discount" and bull>bear: bull+=5
    if e.get("premium_discount")=="premium" and bear>bull: bear+=5
    candidate=str(e.get("candidate_direction","NONE")).upper()
    direction=candidate if candidate in ("BUY","SELL") else ("BUY" if bull>=70 and bull-bear>=15 else "SELL" if bear>=70 and bear-bull>=15 else "WAIT")
    return {"direction":direction,"bull_score":min(100,bull),"bear_score":min(100,bear),"bull_reasons":br,"bear_reasons":sr,
            "candidate_direction":candidate,"candidate_bull_score":e.get("candidate_bull_score"),"candidate_bear_score":e.get("candidate_bear_score")}

async def ai_review(symbol,tf,t):
    if not AI_KEY: return {"status":"AI_NOT_CONFIGURED"}
    with db() as c:
        rows=c.execute("SELECT * FROM candles WHERE symbol=? AND timeframe=? AND t<=? ORDER BY t DESC LIMIT 30",(symbol,tf,t)).fetchall()
    if not rows: return None
    r=rows[0]; ind=json.loads(r["ind"]); ev=json.loads(r["events"])
    candle=Candle(time=r["t"],open=r["open"],high=r["high"],low=r["low"],close=r["close"],volume=r["volume"],events=ev,**ind)
    sc=score(candle)
    if sc["direction"] not in ("BUY","SELL"): return {"status":"NO_CANDIDATE"}
    recent=[{"time":x["t"],"ohlc":[x["open"],x["high"],x["low"],x["close"]],"indicators":json.loads(x["ind"]),"events":json.loads(x["events"])} for x in reversed(rows)]
    system=("Review this technical trading candidate using only supplied OHLC, indicators and SMC events. "
            "Return JSON with decision VALID, REJECT, or WAIT; confidence integer 0-100; rationale; risks array; invalidation. "
            "VALID only if direction is technically coherent; REJECT if contradicted; WAIT if mixed. Never invent data. "
            "Confidence is not win probability. No order execution.")
    body={"model":AI_MODEL,"temperature":0.1,"response_format":{"type":"json_object"},"messages":[
        {"role":"system","content":system},{"role":"user","content":json.dumps({"symbol":symbol,"timeframe":tf,"candidate":sc,"recent_candles":recent})}]}
    async with httpx.AsyncClient(timeout=45) as client:
        res=await client.post(AI_URL+"/chat/completions",headers={"Authorization":"Bearer "+AI_KEY},json=body)
    res.raise_for_status()
    data=json.loads(res.json()["choices"][0]["message"]["content"])
    decision=str(data.get("decision","WAIT")).upper()
    if decision not in ("VALID","REJECT","WAIT"): decision="WAIT"
    conf=max(0,min(100,int(data.get("confidence",0))))
    rationale=str(data.get("rationale",""))[:3000]
    with db() as c:
        c.execute("UPDATE signals SET ai_decision=?,ai_confidence=?,ai_rationale=? WHERE symbol=? AND timeframe=? AND t=?",
                  (decision,conf,rationale,symbol,tf,t))
    return {"ai_decision":decision,"ai_confidence":conf,"rationale":rationale,"risks":data.get("risks",[]),"invalidation":data.get("invalidation","")}

@app.get("/health")
def health(): return {"status":"ok","service":"AIFX Sentinel","ai_configured":bool(AI_KEY),"execution":"disabled"}

@app.post("/webhook")
async def webhook(payload: Batch, token: str=Query(default="")):
    if not HOOK or token!=HOOK: raise HTTPException(401,"Invalid webhook token")
    sym=payload.symbol.strip().upper(); tf=payload.timeframe
    candles=sorted(payload.candles,key=lambda x:x.time)
    with db() as c:
        for x in candles:
            if x.high<max(x.open,x.close,x.low) or x.low>min(x.open,x.close,x.high) or x.volume<0: raise HTTPException(422,"Invalid OHLCV")
            ind=x.model_dump(exclude={"time","open","high","low","close","volume","events"})
            c.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,timeframe,t) DO UPDATE SET market=excluded.market,open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,ind=excluded.ind,events=excluded.events",
                (sym,tf,payload.market,x.time,x.open,x.high,x.low,x.close,x.volume,json.dumps(ind),json.dumps(x.events)))
            s=score(x)
            c.execute("INSERT INTO signals(symbol,timeframe,t,direction,bull,bear,entry,created) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(symbol,timeframe,t) DO UPDATE SET direction=excluded.direction,bull=excluded.bull,bear=excluded.bear,entry=excluded.entry",
                (sym,tf,x.time,s["direction"],s["bull_score"],s["bear_score"],x.close,int(time.time())))
        c.execute("INSERT INTO batches(symbol,timeframe,count,received) VALUES(?,?,?,?)",(sym,tf,len(candles),int(time.time())))
        # Evaluate simple future-close directional outcome after N subsequent candles.
        sigs=c.execute("SELECT t,direction,entry FROM signals WHERE symbol=? AND timeframe=? AND outcome IS NULL AND direction IN ('BUY','SELL')",(sym,tf)).fetchall()
        for sig in sigs:
            fut=c.execute("SELECT close FROM candles WHERE symbol=? AND timeframe=? AND t>? ORDER BY t LIMIT ?",(sym,tf,sig["t"],HORIZON)).fetchall()
            if len(fut)>=HORIZON:
                end=fut[-1]["close"]; won=end>sig["entry"] if sig["direction"]=="BUY" else end<sig["entry"]
                c.execute("UPDATE signals SET outcome=?,exit=? WHERE symbol=? AND timeframe=? AND t=?",("WIN" if won else "LOSS",end,sym,tf,sig["t"]))
    review=None
    try: review=await ai_review(sym,tf,candles[-1].time)
    except Exception as ex: review={"status":"AI_REVIEW_ERROR","error":type(ex).__name__}
    return {"accepted":True,"received":len(candles),"signal":score(candles[-1]),"ai_review":review,"execution":"disabled"}

@app.get("/api/summary")
def summary(token:str|None=None):
    auth(token)
    with db() as c:
        series=[dict(x) for x in c.execute("SELECT symbol,market,timeframe,COUNT(*) candles,MAX(t) latest FROM candles GROUP BY symbol,market,timeframe")]
        n=c.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        ns=c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    return {"total_candles":n,"total_signals":ns,"series":series}

@app.get("/api/candles")
def get_candles(symbol:str,timeframe:str,limit:int=Query(200,ge=1,le=200),token:str|None=None):
    auth(token)
    with db() as c: rows=c.execute("SELECT * FROM candles WHERE symbol=? AND timeframe=? ORDER BY t DESC LIMIT ?",(symbol.upper(),timeframe,limit)).fetchall()
    return {"candles":[dict(x) for x in reversed(rows)]}

@app.get("/api/signals")
def get_signals(symbol:str|None=None,timeframe:str|None=None,limit:int=100,token:str|None=None):
    auth(token); q="SELECT * FROM signals WHERE 1=1"; a=[]
    if symbol: q+=" AND symbol=?"; a.append(symbol.upper())
    if timeframe: q+=" AND timeframe=?"; a.append(timeframe)
    q+=" ORDER BY t DESC LIMIT ?"; a.append(max(1,min(1000,limit)))
    with db() as c: rows=c.execute(q,a).fetchall()
    return {"signals":[dict(x) for x in rows]}

@app.get("/api/performance")
def performance(symbol:str|None=None,timeframe:str|None=None,token:str|None=None):
    auth(token); q="SELECT outcome,COUNT(*) n FROM signals WHERE direction IN ('BUY','SELL')"; a=[]
    if symbol: q+=" AND symbol=?"; a.append(symbol.upper())
    if timeframe: q+=" AND timeframe=?"; a.append(timeframe)
    q+=" GROUP BY outcome"
    with db() as c: rows=c.execute(q,a).fetchall()
    d={x["outcome"] or "PENDING":x["n"] for x in rows}; w=d.get("WIN",0); l=d.get("LOSS",0)
    return {"wins":w,"losses":l,"pending":d.get("PENDING",0),"accuracy_pct":round(w/(w+l)*100,2) if w+l else None,"warning":"Directional hit rate only; excludes trading costs."}

@app.get("/api/score")
async def score_latest(symbol:str,timeframe:str,token:str|None=None):
    auth(token)
    with db() as c: r=c.execute("SELECT t FROM candles WHERE symbol=? AND timeframe=? ORDER BY t DESC LIMIT 1",(symbol.upper(),timeframe)).fetchone()
    if not r: raise HTTPException(404,"No candles")
    return await ai_review(symbol.upper(),timeframe,r["t"])

@app.get("/export/json")
def export_json(symbol:str|None=None,timeframe:str|None=None,limit:int=200,token:str|None=None):
    auth(token); q="SELECT * FROM candles WHERE 1=1"; a=[]
    if symbol: q+=" AND symbol=?"; a.append(symbol.upper())
    if timeframe: q+=" AND timeframe=?"; a.append(timeframe)
    q+=" ORDER BY t DESC LIMIT ?"; a.append(max(1,min(50000,limit)))
    with db() as c: rows=[dict(x) for x in c.execute(q,a).fetchall()]
    return JSONResponse({"candles":rows})

@app.get("/export/csv")
def export_csv(symbol:str|None=None,timeframe:str|None=None,limit:int=200,token:str|None=None):
    auth(token); q="SELECT * FROM candles WHERE 1=1"; a=[]
    if symbol: q+=" AND symbol=?"; a.append(symbol.upper())
    if timeframe: q+=" AND timeframe=?"; a.append(timeframe)
    q+=" ORDER BY t DESC LIMIT ?"; a.append(max(1,min(50000,limit)))
    with db() as c: rows=c.execute(q,a).fetchall()
    out=io.StringIO(); w=csv.writer(out); w.writerow(["symbol","market","timeframe","time","open","high","low","close","volume","indicators_json","events_json"])
    for r in rows: w.writerow(list(r))
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=aifx_export.csv"})

@app.get("/",response_class=HTMLResponse)
def dashboard():
    p=ROOT/"app"/"index.html"
    return p.read_text() if p.exists() else "<h1>AIFX Sentinel API is running</h1><p>Use /docs for API endpoints.</p>"
