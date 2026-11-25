"""Data-driven leader imitation and evolutionary exit/grid search.
Training features use only completed pre-entry bars; only trades closed before
the training cutoff seed exits. Holdout evaluated once, never used to breed.
Research scores do not establish real-money profitability.
"""
import time,logging,math
from pathlib import Path
import numpy as np
import leader_lab,leader_imitation,leader_replay
BAR=leader_replay.BAR
def read_examples():
    return {name:leader_lab.parse((Path(__file__).parent/"leader_data"/(name+".csv")).read_text(encoding="utf-8-sig")) for name in ("AlfaRomeo","PlymouthTrade")}
def quantiles(xs):
    return [float(x) for x in np.quantile(xs,[.15,.35,.5,.65,.85])] if xs else []
def fit(a,sym,examples):
    x,valid=leader_imitation.features(a)
    n=len(a);c1=int(n*.6);c2=int(n*.8);cut=a[c1,0]/1000
    targets=set()
    exits=[];holds=[];steps=[];depth=[];adverse=[]
    for rows in examples.values():
        seen=[r for r in rows if r["symbol"]==sym and r["closed"]<cut]
        targets.update(t for s,t in leader_imitation.entries(seen) if s==sym)
        prev=[]
        for r in seen:
            prev=[p for p in prev if p["closed"]>r["opened"]]
            if prev:
                z=1-r["entry"]/prev[-1]["entry"]
                if z>0:steps.append(z)
                depth.append(len(prev))
            else:depth.append(0)
            prev.append(r)
            ret=r["exit"]/r["entry"]-1
            if ret>0:exits.append(ret)
            holds.append(max(1,(r["closed"]-r["opened"])/900))
            j=int(np.searchsorted(a[:,0],r["opened"]*1000,side="right"))
            k=int(np.searchsorted(a[:,0],r["closed"]*1000,side="left"))
            if k>j and k<=c1:
                adverse.append(max(0.,1-float(a[j:k,3].min())/r["entry"]))
    y=np.isin(a[:,0].astype(np.int64),list(targets))
    tr=valid & (np.arange(n)<c1)
    pos=np.flatnonzero(tr&y);neg=np.flatnonzero(tr&~y)
    if len(pos)<8 or len(neg)<100 or not exits or not holds:return None
    rng=np.random.default_rng(20261125)
    ix=np.r_[pos,rng.choice(neg,min(len(neg),max(1000,len(pos)*30)),replace=False)]
    mu,sd,w=leader_imitation.logistic(x[ix],y[ix])
    scores=np.zeros(n);scores[valid]=leader_imitation.score(x[valid],mu,sd,w)
    # Candidate prior comes from actual leader examples, not a manual RSI/dip rule.
    prior={"entry_score":quantiles(scores[pos].tolist()),"tp":quantiles(exits),"hold":quantiles(holds),"step":quantiles(steps),"adds":quantiles(depth),"stop":quantiles(adverse),"first_entries":int(len(pos)),"exit_examples":len(exits),"add_examples":len(steps),"adverse_examples":len(adverse)}
    # Where no additions were observed, do not invent leader grid evidence.
    return {"prior":prior,"mu":mu.tolist(),"sd":sd.tolist(),"w":w.tolist(),"cutoffs":[int(a[c1,0]),int(a[c2,0])]},scores,valid,c1,c2
