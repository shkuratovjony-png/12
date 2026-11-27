"""October entry forensic lab. No orders; unchanged September profit_lock sizing.
Stored candidate events are not the executed portfolio. Forensic forward excursions are
descriptive ONLY; new entry rules never access them.
"""
import json,time,math
from collections import defaultdict
import numpy as np,pandas as pd
import store,impulse_adaptive as a,impulse_holdout as h,impulse_research as old,impulse_daily_risk as dr
KEY="research:adaptive_forensics:october:v1"
MODELS=("control","retest","ema_pullback","range_sweep")
def stats(events):
    if not events:return {"n":0,"wins":0,"mean_R":None,"gross_mean_R":None,"mean_win_R":None,"mean_loss_R":None}
    rs=[e[6]/e[5] for e in events]
    win=[r for r in rs if r>0];loss=[r for r in rs if r<0]
    return {"n":len(rs),"wins":len(win),"mean_R":sum(rs)/len(rs),"gross_mean_R":sum((e[6]+e[7]+e[8])/e[5] for e in events)/len(rs),"mean_win_R":sum(win)/len(win) if win else None,"mean_loss_R":sum(loss)/len(loss) if loss else None}
def forensic(events):
    groups=defaultdict(list)
    for e in events:
        groups["symbol:"+e[2]].append(e)
        minutes=e[3]-e[0]
        groups["hold:"+("0-5m" if minutes<=5 else "10-25m" if minutes<30 else "30m+")].append(e)
    return {"overall":stats(events),"by_hold":{k[5:]:stats(v) for k,v in groups.items() if k.startswith("hold:")},"by_symbol":{k[7:]:stats(v) for k,v in groups.items() if k.startswith("symbol:")}}
def excursion(m,sig):
    """Counterfactual entire 30m/60m price path, independent of actual exit.
    Never passed to entry selectors. Not actual executable PnL.
    """
    i,s,e,stop,d,*_=sig
    def path(n):
        bars=m.iloc[i:i+n]
        return (max(0.,(bars.high.max()-e)/d) if s==1 else max(0.,(e-bars.low.min())/d),max(0.,(e-bars.low.min())/d) if s==1 else max(0.,(bars.high.max()-e)/d))
    return (*path(6),*path(12))
def make(m,i,s,stop,score,allowed,aligned=True):
    if i<1 or i+12>=len(m):return None
    t=m.index[i]
    if not h.START<=t<h.END:return None
    f=allowed.get(t.floor("h"))
    if f is None or (aligned and s!=f[2]):return None
    e=float(m.open.iloc[i])*(1+s*a.SLIP)
    stop=float(stop)*(1-s*.0002);d=s*(e-stop)
    if not .01<=d/e<=.03 or s*(float(m.open.iloc[i])-stop)<=0:return None
    return (i,s,e,stop,d,float(score),f[0]==s,True)
def signals(hourly,m,allowed,base):
    out={k:[] for k in MODELS}
    out["control"]=[x for x in base if x[-1]]
    # Wait for a retest of the actual broken candle's high/low; enter only on
    # the next candle after reclaim, never at the retrospectively best price.
    for i,s,e,stop,d,score,daily,aligned in out["control"]:
        level=float(m.high.iloc[i-2] if s==1 else m.low.iloc[i-2])
        for j in range(i,min(i+3,len(m)-12)):
            bar=m.iloc[j]
            touch=bar.low<=level*(1+.001) if s==1 else bar.high>=level*(1-.001)
            if s*(float(bar.low if s==1 else bar.high)-stop)<=0:break
            if touch and s*(float(bar.close)-level)>0 and s*(float(bar.close)-float(bar.open))>0:
                x=make(m,j+1,s,stop/(1-s*.0002),score,allowed)
                if x:out["retest"].append(x)
                break
    ema=m.close.ewm(span=20,adjust=False).mean()
    vol=m.volume/m.volume.shift(1).rolling(20).mean()
    hh=hourly.high;ll=hourly.low
    efficiency=(hourly.close-hourly.close.shift(12)).abs()/hourly.close.diff().abs().rolling(12).sum().replace(0,np.nan)
    efficiency.index=efficiency.index+pd.Timedelta(hours=1)
    for s in (1,-1):
        o=s*m.open;c=s*m.close;high=m.high if s==1 else -m.low;low=m.low if s==1 else -m.high
        # Early pullback reclaim, not the original three-candle impulse.
        mask=(s*(m.close-ema)>0)&(s*(m.close.shift(1)-ema.shift(1))<=0)&(c>o)&(vol>=1)&(s*(ema-ema.shift(4))>0)
        anchor=low.rolling(4).min()
        for i in np.flatnonzero(mask.fillna(False).to_numpy())+1:
            if i>=len(m):continue
            f=allowed.get(m.index[i].floor("h"))
            if not f or f[2]!=s:continue
            er=efficiency.get(m.index[i].floor("h"),np.nan)
            if not er>=.35:continue
            x=make(m,i,s,s*anchor.iloc[i-1],f[1],allowed)
            if x:out["ema_pullback"].append(x)
        # Failed breakout of an already known one-hour range in a weak trend.
        level=low.shift(1).rolling(12).min()
        mask=(low<level)&(c>level)&(c>o)&(vol>=1)
        for i in np.flatnonzero(mask.fillna(False).to_numpy())+1:
            if i>=len(m):continue
            f=allowed.get(m.index[i].floor("h"))
            if not f:continue
            er=efficiency.get(m.index[i].floor("h"),np.nan)
            if not er<=.25:continue
            x=make(m,i,s,s*low.iloc[i-1],f[1],allowed,False)
            if x:out["range_sweep"].append(x)
    for k in MODELS:
        out[k]=list({(x[0],x[1]):x for x in out[k]}.values())
    return out
