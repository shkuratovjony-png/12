"""Pooled chronological OHLCV replay; public market only.
No claim of tick-level fills, independent repeated holdouts, or live profitability.
Fixed hyperparameters, global time splits, costs and conservative stop proxy.
"""
import time,logging,math
import numpy as np
import pandas as pd
import store,risk
BAR=900000
HORIZONS=(1,4,16)
VIEW={}
MODELS={}
NAMES=("bias","ret1","ret2","ret4","ret8","ret16","ret32","ret64","ema8","ema24","ema64","range","body","upper_wick","lower_wick","atr8","atr24","vol8","vol24","rel_volume","range_pos24","break_high24","break_low24","efficiency","hour_sin","hour_cos")
def features(rows):
    a=np.asarray(rows,float)
    if len(a)<100 or a.ndim!=2 or a.shape[1]!=6:return None
    t,o,h,l,c,v=a.T
    s=pd.Series(c);hs=pd.Series(h);ls=pd.Series(l);vs=pd.Series(v)
    r=s.pct_change()
    tr=np.maximum(h-l,np.maximum(abs(h-np.r_[c[0],c[:-1]]),abs(l-np.r_[c[0],c[:-1]])))/c
    hi=hs.shift(1).rolling(24).max();lo=ls.shift(1).rolling(24).min()
    mat=[np.ones(len(c))]
    mat.extend(s.pct_change(n).to_numpy()*100 for n in (1,2,4,8,16,32,64))
    mat.extend((s/s.ewm(span=n,adjust=False).mean()-1).to_numpy()*100 for n in (8,24,64))
    mat.extend([(h-l)/c*100,(c-o)/o*100,(h-np.maximum(o,c))/c*100,(np.minimum(o,c)-l)/c*100])
    mat.extend(pd.Series(tr).rolling(n).mean().to_numpy()*100 for n in (8,24))
    mat.extend(r.rolling(n).std().to_numpy()*100 for n in (8,24))
    mat.extend([(vs/(vs.shift(1).rolling(24).mean()+1e-9)-1).to_numpy(),
                ((s-lo)/(hi-lo).replace(0,np.nan)*2-1).to_numpy(),
                (s/hi-1).to_numpy()*100,(s/lo-1).to_numpy()*100,
                ((s-s.shift(24)).abs()/(s.diff().abs().rolling(24).sum()+1e-12)).to_numpy(),
                np.sin(t/86400000*2*np.pi),np.cos(t/86400000*2*np.pi)])
    x=np.column_stack(mat);gap=np.r_[0,np.cumsum(np.diff(t)!=BAR)]
    valid=np.isfinite(x).all(axis=1);valid[:64]=False
    valid[64:] &= gap[64:]==gap[:-64]
    return a,np.clip(x,-8,8),valid
def examples(rows,kind):
    f=features(rows)
    if f is None:return None
    a,x,valid=f;t=a[:,0]
    ix=np.arange(64,len(a)-max(HORIZONS));ix=ix[valid[ix] & (t[ix+16]-t[ix]==16*BAR)]
    if not len(ix):return None
    entry=a[ix+1,1];cost=.0039 if kind=="spot" else .0019
    targets=[]
    for h in HORIZONS:
        move=a[ix+h,4]/entry-1
        low=np.min(np.column_stack([a[ix+j,3] for j in range(1,h+1)]),axis=1)
        high=np.max(np.column_stack([a[ix+j,2] for j in range(1,h+1)]),axis=1)
        targets.extend([np.where(low<=entry*(1-risk.STOP),-risk.STOP,move)-cost,
                        np.where(high>=entry*(1+risk.STOP),-risk.STOP,-move)-cost])
    return x[ix],np.column_stack(targets),t[ix],ix
def metrics(pred,y,ids,indices,kind,h):
    # Nonoverlapping per-instrument samples for multi-bar horizons.
    k=HORIZONS.index(h)*2
    p=pred[:,k:k+2];side=np.argmax(p,axis=1) if kind=="linear" else np.zeros(len(p),int)
    score=p[np.arange(len(p)),side]
    take=(score>.0005)&(indices%h==0)
    ret=y[np.arange(len(p)),k+side][take]
    per={}
    for s in np.unique(ids[take]):
        v=ret[ids[take]==s];per[str(s)]={"trades":int(len(v)),"mean_net":float(v.mean())}
    return {"trades":int(len(ret)),"mean_net":float(ret.mean()) if len(ret) else 0.,
            "win_rate":float((ret>0).mean()) if len(ret) else 0.,
            "positive_symbols":sum(v["mean_net"]>0 for v in per.values()),"symbols":per}
