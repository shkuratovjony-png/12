"""Causal signal quality lab. Only closed candles are features.
October 1-15 fits a fixed ridge model of net R; October 16-31 is a
chronological development check, not an untouched validation month.
No order placement or live trading changes.
"""
import math,json
import numpy as np,pandas as pd
import impulse_adaptive as a,impulse_holdout as h,impulse_daily_risk as dr,impulse_forensics as f,impulse_research as old
NAMES=("side","relative_volume_log","signed_24h_return","turnover_log","hour_efficiency","m5_relative_volume_log","wick_fraction","close_location","body_atr","sweep_atr","reclaim_atr","stop_pct","cost_to_stop","room_to_mid_R")
CUT=int(pd.Timestamp("2026-10-16",tz="UTC").timestamp()/60)
def features(hourly,m,ss,events):
    # Compute once per symbol. Index H1 candle by availability, not start time.
    hh=hourly.copy()
    hf=pd.DataFrame({"ret":hh.close/hh.close.shift(24)-1,"turn":hh.turnover.rolling(24).sum(),"er":(hh.close-hh.close.shift(12)).abs()/hh.close.diff().abs().rolling(12).sum().replace(0,np.nan)})
    hf.index=hf.index+pd.Timedelta(hours=1)
    prev=m.close.shift(1)
    tr=pd.concat([m.high-m.low,(m.high-prev).abs(),(m.low-prev).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14).mean().shift(1)
    vol=m.volume/m.volume.shift(1).rolling(20).mean()
    lookup={int(ev[0]):ev for ev in events}
    rows=[]
    for i,s,e,stop,d,score,*_ in ss:
        t=m.index[i];ev=lookup.get(int(t.timestamp()/60))
        if ev is None or i<21 or t.floor("h") not in hf.index:continue
        b=m.iloc[i-1];p=m.iloc[i-13:i-1];q=hf.loc[t.floor("h")]
        span=float(b.high-b.low);av=float(atr.iloc[i-1]);px=float(b.close)
        # ATR ends BEFORE the signal candle. Price proxy is its close.
        if span<=0 or av<=0 or px<=0:continue
        sd=s*(px-stop)
        if sd<=0:continue
        level=float(p.low.min()) if s==1 else float(p.high.max())
        extreme=float(b.low if s==1 else b.high)
        tail=float(min(b.open,b.close)-b.low if s==1 else b.high-max(b.open,b.close))
        loc=float((b.close-b.low)/span if s==1 else (b.high-b.close)/span)
        mid=(float(p.high.max())+float(p.low.min()))/2
        x=[s,math.log(max(float(score),1e-12)),s*float(q.ret),math.log(max(float(q.turn),1e-12)),float(q.er),math.log(max(float(vol.iloc[i-1]),1e-12)),tail/span,loc,s*float(b.close-b.open)/av,s*(level-extreme)/av,s*(px-level)/av,sd/px,2*(a.F+a.SLIP)*px/sd,s*(mid-px)/sd]
        if all(math.isfinite(v) for v in x):rows.append([ev,x])
    return rows
def rough(events):
    # Archived fields known at execution: relative volume and planned stop-risk.
    def group(fn,cut):
        low=[e for e in events if fn(e)<cut];high=[e for e in events if fn(e)>=cut]
        return {"threshold":cut,"below":f.stats(low),"at_or_above":f.stats(high)}
    return {"volume_3x":group(lambda e:-e[1],3.),"risk_distance_2pct":group(lambda e:e[5]/e[4],.02)}
def fit(rows):
    if len(rows)<60:return None
    x=np.array([r[1] for r in rows],dtype=float);y=np.array([r[0][6]/r[0][5] for r in rows])
    if not (np.any(y>0) and np.any(y<=0)):return None
    # Training-only clipping/scaling; ridge regularization fixed in advance.
    lo,hi=np.quantile(x,[.05,.95],axis=0);z=np.clip(x,lo,hi);mu=z.mean(axis=0);sd=z.std(axis=0);sd[sd<1e-8]=1.
    z=(z-mu)/sd
    coef=np.linalg.solve(z.T@z+20*np.eye(z.shape[1]),z.T@(y-y.mean()))
    return {"lo":lo.tolist(),"hi":hi.tolist(),"mu":mu.tolist(),"sd":sd.tolist(),"coef":coef.tolist(),"intercept":float(y.mean())}
def predict(model,x):
    z=(np.clip(x,model["lo"],model["hi"])-np.array(model["mu"]))/np.array(model["sd"])
    return float(model["intercept"]+z@np.array(model["coef"]))
def summarize(rows,model):
    if not rows:return []
    x=np.array([r[1] for r in rows]);y=np.array([r[0][6]/r[0][5] for r in rows]);p=y>0
    if not p.any() or p.all():return []
    return sorted([{"feature":n,"win_mean":float(x[p,i].mean()),"loss_mean":float(x[~p,i].mean()),"coefficient":model["coef"][i]} for i,n in enumerate(NAMES)],key=lambda d:-abs(d["coefficient"]))
def report(rows,total):
    # Purge positions still open at the split. Holdout labels never enter fit.
    train=[r for r in rows if r[0][0]<CUT and r[0][3]<CUT]
    test=[r for r in rows if r[0][0]>=CUT]
    model=fit(train)
    result={"feature_rows":len(rows),"candidate_total":total,"train":len(train),"test":len(test),"status":"insufficient_data","results":{}}
    if model is None or not test:return result
    ranked=[];positive=[]
    for ev,x in test:
        score=predict(model,x);q=list(ev);q[1]=-score;ranked.append(q)
        if score>0:positive.append(q)
    def replay(events,cap):
        r=dr.replay(events,"profit_lock",max_positions=cap)
        for t in pd.date_range("2026-10-16","2026-10-31"):
            r["daily"].setdefault(t.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0,"entries":0})
        r["daily"]=dict(sorted(r["daily"].items()))
        r["flat_days"]=sum(v["pnl"]==0 for v in r["daily"].values())
        r["raw"]=f.stats(events)
        return r
    results={"baseline4":replay([r[0] for r in test],4)}
    for cap in (1,2,3,4):
        results["rank"+str(cap)]=replay(ranked,cap)
        results["positive"+str(cap)]=replay(positive,cap)
    result.update(status="complete_development_check",model=model,features=summarize(train,model),results=results)
    return result
