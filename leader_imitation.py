"""Learn entry context from observed leader trades, not just hypothetical grids.
Labels are first observed entries, deduplicated across the two leaders.
Unlabelled bars are not proof of no entry (closed-trade export is incomplete).
No lookahead features. Global chronological split, validation-selected threshold,
one final holdout. Only a conservative no-grid, 15/30-minute derivative may
publish DEMO signals after positive out-of-sample results.
"""
import time,logging,math
from pathlib import Path
import numpy as np
import pandas as pd
import store,market,league,leader_lab,leader_replay
BAR=900000
VIEW={}
NAMES=("ret15m","ret1h","ret4h","ret24h","ema_gap","rsi","atr","relative_volume","range_position","body","lower_wick","upper_wick")
def features(a):
    if len(a)<110:return None
    t,o,h,l,c,v=a.T
    s=pd.Series(c);vs=pd.Series(v);hi=pd.Series(h);lo=pd.Series(l)
    d=s.diff();up=d.clip(lower=0).ewm(alpha=1/14,adjust=False).mean();dn=(-d.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rsi=(up/(up+dn).replace(0,np.nan)-.5).to_numpy()
    atr=(pd.Series(np.maximum(h-l,np.maximum(abs(h-np.r_[c[0],c[:-1]]),abs(l-np.r_[c[0],c[:-1]])))).rolling(14).mean()/s).to_numpy()
    top=hi.shift(1).rolling(24).max();bot=lo.shift(1).rolling(24).min()
    x=np.column_stack([s.pct_change(i).to_numpy() for i in (1,4,16,96)]+[(s/s.ewm(span=24,adjust=False).mean()-1).to_numpy(),rsi,atr,(vs/(vs.shift(1).rolling(24).mean()+1e-9)-1).to_numpy(),((s-bot)/(top-bot).replace(0,np.nan)).to_numpy(),(c-o)/o,(np.minimum(o,c)-l)/c,(h-np.maximum(o,c))/c])
    gap=np.r_[0,np.cumsum(np.diff(t)!=BAR)]
    valid=np.isfinite(x).all(axis=1);valid[:96]=False;valid[96:] &= gap[96:]==gap[:-96]
    return np.clip(x,-10,10),valid
def entries(rows):
    # Exclude overlapping entries within one trader/symbol, then dedup leader
    # signals in the same 15m bucket across both traders.
    by={}
    for r in sorted(rows,key=lambda q:q["opened"]):
        if r["side"]!=1:continue
        sym=r["symbol"];previous=by.get(sym,0)
        by[sym]=max(previous,r["closed"])
        if r["opened"]>=previous:yield sym,int(r["opened"]*1000//BAR)*BAR-BAR
def samples(a,targets):
    f=features(a)
    if f is None:return None
    x,valid=f;t=a[:,0].astype(np.int64);y=np.isin(t,list(targets))
    return x,valid,y
def logistic(x,y):
    # Class-balanced fit, training-only scaling; scores are not calibrated probabilities.
    mu=x.mean(0);sd=np.maximum(x.std(0),1e-5)
    z=np.column_stack([np.ones(len(x)),np.clip((x-mu)/sd,-8,8)])
    w=np.zeros(z.shape[1])
    weights=np.where(y,0.5/max(1,y.sum()),0.5/max(1,(~y).sum()))
    for _ in range(100):
        p=1/(1+np.exp(-np.clip(z@w,-30,30)))
        grad=z.T@((p-y)*weights);grad[1:]+=.01*w[1:]
        w-=.5*grad
    return mu,sd,w
def score(x,mu,sd,w):
    z=np.column_stack([np.ones(len(x)),np.clip((x-mu)/sd,-8,8)])
    return 1/(1+np.exp(-np.clip(z@w,-30,30)))
def classification(p,y,threshold):
    take=p>=threshold;n=int(take.sum());hits=int((take&y).sum());events=int(y.sum())
    return {"signals":n,"observed_entries":events,"matches":hits,"precision":hits/max(1,n),"recall":hits/max(1,events),"base_rate":events/max(1,len(y))}
def trade_metrics(a,selected,start,end,hold,stop):
    vals=[];last=-1
    for i in np.flatnonzero(selected & (a[:,0]>=start)&(a[:,0]<end)):
        if i<=last or i+hold>=len(a) or a[i+hold,0]>=end or a[i+hold,0]-a[i,0]!=hold*BAR:continue
        entry=a[i+1,1]
        if entry<=0:continue
        exit=a[i+hold,4]
        for j in range(i+1,i+hold+1):
            if a[j,3]<=entry*(1-stop):
                exit=min(a[j,1],entry*(1-stop));break
        vals.append(exit/entry-1-.0025);last=i+hold
    return vals
def stats(vals):
    if not vals:return {"n":0,"mean":0.,"score":-1.,"win":0.}
    v=np.asarray(vals);return {"n":len(v),"mean":float(v.mean()),"score":float(v.mean()-v.std()/math.sqrt(len(v))),"win":float((v>0).mean())}
def train(datasets,targets):
    parts={}
    for sym,a in datasets.items():
        z=samples(a,targets.get(sym,set()))
        if z is not None:parts[sym]=(a,*z)
    if len(parts)<3:return {"reason":"not enough markets","approved":False}
    times=np.unique(np.concatenate([a[v,0] for a,x,v,y in parts.values()]))
    c1=times[int(len(times)*.6)];c2=times[int(len(times)*.8)]
    tx=[];ty=[]
    for a,x,v,y in parts.values():
        take=v&(a[:,0]<c1);tx.append(x[take]);ty.append(y[take])
    x=np.concatenate(tx);y=np.concatenate(ty)
    if y.sum()<20:return {"reason":"not enough first entries in train","train_entries":int(y.sum()),"approved":False}
    # Fixed negative downsample for bounded CPU, all positive rows preserved.
    neg=np.flatnonzero(~y);pos=np.flatnonzero(y)
    rng=np.random.default_rng(20261125)
    ix=np.r_[pos,rng.choice(neg,min(len(neg),max(2000,len(pos)*30)),replace=False)]
    mu,sd,w=logistic(x[ix],y[ix])
    pred={sym:score(x,mu,sd,w) for sym,(a,x,v,y) in parts.items()}
    def eval_split(start,end,threshold,hold,stop):
        vals=[];pp=[];yy=[];per={}
        for sym,(a,x,v,y) in parts.items():
            p=pred[sym];take=v&(a[:,0]>=start)&(a[:,0]<end);pp.extend(p[take]);yy.extend(y[take])
            rets=trade_metrics(a,v&(p>=threshold),start,end,hold,stop)
            per[sym]=stats(rets);vals.extend(rets)
        return {"entry_match":classification(np.asarray(pp),np.asarray(yy,bool),threshold),"pnl":stats(vals),"symbols":per}
    # Validation chooses among thresholds and executable holds/stops. Test is not used to tune.
    candidates=[]
    for threshold in (.55,.65,.75,.85,.90):
        for hold in (1,2):
            for stop in (.005,.01,.015):
                val=eval_split(c1,c2,threshold,hold,stop)
                if val["pnl"]["n"]>=15:candidates.append((val["pnl"]["score"],threshold,hold,stop,val))
    if not candidates:return {"reason":"no validation candidate","train_entries":int(y.sum()),"approved":False}
    _,threshold,hold,stop,val=max(candidates,key=lambda x:x[0])
    test=eval_split(c2,float("inf"),threshold,hold,stop)
    # Positive pooled return alone is insufficient; require positive individual
    # symbols in both chronological periods before allowing their DEMO signal.
    allowed=[sym for sym in parts if all(m["symbols"][sym]["n"]>=5 and m["symbols"][sym]["mean"]>0 for m in (val,test))]
    approved=bool(allowed) and all(m["pnl"]["n"]>=15 and m["pnl"]["score"]>0 and m["entry_match"]["matches"]>=3 and m["entry_match"]["precision"]>m["entry_match"]["base_rate"] for m in (val,test))
    return {"time":time.time(),"approved":approved,"allowed":allowed if approved else [],"train_entries":int(y.sum()),"rows":sum(len(a) for a,*_ in parts.values()),"threshold":threshold,"hold":hold,"stop":stop,"validation":val,"test":test,"cutoffs":[int(c1),int(c2)],"weights":dict(zip(NAMES,map(float,w[1:]))),"mu":mu.tolist(),"sd":sd.tolist(),"w":w.tolist()}
def worker():
    global VIEW
    report=store.get("leader_imitation_v1",{}) or {}
    last={};last_try=0
    while True:
        try:
            now=time.time()
            if not report and now-last_try>60:
                last_try=now
                progress=store.get("leader_replay_progress_v1",{}) or {}
                ready=[sym for sym in leader_replay.SYMS if progress.get(sym,{}).get("done")]
                if len(ready)==len(leader_replay.SYMS):
                    targets={}
                    for name in ("AlfaRomeo","PlymouthTrade"):
                        rows=leader_lab.parse((Path(__file__).parent/"leader_data"/(name+".csv")).read_text(encoding="utf-8-sig"))
                        for sym,t in entries(rows):targets.setdefault(sym,set()).add(t)
                    data={sym:leader_replay.data(sym,progress[sym]) for sym in ready}
                    report=train(data,targets);report["observed_first_buckets"]=sum(len(targets.get(s,set())) for s in ready)
                    store.put("leader_imitation_v1",report)
                    logging.info("LEADER IMITATION %s",{k:v for k,v in report.items() if k not in ("mu","sd","w")})
                else:VIEW={"status":"waiting_history","markets":len(ready),"total":len(leader_replay.SYMS)}
            ranked=[]
            if report:
                VIEW={k:v for k,v in report.items() if k not in ("mu","sd","w")}
                if report.get("approved"):
                    for sym in report["allowed"]:
                        # Use only currently subscribed liquid markets, no stale quote fallback.
                        if sym not in market.SYMBOLS:continue
                        key="leader-imitation:"+sym
                        ranked.append({"key":key,"market":"linear","symbol":sym,"family":"leader_imitation","eligible":False,"pilot":False,"historical":True,"historical_score":min(report["validation"]["symbols"][sym]["mean"],report["test"]["symbols"][sym]["mean"]),"trades":0,"net":0.,"score":report["validation"]["pnl"]["score"],"drawdown":0.,"tier":"practice","allocation":.025})
                        rows=store.get("candles:"+sym,[])
                        if len(rows)<110:continue
                        a=np.asarray(rows,float);bar=int(a[-1,0])
                        if bar<=last.get(sym,0) or not 0<=time.time()*1000-bar-BAR<=90000:continue
                        last[sym]=bar;f=features(a)
                        if f is None or not f[1][-1]:continue
                        p=score(f[0][-1:],np.asarray(report["mu"]),np.asarray(report["sd"]),np.asarray(report["w"]))[0]
                        if p>=report["threshold"]:
                            t=time.time();league.publish(key,"linear",sym,1,{"leader_imitation":True},t,t+20,report["hold"]*900,report["stop"])
                            logging.info("LEADER IMITATION SIGNAL %s score=%.4f",sym,p)
            league.update("leader_imitation",ranked)
        except Exception:logging.exception("LEADER IMITATION error")
        time.sleep(10)
def selftest():
    a=[{"symbol":"X","side":1,"opened":1000,"closed":2000},{"symbol":"X","side":1,"opened":1100,"closed":2200},{"symbol":"X","side":1,"opened":2300,"closed":2400}]
    assert len(list(entries(a)))==2
    x=np.array([[0.,0.],[1.,1.],[2.,2.],[3.,3.]])
    mu,sd,w=logistic(x,np.array([False,False,True,True]))
    assert score(x,mu,sd,w)[-1]>score(x,mu,sd,w)[0]