def excursion_summary(rows):
    # rows: net R, MFE30, MAE30, MFE60, MAE60, side, stop%
    losses=[r for r in rows if r[0]<0]
    return {"n":len(rows),"losses":len(losses),"loss_mfe30_lt_halfR":sum(r[1]<.5 for r in losses),"loss_mfe30_ge_1R":sum(r[1]>=1 for r in losses),"loss_mfe60_ge_2R":sum(r[3]>=2 for r in losses),"long":sum(r[5]==1 for r in rows),"short":sum(r[5]==-1 for r in rows),"long_losses":sum(r[5]==1 for r in losses),"short_losses":sum(r[5]==-1 for r in losses)}
def publish(state):
    results={}
    for k,events in state["events"].items():
        r=dr.replay(events,"profit_lock")
        for t in pd.date_range(h.START,h.END-pd.Timedelta(days=1),freq="D"):
            r["daily"].setdefault(t.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0,"entries":0})
        r["daily"]=dict(sorted(r["daily"].items()))
        r["flat_days"]=sum(v["pnl"]==0 for v in r["daily"].values())
        r["raw"]=stats(events);results[k]=r
    state["result"]=results;state["excursion_summary"]=excursion_summary(state["excursions"]);state["updated"]=time.time()
    old.db_put(KEY,state)
    compact={k:{n:v[n] for n in ("balance","roi","dd","trades","wins","positive_days","negative_days","flat_days","raw")} for k,v in results.items()}
    print("ADAPTIVE_FORENSICS_RESULT",json.dumps({"scanned":len(state["scanned"]),"universe":len(state["universe"]),"complete":state["complete"],"excluded_count":len(state["excluded"]),"diagnosis":state["excursion_summary"],"result":compact},default=old.json_number),flush=True)
def run():
    if not store.URL:return
    state=store.get(KEY)
    if not state:
        prev=store.get("research:adaptive_recovery:october:v1")
        if not prev:raise RuntimeError("Missing recovery archive")
        diagnosis=forensic(prev["events"])
        # Log stored raw candidate outcomes before any new market request.
        print("ADAPTIVE_FORENSICS_ARCHIVE",json.dumps({"scanned":len(prev["scanned"]),"universe":len(prev["universe"]),"diagnosis":diagnosis},default=old.json_number),flush=True)
        priority=list(dict.fromkeys(e[2] for e in prev["events"]))
        # Revisit all known signal symbols first for actual price-path diagnosis.
        # This is a biased intermediate subset, not a final market-wide result.
        state={"universe":prev["universe"],"order":list(dict.fromkeys(priority+prev["universe"])),"scanned":[],"excluded":[],"events":{k:[] for k in MODELS},"excursions":[],"archive":diagnosis,"archive_scanned":len(prev["scanned"]),"complete":False}
    publish(state)
    if state["complete"]:return
    for sym in state["order"]:
        if sym in state["scanned"]:continue
        hourly=a.window(sym,60,h.START-pd.Timedelta(days=32),h.END)
        if hourly is None:state["excluded"].append(sym+":H1")
        else:
            allowed=a.eligible(hourly,h.START,h.END)
            if allowed:
                m=a.window(sym,5,h.START-pd.Timedelta(minutes=120),h.END+pd.Timedelta(minutes=65))
                if m is None:state["excluded"].append(sym+":M5")
                else:
                    base=a.setups(m,allowed,h.START,h.END)
                    candidates=signals(hourly,m,allowed,base)
                    if any(candidates.values()):
                        rates=h.funding(sym)
                        if not rates:state["excluded"].append(sym+":funding")
                        else:
                            for k,ss in candidates.items():
                                # All variants use the SAME 30m, 2R, 1R break-even exits.
                                events=a.exits(sym,m,ss,rates,6,2,1,"switch",end=h.END)
                                state["events"][k].extend(events)
                                if k=="control":
                                    for sig,event in zip(ss,events):
                                        state["excursions"].append([event[6]/event[5],*excursion(m,sig),sig[1],sig[4]/sig[2]])
        state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(state["universe"])
        publish(state)
