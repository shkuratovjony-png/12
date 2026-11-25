"""Source-inspired minute strategies, not an exact replication or claimed leader clone.
Independent fixed chronological train/validation/test, per-symbol and per-horizon.
No trading credentials, no external code execution. Demo signal via league.
"""
import time,logging,math
import numpy as np
import pandas as pd
import market,store,league
BAR=60000
SYMS=("BTCUSDT","ETHUSDT","SOLUSDT")
VIEW={}
SOURCES={"candle_turn":"https://doi.org/10.1016/j.heliyon.2023.e14236","momentum_reversal":"https://doi.org/10.5195/ledger.2021.213","volume_reversal":"https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/Strategy005.py"}
def bars(kind,sym,end,limit):
    raw=market.request("/v5/market/kline",category=kind,symbol=sym,interval="1",end=end,limit=limit)["list"]
    return sorted([[int(x[0])]+[float(v) for v in x[1:6]] for x in raw if int(x[0])+BAR<=end+1 and all(math.isfinite(float(v)) for v in x[1:6])],key=lambda r:r[0])
def signals(rows):
    a=np.asarray(rows,float);t,o,h,l,c,v=a.T
    s=pd.Series(c);vol=pd.Series(v);d=s.diff()
    up=d.clip(lower=0).ewm(alpha=1/14,adjust=False).mean();dn=(-d.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rsi=(100*up/(up+dn).replace(0,np.nan)).to_numpy()
    e8=s.ewm(span=8,adjust=False).mean().to_numpy();e24=s.ewm(span=24,adjust=False).mean().to_numpy()
    rv=(vol/vol.shift(1).rolling(30).mean().replace(0,np.nan)).to_numpy()
    r5=s.pct_change(5).to_numpy();r15=s.pct_change(15).to_numpy()
    out={}
    out["candle_turn"]=np.where((t//BAR+1)%15==0,1,0)
    for x in (.002,.004,.006):
        out["momentum_"+str(x)]=np.where((r5>x)&(e8>e24),1,np.where((r5<-x)&(e8<e24),-1,0))
        out["reversal_"+str(x)]=np.where((r15<-x)&(rsi<35)&(d.to_numpy()>0),1,np.where((r15>x)&(rsi>65)&(d.to_numpy()<0),-1,0))
    for x in (2.,3.,4.):
        out["volume_reversal_"+str(x)]=np.where((rv>x)&(rsi<35)&(c>o)&(c<e24),1,np.where((rv>x)&(rsi>65)&(c<o)&(c>e24),-1,0))
    gap=np.r_[0,np.cumsum(np.diff(t)!=BAR)]
    valid=np.zeros(len(a),bool);valid[60:]=gap[60:]==gap[:-60]
    return a,{k:np.where(valid,sig,0) for k,sig in out.items()}
def measure(a,sig,kind,hold,start,end):
    cost=.0039 if kind=="spot" else .0019
    last=-1;rets=[]
    for i in np.flatnonzero(sig[start:end])+start:
        if i<=last or i+hold>=end or a[i+hold,0]-a[i,0]!=hold*BAR:continue
        side=int(sig[i])
        if kind=="spot" and side<0:continue
        entry=a[i+1,1]
        if entry<=0:continue
        window=a[i+1:i+hold+1]
        stop=.005
        touched=np.min(window[:,3])<=entry*(1-stop) if side>0 else np.max(window[:,2])>=entry*(1+stop)
        ret=(-stop if touched else side*(a[i+hold,4]/entry-1))-cost
        rets.append(ret);last=i+hold
    if not rets:return {"trades":0,"mean":0.,"net":0.,"dd":0.,"score":-1.}
    r=np.asarray(rets);curve=np.cumprod(np.r_[1.,1+r*.1])
    return {"trades":len(r),"mean":float(r.mean()),"net":float(curve[-1]-1),"dd":float(np.max(1-curve/np.maximum.accumulate(curve))),"score":float(r.mean()-r.std()/np.sqrt(len(r)))}
def train(rows,kind):
    a,ss=signals(rows);n=len(a);c1=int(n*.6);c2=int(n*.8);allr=[]
    for name,sig in ss.items():
        for h in (1,3,5):
            tr=measure(a,sig,kind,h,60,c1)
            allr.append((name,h,tr))
    # One candidate per family chosen using training ONLY. Test never chooses parameters.
    best={}
    for name,h,tr in allr:
        family="volume_reversal" if name.startswith("volume_") else name.split("_")[0]
        if name=="candle_turn":family=name
        if tr["trades"]<20:continue
        if family not in best or tr["score"]>best[family][2]["score"]:best[family]=(name,h,tr)
    out=[]
    for name,h,tr in best.values():
        val=measure(a,ss[name],kind,h,c1,c2);test=measure(a,ss[name],kind,h,c2,n)
        ok=all(x["trades"]>=10 and x["mean"]>0 and x["score"]>0 and x["dd"]<=.05 for x in (tr,val,test))
        out.append({"name":name,"hold":h,"train":tr,"validation":val,"test":test,"approved":ok})
    return {"time":time.time(),"rows":n,"last_bar":int(a[-1,0]),"candidates":len(allr),"results":out}
def worker():
    global VIEW
    reports=store.get("source_lab_v1",{}) or {}
    keys=[(kind,sym) for kind in ("linear","spot") for sym in SYMS]
    cache={};last={};cursor=0
    while True:
        try:
            kind,sym=keys[cursor%len(keys)];cursor+=1;k=kind+":"+sym
            end=int(time.time()*1000//BAR)*BAR-1
            if k not in reports:
                allrows={};pos=end
                for _ in range(11):
                    rr=bars(kind,sym,pos,1000)
                    if not rr:break
                    allrows.update({r[0]:r for r in rr});pos=rr[0][0]-1
                    time.sleep(.6)
                rows=[allrows[t] for t in sorted(allrows) if t>=end-7*86400000]
                if len(rows)>=3000:
                    reports[k]=train(rows,kind);store.put("source_lab_v1",reports)
                    logging.info("SOURCE LAB %s rows=%s reports=%s",k,len(rows),reports[k]["results"])
            report=reports.get(k)
            if report and any(m["approved"] for m in report["results"]):
                rows=bars(kind,sym,end,100)
                if len(rows)>=65 and 0<=time.time()*1000-rows[-1][0]-BAR<15000 and rows[-1][0]>last.get(k,0):
                    a,ss=signals(rows);last[k]=rows[-1][0]
                    for m in report["results"]:
                        if not m["approved"]:continue
                        side=int(ss[m["name"]][-1])
                        if kind=="spot" and side<0:continue
                        if side:
                            sid="source:"+k+":"+m["name"]+":"+str(m["hold"])
                            now=time.time()
                            league.publish(sid,kind,sym,side,{"source_lab":m["name"]},now,now+12,m["hold"]*60,.005)
            now=time.time()
            ranking=[]
            for key,report in reports.items():
                cat,sym=key.split(":")
                for m in report["results"]:
                    if not m["approved"]:continue
                    sid="source:"+key+":"+m["name"]+":"+str(m["hold"])
                    ranking.append({"key":sid,"market":cat,"symbol":sym,"family":"source","eligible":False,"pilot":False,"historical":True,"historical_score":min(m["validation"]["mean"],m["test"]["mean"]),"trades":0,"net":0.,"score":min(m["validation"]["score"],m["test"]["score"]),"drawdown":0.,"tier":"practice","allocation":.025})
            league.update("source_lab",ranking)
            VIEW={"time":now,"sources":SOURCES,"reports":reports,"approved":len(ranking),"markets":len(reports)}
        except Exception:logging.exception("SOURCE LAB error")
        time.sleep(2)