def train(kind,data):
    parts=[]
    for sym,rows in data.items():
        e=examples(rows,kind)
        if e is not None and len(e[0])>=200:parts.append((*e,np.full(len(e[0]),sym)))
    if len(parts)<3:return None
    x,y,t,ix,ids=[np.concatenate([p[j] for p in parts]) for j in range(5)]
    # All instruments share the same chronological boundaries, preventing future
    # observations on one instrument leaking into another's earlier validation.
    times=np.unique(t);c1=times[int(len(times)*.60)];c2=times[int(len(times)*.80)]
    tr=t+16*BAR<c1;va=(t>=c1)&(t+16*BAR<c2);te=t>=c2
    if min(tr.sum(),va.sum(),te.sum())<100:return None
    scale=np.maximum(np.std(x[tr],axis=0),.1);scale[0]=1.
    z=x/scale
    # Ridge regression jointly learns six long/short exit alternatives.
    w=np.linalg.solve(z[tr].T@z[tr]+np.eye(z.shape[1])*30,z[tr].T@y[tr])
    val={str(h):metrics(z[va]@w,y[va],ids[va],ix[va],kind,h) for h in HORIZONS}
    test={str(h):metrics(z[te]@w,y[te],ids[te],ix[te],kind,h) for h in HORIZONS}
    v=val["1"];u=test["1"]
    approved=all(m["trades"]>=30 and m["mean_net"]>0 and m["positive_symbols"]>=2 for m in (v,u))
    return {"time":time.time(),"rows":len(x),"train":int(tr.sum()),"validation_rows":int(va.sum()),"test_rows":int(te.sum()),
            "features":len(NAMES),"symbols":len(parts),"cutoffs":[int(c1),int(c2)],"validation":val,"test":test,"approved":approved,
            "w":w.tolist(),"scale":scale.tolist(),"last_bar":int(t.max()),"kind":kind}
def signal(rows,kind):
    m=MODELS.get(kind)
    if not m or not m.get("approved") or time.time()-m["time"]>3600:return 0
    f=features(rows)
    if f is None or not f[2][-1]:return 0
    p=(f[1][-1]/np.asarray(m["scale"]))@np.asarray(m["w"])
    i=0 if kind=="spot" or p[0]>=p[1] else 1
    return (1 if i==0 else -1) if p[i]>.0005 else 0
def worker(market,spot_universe):
    global VIEW,MODELS
    MODELS=store.get("pooled_replay_v1",{}) or {}
    seen={}
    while True:
        try:
            for kind,syms in (("linear",list(market.SYMBOLS)),("spot",spot_universe())):
                prefix="candles:" if kind=="linear" else "spot_candles:"
                d=store.get_many([prefix+s for s in syms])
                data={s:d.get(prefix+s,[]) for s in syms}
                signature=tuple((s,len(r),r[-1][0] if r else 0) for s,r in sorted(data.items()))
                if signature!=seen.get(kind):
                    m=train(kind,data)
                    if m:
                        MODELS={**MODELS,kind:m};store.put("pooled_replay_v1",MODELS);seen[kind]=signature
                        logging.info("POOLED REPLAY kind=%s rows=%s symbols=%s approved=%s test=%s",kind,m["rows"],m["symbols"],m["approved"],{h:{k:v for k,v in r.items() if k!="symbols"} for h,r in m["test"].items()})
            VIEW={k:{a:b for a,b in m.items() if a not in ("w","scale")} for k,m in MODELS.items()}
        except Exception:logging.exception("Pooled replay error")
        time.sleep(60)
def selftest():
    rows=[[i*BAR,100+i*.01,100.2+i*.01,99.8+i*.01,100.05+i*.01,100+i%7] for i in range(450)]
    e=examples(rows,"linear");assert e is not None and e[0].shape[1]==len(NAMES) and e[1].shape[1]==6
    a=train("linear",{str(i):rows for i in range(3)})
    assert a and a["train"]>0 and a["test_rows"]>0
