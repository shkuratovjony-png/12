"""Separate entry-quality experiments, never modifies the frozen holdout.
October is development data; November is a distinct validation period.
No order placement. Filters use only candles closed before entry.
"""
import json,time
import pandas as pd
import store,impulse_adaptive as a,impulse_daily_risk as dr,impulse_holdout as holdout,impulse_research as old
MODELS=("baseline","clean_trend","confirmed_trend","cost_aware_trend")
def features(h,m):
    net=h.close-h.close.shift(12)
    path=h.close.diff().abs().rolling(12).sum()
    efficiency=net.abs()/path.replace(0,float("nan"))
    # H1 features available only from the next hour.
    hf=pd.DataFrame({"er":efficiency,"trend":net,"ema":h.close.ewm(span=24,adjust=False).mean(),"close":h.close})
    hf.index=hf.index+pd.Timedelta(hours=1)
    prev=m.close.shift(1)
    tr=pd.concat([m.high-m.low,(m.high-prev).abs(),(m.low-prev).abs()],axis=1).max(axis=1)
    mf=pd.DataFrame({"atr":tr.rolling(14).mean().shift(1),"body":(m.close-m.open).shift(1),"vol":m.volume.shift(1)/m.volume.shift(2).rolling(20).mean(),"range":(m.high-m.low).shift(1)})
    return hf,mf
def select(m,signals,hf,mf):
    out={k:[] for k in MODELS}
    for sig in signals:
        i,side,e,stop,dist,score,daily,alignment=sig
        if not alignment:continue
        out["baseline"].append(sig)
        t=m.index[i];hour=t.floor("h")
        if hour not in hf.index:continue
        h=hf.loc[hour];f=mf.iloc[i]
        if not (h.er>=.35 and side*h.trend>0 and side*(h.close-h.ema)>0):continue
        out["clean_trend"].append(sig)
        if not (f.atr>0 and side*f.body>=.45*f.atr and f.vol>=1.2 and f.range<=2.5*f.atr):continue
        out["confirmed_trend"].append(sig)
        # Known round-trip cost proxy and stop/ATR sanity. No future funding or candle data.
        if not (.8<=dist/f.atr<=3 and 2*(a.F+a.SLIP)*e/dist<=.12):continue
        out["cost_aware_trend"].append(sig)
    return out
def summary(events,start,end):
    result=dr.replay(events,"profit_lock")
    for t in pd.date_range(start,end-pd.Timedelta(days=1),freq="D"):
        result["daily"].setdefault(t.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0,"entries":0})
    result["daily"]=dict(sorted(result["daily"].items()))
    result["flat_days"]=sum(v["pnl"]==0 for v in result["daily"].values())
    result["raw_candidates"]=len(events)
    result["raw_mean_R"]=sum(x[6]/x[5] for x in events)/len(events) if events else None
    return result
def run(period="october"):
    if period not in ("october","november"):raise ValueError("unknown period")
    if not store.URL:return
    frozen=store.get(holdout.KEY)
    if not frozen:return
    if period=="november" and not (store.get("research:adaptive_entry_quality:october:v1") or {}).get("complete"):return
    start,end=(holdout.START,holdout.END) if period=="october" else (pd.Timestamp("2026-11-01",tz="UTC"),pd.Timestamp("2026-11-22",tz="UTC"))
    key="research:adaptive_entry_quality:"+period+":v1"
    state=store.get(key,{"universe":frozen["universe"],"scanned":[],"excluded":[],"events":{k:[] for k in MODELS},"complete":False})
    if state["complete"]:return
    for sym in state["universe"]:
        if sym in state["scanned"]:continue
        h=a.window(sym,60,start-pd.Timedelta(days=32),end)
        if h is None:state["excluded"].append(sym+":H1")
        else:
            allowed=a.eligible(h,start,end)
            if allowed:
                m=a.window(sym,5,start-pd.Timedelta(minutes=120),end+pd.Timedelta(minutes=65))
                if m is None:state["excluded"].append(sym+":M5")
                else:
                    sig=a.setups(m,allowed,start,end)
                    if sig:
                        rates=holdout.funding(sym,start,end)
                        if not rates:state["excluded"].append(sym+":funding")
                        else:
                            hf,mf=features(h,m)
                            for name,selected in select(m,sig,hf,mf).items():
                                state["events"][name].extend(a.exits(sym,m,selected,rates,*a.VARIANTS[holdout.MODEL],end=end))
        state["scanned"].append(sym)
        state["complete"]=len(state["scanned"])==len(state["universe"])
        state["result"]={k:summary(v,start,end) for k,v in state["events"].items()}
        state["updated"]=time.time()
        old.db_put(key,state)
        compact={k:{n:v[n] for n in ("balance","roi","dd","trades","wins","days","positive_days","negative_days","flat_days","fees","funding","raw_candidates","raw_mean_R")} for k,v in state["result"].items()}
        print("ADAPTIVE_QUALITY_LAB",json.dumps({"period":period,"scanned":len(state["scanned"]),"universe":len(state["universe"]),"complete":state["complete"],"excluded_count":len(state["excluded"]),"result":compact},default=old.json_number),flush=True)
