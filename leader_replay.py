"""Leader-inspired research, distinct from the unknown original entry rules.
Historical closed-bar signals, one position per symbol, bounded grid variants.
No orders or leverage; evaluates costs and conservative intrabar stop priority.
"""
import time,math,logging
import numpy as np
import pandas as pd
import market,store
BAR=900000
SYMS=("SUIUSDT","QNTUSDT","TIAUSDT","JUPUSDT","ICPUSDT","HYPEUSDT")
VIEW={}
def fetch(sym,state):
    k="leader_replay_bars:"+sym
    m=state.setdefault(sym,{"end":int(time.time()*1000//BAR)*BAR-1,"pages":0,"done":False})
    if "anchor" not in m:m["anchor"]=m["end"]
    if m["done"]:return
    cut=m["anchor"]-150*86400000
    raw=market.request("/v5/market/kline",category="linear",symbol=sym,interval="15",end=m["end"],limit=1000)["list"]
    rows=[[int(x[0])]+[float(z) for z in x[1:6]] for x in raw if cut<=int(x[0])<=m["end"] and all(math.isfinite(float(z)) for z in x[1:6])]
    if rows:
        store.put(k+":"+str(m["pages"]),rows);m["pages"]+=1
    if not raw or min(int(x[0]) for x in raw)<=cut:m["done"]=True
    else:m["end"]=min(int(x[0]) for x in raw)-1
    store.put("leader_replay_progress_v1",state)
def data(sym,m):
    chunks=store.get_many(["leader_replay_bars:"+sym+":"+str(i) for i in range(m["pages"])])
    rows={r[0]:r for rs in chunks.values() for r in rs}
    return np.asarray([rows[t] for t in sorted(rows)],float)
def features(a):
    c=pd.Series(a[:,4]);ret4=c.pct_change(4).to_numpy();ret16=c.pct_change(16).to_numpy()
    ema=c.ewm(span=24,adjust=False).mean().to_numpy()
    gap=np.r_[0,np.cumsum(np.diff(a[:,0])!=BAR)]
    valid=np.zeros(len(a),bool);valid[32:]=gap[32:]==gap[:-32]
    return ret4,ret16,ema,valid
def simulate(a,sig,start,end,tp,stop,step,adds,hold):
    # All allocations are fractions of the planned trade budget; no borrowing.
    # If stop, TP and a grid level share a bar, stop wins; new add is not
    # allowed to hit TP in the same bar. No overlap within an instrument.
    results=[];i=start;cost=.002
    while i<end-1:
        if not sig[i] or a[i+1,0]-a[i,0]!=BAR:i+=1;continue
        entry=a[i+1,1];qty=1/entry/(adds+1);spent=1/(adds+1);n=0;avg=entry
        j=i+1;exit_price=entry
        while j<min(end,i+hold+1):
            t,o,h,l,c,v=a[j]
            if j>i+1 and t-a[j-1,0]!=BAR:
                exit_price=o;break
            sl=entry*(1-stop);target=avg*(1+tp)
            if l<=sl:exit_price=min(o,sl);break
            level=entry*(1-step*(n+1))
            if n<adds and l<=level:
                fill=min(o,level);qty+=1/(adds+1)/fill;spent+=1/(adds+1);n+=1;avg=spent/qty
                exit_price=c;j+=1;continue
            if h>=target:exit_price=target;break
            exit_price=c;j+=1
        net=qty*exit_price-spent-cost*spent
        results.append(net);i=max(i+1,j+1)
    if not results:return {"n":0,"mean":0.,"return":0.,"dd":0.,"score":-1.}
    r=np.asarray(results);curve=np.cumprod(np.r_[1.,1.+.1*r])
    return {"n":len(r),"mean":float(r.mean()),"return":float(curve[-1]-1),"dd":float(np.max(1-curve/np.maximum.accumulate(curve))),"score":float(r.mean()-r.std()/np.sqrt(len(r)))}
def train(a,grid_only=False):
    r4,r16,ema,valid=features(a);c=a[:,4];o=a[:,1];n=len(a);c1=int(n*.6);c2=int(n*.8)
    # Starting hypotheses, not recovered exact leader rules. Include no-grid control.
    candidates=[]
    for dip in (.01,.02,.03):
        for recovery in (False,True):
            sig=valid&(r4<=-dip)&(r16>-.10)
            if recovery:sig&=c>o
            for tp in (.01,.02,.03):
                for stop,step,adds in ((.015,0.,0),(.035,0.,0),(.055,.03,1),(.075,.03,2)):
                    if grid_only and not adds:continue
                    for hold in (4,12,24):
                        p=(tp,stop,step,adds,hold)
                        tr=simulate(a,sig,64,c1,*p)
                        if tr["n"]>=20:candidates.append((tr["score"],dip,recovery,p,tr))
    if not candidates:return {"rows":n,"candidates":0,"approved":False}
    _,dip,recovery,p,tr=max(candidates,key=lambda x:x[0])
    sig=valid&(r4<=-dip)&(r16>-.10)
    if recovery:sig&=c>o
    val=simulate(a,sig,c1,c2,*p);test=simulate(a,sig,c2,n,*p)
    approved=all(x["n"]>=10 and x["mean"]>0 and x["score"]>0 and x["dd"]<=.05 for x in (tr,val,test))
    return {"rows":n,"candidates":len(candidates),"dip":dip,"recovery":recovery,"tp":p[0],"stop":p[1],"grid_step":p[2],"adds":p[3],"hold_minutes":p[4]*15,"train":tr,"validation":val,"test":test,"approved":approved}
def worker():
    global VIEW
    progress=store.get("leader_replay_progress_v1",{}) or {}
    reports=store.get("leader_replay_results_v1",{}) or {}
    while True:
        try:
            for sym in SYMS:
                if sym in reports:continue
                fetch(sym,progress)
                m=progress[sym]
                if m["done"]:
                    a=data(sym,m)
                    if len(a)>=1000:
                        reports[sym]=train(a);store.put("leader_replay_results_v1",reports)
                        logging.info("LEADER REPLAY %s %s",sym,reports[sym])
                    else:
                        reports[sym]={"rows":len(a),"approved":False,"reason":"insufficient data"};store.put("leader_replay_results_v1",reports)
                VIEW={"time":time.time(),"progress":progress,"reports":reports,"approved":sum(bool(x.get("approved")) for x in reports.values()),"mode":"historical hypotheses only; no execution"}
                time.sleep(2)
        except Exception:logging.exception("LEADER REPLAY error")
        time.sleep(60 if len(reports)==len(SYMS) else 5)