def sample(rng,prior,parent=None):
    def choose(k,default):
        xs=prior.get(k) or [default];return float(rng.choice(xs))
    # Execution envelope only; parameter search is seeded by examples.
    p={"threshold":choose("entry_score",.5),"tp":choose("tp",.01),"hold":choose("hold",4),"step":choose("step",0),"adds":choose("adds",0),"stop":choose("stop",.01)}
    if parent:
        p=dict(parent)
        for k in p:
            if rng.random()<.45:
                if k=="adds":p[k]+=int(rng.choice([-1,1]))
                elif k=="threshold":p[k]+=float(rng.normal(0,.05))
                else:p[k]*=float(np.exp(rng.normal(0,.30)))
    p["threshold"]=round(float(np.clip(p["threshold"],.05,.99)),4)
    p["tp"]=round(float(np.clip(p["tp"],.002,.15)),5)
    p["hold"]=int(np.clip(round(p["hold"]),1,96))
    p["adds"]=int(np.clip(round(p["adds"]),0,4)) if prior["add_examples"] else 0
    p["step"]=round(float(np.clip(p["step"],.001,.08)),5) if p["adds"] else 0.
    p["stop"]=round(float(np.clip(max(p["stop"],p["step"]*p["adds"]+.002),.003,.35)),5)
    if p["step"]*p["adds"]>=p["stop"]:p["adds"]=max(0,int((p["stop"]-.003)/max(p["step"],.001)))
    return p
def advance(a,sym,examples,old,feedback=None):
    fitted=fit(a,sym,examples)
    if fitted is None:return {"reason":"insufficient matched first-entry examples","rows":len(a),"generation":0}
    model,pred,valid,c1,c2=fitted
    prior=model["prior"]
    generation=int(old.get("generation",0))+1
    rng=np.random.default_rng(20261125+sum(map(ord,sym))+generation*101)
    archive=old.get("archive",[])
    # Real demo PnL affects parent sampling, not the historical holdout.
    parents=[e for e in archive if e.get("train",{}).get("n",0)>=8]
    feedback=feedback or {}
    def parent_score(e):
        f=feedback.get(e.get("key"),{})
        return e["fitness"]+float(f.get("net_return",0))/(int(f.get("n",0))+5)
    parents.sort(key=parent_score,reverse=True)
    candidates=[e["params"] for e in parents[:4]]
    for i in range(24):
        parent=parents[i%min(len(parents),4)]["params"] if parents and i%3 else None
        candidates.append(sample(rng,prior,parent))
    import json,hashlib
    ranked=[];seen=set()
    for p in candidates:
        key=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()[:16]
        if key in seen:continue
        seen.add(key);sig=valid&(pred>=p["threshold"])
        args=(p["tp"],p["stop"],p["step"],p["adds"],p["hold"])
        tr=leader_replay.simulate(a,sig,110,c1,*args)
        va=leader_replay.simulate(a,sig,c1,c2,*args)
        if min(tr["n"],va["n"])<8:continue
        fitness=min(tr["score"],va["score"])-.1*max(tr["dd"],va["dd"])
        sid="leader-evo:"+sym+":"+key
        ranked.append({"key":sid,"params":p,"train":tr,"validation":va,"fitness":fitness})
    ranked.sort(key=lambda e:e["fitness"],reverse=True)
    result={**model,"rows":len(a),"generation":generation,"tested_total":int(old.get("tested_total",0))+len(seen),"archive":ranked[:12],"holdout_initial":old.get("holdout_initial"),"demo_feedback":{k:v for k,v in feedback.items() if k.startswith("leader-evo:"+sym+":")}}
    if ranked and not result["holdout_initial"]:
        e=ranked[0];p=e["params"];sig=valid&(pred>=p["threshold"])
        test=leader_replay.simulate(a,sig,c2,len(a),p["tp"],p["stop"],p["step"],p["adds"],p["hold"])
        result["holdout_initial"]={"key":e["key"],"metrics":test,"generation":generation}
    return result
def live(a,report):
    f=leader_imitation.features(a)
    if f is None or not f[1][-1]:return None
    return float(leader_imitation.score(f[0][-1:],np.asarray(report["mu"]),np.asarray(report["sd"]),np.asarray(report["w"]))[0])
def selftest():
    p={"entry_score":[.7],"tp":[.02],"hold":[6],"step":[.03],"adds":[2],"stop":[.08],"add_examples":3}
    v=sample(np.random.default_rng(1),p)
    assert v["tp"]==.02 and v["adds"]==2 and v["step"]==.03 and v["hold"]==6
