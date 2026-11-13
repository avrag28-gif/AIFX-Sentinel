#!/usr/bin/env python3
"""AIFX XAUUSD research pipeline: Dukascopy BID/ASK -> M1/M5 -> hybrid ensemble -> evaluation/backtest."""
import os, sys, subprocess, json, random, copy, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

ROOT = Path(os.environ.get("AIFX_HOME", "/content/AIFX_XAUUSD"))
RAW, OUT, ART = ROOT/"data/raw", ROOT/"data/processed", ROOT/"artifacts"
for p in (RAW, OUT, ART): p.mkdir(parents=True, exist_ok=True)
SEED = 42
random.seed(SEED); np.random.seed(SEED)

def download(side, start, end, name):
    cmd = ["npx","--yes","dukascopy-node","-i","xauusd","-from",start,"-to",end,
           "-t","m1","-p",side,"-f","csv","-v","-dir",str(RAW),"-fn",name,
           "--cache","--retries","5","--batch-pause","1500","--rate-limit-retries","5"]
    print("RUN", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

def load_side(side, start, end):
    fs = sorted(RAW.glob(f"*{side}*.csv"))
    if not fs: raise FileNotFoundError(f"Missing {side} CSVs in {RAW}")
    parts=[]
    for f in fs:
        d=pd.read_csv(f)
        if "timestamp" not in d: raise ValueError(f"No timestamp column in {f}")
        d["time"]=pd.to_datetime(d["timestamp"],unit="ms",utc=True)
        cols=["open","high","low","close"]
        if not set(cols).issubset(d.columns): raise ValueError(f"Missing OHLC in {f}")
        parts.append(d[["time"]+cols])
    z=pd.concat(parts,ignore_index=True).drop_duplicates("time").sort_values("time").set_index("time")
    z=z.loc[(z.index>=pd.Timestamp(start,tz="UTC"))&(z.index<pd.Timestamp(end,tz="UTC"))]
    return z.rename(columns={c:f"{c}_{side}" for c in ["open","high","low","close"]})

def prepare_data():
    periods={"train_2015_2020":("2015-01-01","2021-01-01"),
             "validation_2021_2023":("2021-01-01","2024-01-01"),
             "test_2024_2026":("2024-01-01","2026-11-14")}
    for side in ("bid","ask"):
        for name,(start,end) in [("train_2015_2020",periods["train_2015_2020"]),
                                 ("eval_2021_2026",("2021-01-01","2026-11-14"))]:
            download(side,start,end,f"xauusd_m1_{side}_{name}")
    bid=load_side("bid","2015-01-01","2026-11-14")
    ask=load_side("ask","2015-01-01","2026-11-14")
    q=bid.join(ask,how="inner").dropna().sort_index().reset_index()
    for c in ("open","high","low","close"):
        q[f"{c}_mid"]=(q[f"{c}_bid"]+q[f"{c}_ask"])/2
    q["spread_open"]=q.open_ask-q.open_bid
    q["spread_close"]=q.close_ask-q.close_bid
    mid=q[["time","open_mid","high_mid","low_mid","close_mid","spread_close"]].rename(
        columns={"open_mid":"open","high_mid":"high","low_mid":"low","close_mid":"close","spread_close":"spread"})
    m5=(mid.set_index("time").resample("5min",label="right",closed="left")
        .agg({"open":"first","high":"max","low":"min","close":"last","spread":"mean"}).dropna().reset_index())
    audit=[]
    for name,(start,end) in periods.items():
        mask=(q.time>=pd.Timestamp(start,tz="UTC"))&(q.time<pd.Timestamp(end,tz="UTC"))
        mm=(mid.time>=pd.Timestamp(start,tz="UTC"))&(mid.time<pd.Timestamp(end,tz="UTC"))
        m5m=(m5.time>=pd.Timestamp(start,tz="UTC"))&(m5.time<pd.Timestamp(end,tz="UTC"))
        q.loc[mask].to_csv(OUT/f"xauusd_m1_bid_ask_{name}.csv",index=False)
        mid.loc[mm].to_csv(OUT/f"xauusd_m1_mid_{name}.csv",index=False)
        m5.loc[m5m].to_csv(OUT/f"xauusd_m5_mid_{name}.csv",index=False)
        audit.append({"split":name,"m1_rows":int(mask.sum()),"m5_rows":int(m5m.sum()),
                      "first_utc":str(q.loc[mask,"time"].min()),"last_utc":str(q.loc[mask,"time"].max()),
                      "mean_spread":float(q.loc[mask,"spread_close"].mean()) if mask.any() else None})
    pd.DataFrame(audit).to_csv(OUT/"dataset_audit.csv",index=False)
    q.to_csv(RAW/"xauusd_m1_bid_ask_joined.csv",index=False)
    print(pd.DataFrame(audit).to_string(index=False))
    return periods

def indicators(d,prefix=""):
    x=d.copy(); c=x.close.astype(float); h=x.high.astype(float); l=x.low.astype(float); r=c.pct_change()
    x[prefix+"ret_1"]=r
    for n in (3,5,10,15,30,60):
        x[prefix+f"ret_{n}"]=c.pct_change(n)
        x[prefix+f"vol_{n}"]=r.rolling(n).std()
        x[prefix+f"ema_gap_{n}"]=c/c.ewm(span=n,adjust=False).mean()-1
    for n in (7,14,28):
        delta=c.diff(); gain=delta.clip(lower=0).rolling(n).mean(); loss=(-delta.clip(upper=0)).rolling(n).mean()
        x[prefix+f"rsi_{n}"]=100-100/(1+gain/loss.replace(0,np.nan))
        tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        x[prefix+f"atr_{n}"]=tr.rolling(n).mean()
    x[prefix+"range_pct"]=(h-l)/c.replace(0,np.nan)
    x[prefix+"body_pct"]=(c-x.open)/x.open.replace(0,np.nan)
    x[prefix+"close_location"]=(c-l)/(h-l).replace(0,np.nan)
    x[prefix+"hour_sin"]=np.sin(2*np.pi*x.time.dt.hour/24)
    x[prefix+"hour_cos"]=np.cos(2*np.pi*x.time.dt.hour/24)
    x[prefix+"dow"]=x.time.dt.dayofweek
    return x

def make_features(q,m5):
    m1=q[["time","open_mid","high_mid","low_mid","close_mid","spread_close"]].rename(
        columns={"open_mid":"open","high_mid":"high","low_mid":"low","close_mid":"close","spread_close":"spread"})
    a=indicators(m1)
    b=indicators(m5[["time","open","high","low","close"]].copy(),"m5_")
    cols=["time"]+[c for c in b if c.startswith("m5_")]
    a=pd.merge_asof(a.sort_values("time"),b[cols].sort_values("time"),on="time",direction="backward")
    a["spread_pct"]=a.spread/a.close
    return a

def add_target(d,horizon=15,flat=0.0003):
    z=d.copy()
    # M1 timestamps represent candle start; use close at start-time + horizon.
    lookup=pd.Series(z.close.to_numpy(),index=z.time)
    fut=lookup.reindex(z.time+pd.Timedelta(minutes=horizon)).to_numpy()
    z["future_return"]=fut/z.close.to_numpy()-1
    z["target"]=np.select([z.future_return < -flat,z.future_return > flat],[0,2],default=1)
    return z.dropna(subset=["future_return"]).reset_index(drop=True)

def train_all():
    import torch
    from torch import nn
    from torch.utils.data import Dataset,DataLoader
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score,balanced_accuracy_score,log_loss,confusion_matrix,classification_report
    from sklearn.linear_model import LogisticRegression
    from xgboost import XGBClassifier
    import joblib
    torch.manual_seed(SEED)
    device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    def read(split,tf):
        return pd.read_csv(OUT/f"xauusd_{tf}_{split}.csv",parse_dates=["time"])
    qtr,qva,qte=[read(s,"m1_bid_ask") for s in ("train_2015_2020","validation_2021_2023","test_2024_2026")]
    mtr,mva,mte=[read(s,"m5_mid") for s in ("train_2015_2020","validation_2021_2023","test_2024_2026")]
    fs=[add_target(make_features(q,m)) for q,m in ((qtr,mtr),(qva,mva),(qte,mte))]
    tr,va,te=fs
    excluded={"time","open","high","low","close","spread","future_return","target"}
    features=[c for c in tr if c not in excluded and pd.api.types.is_numeric_dtype(tr[c]) and tr[c].notna().any()]
    imp=SimpleImputer(strategy="median"); scl=StandardScaler()
    Xtri=imp.fit_transform(tr[features]); Xvai=imp.transform(va[features]); Xtei=imp.transform(te[features])
    Xtr=scl.fit_transform(Xtri).astype("float32"); Xva=scl.transform(Xvai).astype("float32"); Xte=scl.transform(Xtei).astype("float32")
    ytr,yva,yte=[d.target.to_numpy(dtype=np.int64) for d in (tr,va,te)]
    joblib.dump({"features":features,"imputer":imp,"scaler":scl},ART/"preprocessor.joblib")
    xgb=XGBClassifier(n_estimators=500,max_depth=6,learning_rate=.04,subsample=.85,colsample_bytree=.85,
        min_child_weight=5,reg_lambda=2,objective="multi:softprob",num_class=3,eval_metric="mlogloss",
        tree_method="hist",device="cuda" if torch.cuda.is_available() else "cpu",random_state=SEED,n_jobs=4)
    xgb.fit(Xtri,ytr,eval_set=[(Xvai,yva)],verbose=100)
    pxv,pxte=xgb.predict_proba(Xvai),xgb.predict_proba(Xtei); joblib.dump(xgb,ART/"xgboost.joblib")
    class SeqDS(Dataset):
        def __init__(self,X,y):
            self.X=torch.tensor(X); self.y=torch.tensor(y); self.ends=np.arange(59,len(X),10)
        def __len__(self): return len(self.ends)
        def __getitem__(self,i):
            e=self.ends[i]; return self.X[e-59:e+1],self.y[e],int(e)
    def loader(X,y,shuffle=False): return DataLoader(SeqDS(X,y),batch_size=512,shuffle=shuffle,num_workers=0)
    class LSTM(nn.Module):
        def __init__(self,n):
            super().__init__(); self.r=nn.LSTM(n,96,2,batch_first=True,dropout=.2); self.h=nn.Sequential(nn.LayerNorm(96),nn.Dropout(.2),nn.Linear(96,3))
        def forward(self,x): return self.h(self.r(x)[0][:,-1])
    class Transformer(nn.Module):
        def __init__(self,n):
            super().__init__(); self.p=nn.Linear(n,96); layer=nn.TransformerEncoderLayer(96,4,192,.15,batch_first=True,norm_first=True)
            self.e=nn.TransformerEncoder(layer,2); self.h=nn.Linear(96,3)
        def forward(self,x): return self.h(self.e(self.p(x))[:,-1])
    def fit(model,name):
        model.to(device); opt=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=1e-4); lossfn=nn.CrossEntropyLoss()
        best=1e9; state=None; stale=0
        for epoch in range(5):
            model.train(); ls=[]
            for xb,yb,_ in loader(Xtr,ytr,True):
                xb,yb=xb.to(device),yb.to(device); opt.zero_grad(set_to_none=True)
                loss=lossfn(model(xb),yb); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(),1.0); opt.step(); ls.append(loss.item())
            model.eval(); vl=[]
            with torch.no_grad():
                for xb,yb,_ in loader(Xva,yva):
                    vl.append(lossfn(model(xb.to(device)),yb.to(device)).item())
            score=float(np.mean(vl)); print(name,epoch+1,"train",np.mean(ls),"val",score)
            if score<best: best=score; state=copy.deepcopy(model.state_dict()); stale=0
            else:
                stale+=1
                if stale>=2: break
        if state: model.load_state_dict(state)
        torch.save(model.state_dict(),ART/f"{name}.pt")
        return model
    @torch.no_grad()
    def predict(model,X,y):
        model.eval(); pp=[]; ii=[]
        for xb,yb,idx in loader(X,y):
            pp.append(torch.softmax(model(xb.to(device)),1).cpu().numpy()); ii.extend(idx.numpy())
        out=np.full((len(y),3),np.nan); out[np.array(ii)]=np.vstack(pp); return out
    lm=fit(LSTM(Xtr.shape[1]),"lstm"); pmv,pmt=predict(lm,Xva,yva),predict(lm,Xte,yte)
    tm=fit(Transformer(Xtr.shape[1]),"transformer"); ptv,ptt=predict(tm,Xva,yva),predict(tm,Xte,yte)
    vm=np.isfinite(pmv).all(1)&np.isfinite(ptv).all(1); tmasks=np.isfinite(pmt).all(1)&np.isfinite(ptt).all(1)
    meta=LogisticRegression(max_iter=2000,class_weight="balanced",C=.5)
    meta.fit(np.c_[pxv[vm],pmv[vm],ptv[vm]],yva[vm])
    probs=meta.predict_proba(np.c_[pxte[tmasks],pmt[tmasks],ptt[tmasks]])
    yt=yte[tmasks]; pred=probs.argmax(1)
    brier=float(np.mean(np.sum((np.eye(3)[yt]-probs)**2,axis=1)))
    metrics={"accuracy":float(accuracy_score(yt,pred)),"balanced_accuracy":float(balanced_accuracy_score(yt,pred)),
             "log_loss":float(log_loss(yt,probs,labels=[0,1,2])),"brier_multiclass":brier,"n_test":int(len(yt))}
    print(json.dumps(metrics,indent=2)); print(classification_report(yt,pred,target_names=["DOWN","FLAT","UP"],zero_division=0))
    print("Confusion matrix\n",confusion_matrix(yt,pred))
    joblib.dump(meta,ART/"meta_ensemble.joblib"); np.save(ART/"test_probabilities.npy",probs)
    (ART/"metrics_test.json").write_text(json.dumps(metrics,indent=2))
    # BID/ASK horizon backtest; signal after candle close, enter next minute open, exit at t+15 close.
    qte=qte.copy(); qte.time=pd.to_datetime(qte.time,utc=True)
    quote_map=qte.set_index("time")
    test_rows=te.loc[tmasks].copy().reset_index(drop=True)
    test_rows["p_down"],test_rows["p_flat"],test_rows["p_up"]=probs[:,0],probs[:,1],probs[:,2]
    test_rows=test_rows.set_index("time").sort_index()
    trades=[]; threshold=.55
    for ts,r in test_rows.iterrows():
        side="BUY" if r.p_up>=threshold else ("SELL" if r.p_down>=threshold else None)
        if side is None: continue
        ent=ts+pd.Timedelta(minutes=1); ext=ts+pd.Timedelta(minutes=15)
        # Fill quotes are looked up in the full M1 BID/ASK stream, not the
        # stride-sampled prediction rows, so the next-minute entry is available.
        if ent not in quote_map.index or ext not in quote_map.index: continue
        er=quote_map.loc[ent]; xr=quote_map.loc[ext]
        if side=="BUY": entry=float(er.open_ask); exitp=float(xr.close_bid); pnl=exitp-entry
        else: entry=float(er.open_bid); exitp=float(xr.close_ask); pnl=entry-exitp
        trades.append({"time":ts,"side":side,"entry":entry,"exit":exitp,"pnl_price":pnl})
    td=pd.DataFrame(trades); td.to_csv(ART/"backtest_trades.csv",index=False)
    if len(td):
        win=td.loc[td.pnl_price>0,"pnl_price"].sum(); loss=-td.loc[td.pnl_price<0,"pnl_price"].sum()
        eq=td.pnl_price.cumsum(); dd=eq-eq.cummax()
        summary={"trades":len(td),"win_rate":float((td.pnl_price>0).mean()),"total_pnl_price":float(td.pnl_price.sum()),
                 "profit_factor":float(win/loss) if loss else None,"max_drawdown_price":float(dd.min())}
    else: summary={"trades":0,"note":"No signals passed threshold"}
    (ART/"backtest_summary.json").write_text(json.dumps(summary,indent=2)); print("BACKTEST",json.dumps(summary,indent=2))
    return metrics,summary

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--download-only",action="store_true")
    args=ap.parse_args()
    if not (OUT/"dataset_audit.csv").exists():
        prepare_data()
    else:
        print("Dataset audit already exists; reusing processed CSVs.")
    if not args.download_only:
        train_all()
    print("Artifacts:",ART)
