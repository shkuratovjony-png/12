"""Trade-based order flow: bounded 1bp price histogram, verified closed bars."""
import math,time,threading,logging
from collections import deque
import store
BAR=900000
LOCK=threading.RLock()
START={};BARS={};SEEN={};DONE={};LAST={}
COUNTS={"trades":0,"duplicates":0,"saved":0,"complete":0}
def subscription(cat,sym):
    with LOCK:START[cat,sym]=int(time.time()*1000)
def disconnect(cat):
    with LOCK:
        for k in list(START):
            if k[0]==cat:del START[k]
        for k,b in BARS.items():
            if k[0]==cat:b["gap"]=True
def ingest(cat,sym,ticks):
    now=int(time.time()*1000);key=(cat,sym)
    with LOCK:
        if key not in START:return
        ids,q=SEEN.setdefault(key,(set(),deque()))
        for x in ticks:
            try:
                t=int(x["T"]);p=float(x["p"]);v=float(x["v"]);side=x["S"];uid=str(x["i"])
                if not uid or not 0<p<1e12 or not 0<v<1e15 or side not in ("Buy","Sell"):continue
                if not now-2*BAR<=t<=now+5000:continue
                bar=t//BAR*BAR;k=(cat,sym,bar)
                if bar<=DONE.get(key,-1):continue
                if uid in ids:COUNTS["duplicates"]+=1;continue
                ids.add(uid);q.append(uid)
                if len(q)>8192:ids.discard(q.popleft())
                b=BARS.setdefault(k,{"bar":bar,"gap":START[key]>bar,"buy":0.,"sell":0.,"bv":0.,"sv":0.,"count":0,"hist":{},"large":0.})
                j=int(math.floor(math.log(p)/.0001));hist=b["hist"]
                if j not in hist and len(hist)>=4096:b["gap"]=True;continue
                h=hist.setdefault(j,[0.,0.]);i=0 if side=="Buy" else 1;h[i]+=v
                b["buy" if i==0 else "sell"]+=v;b["bv" if i==0 else "sv"]+=p*v
                b["count"]+=1;b["large"]+=p*v if p*v>=10000 else 0.
                COUNTS["trades"]+=1
            except (KeyError,ValueError,TypeError,OverflowError):continue
        for k in list(BARS):
            if k[2]<now-4*BAR:del BARS[k]
def summarize(b,expected,close,now):
    volume=b["buy"]+b["sell"];coverage=volume/expected if expected>0 else 0.
    ok=not b["gap"] and b["count"]>0 and .995<=coverage<=1.005
    r={"bar":b["bar"],"observed":now,"complete":ok,"coverage":coverage,"trades":b["count"]}
    if not ok:return r
    hist=b["hist"];keys=sorted(hist);vol=[sum(hist[k]) for k in keys]
    i=max(range(len(keys)),key=lambda i:vol[i]);left=right=i;mass=vol[i]
    while mass<.7*volume and (left>0 or right<len(keys)-1):
        if right<len(keys)-1 and (left==0 or vol[right+1]>vol[left-1]):right+=1;mass+=vol[right]
        else:left-=1;mass+=vol[left]
    poc=math.exp((keys[i]+.5)*.0001);vah=math.exp((keys[right]+1)*.0001);val=math.exp(keys[left]*.0001)
    value=b["bv"]+b["sv"]
    return dict(r,delta=b["buy"]-b["sell"],volume=volume,flow_delta=(b["buy"]-b["sell"])/volume,flow_quote_delta=(b["bv"]-b["sv"])/value,
        flow_trade_count=math.log1p(b["count"]),flow_large_share=b["large"]/value,flow_avg_trade=math.log1p(value/b["count"]),
        flow_vwap_gap=1-value/volume/close,flow_poc_gap=1-poc/close,flow_vah_gap=1-vah/close,flow_val_gap=1-val/close,
        flow_footprint_imbalance=sum(1 if a>3*b else -1 if b>3*a else 0 for a,b in hist.values())/len(hist),poc=poc,vah=vah,val=val)
def writer(market):
    while True:
        try:
            now=int(time.time()*1000)
            with LOCK:keys=[k for k in BARS if k[2]+BAR+15000<=now]
            for k in keys:
                cat,sym,bar=k
                candle=next((r for r in market.ws_bars(cat,sym) if r[0]==bar),None)
                if not candle:continue
                with LOCK:
                    b=BARS.pop(k,None)
                    if b is not None:DONE[cat,sym]=max(bar,DONE.get((cat,sym),-1))
                if b is None:continue
                row=summarize(b,candle[5],candle[4],now);key="flow:"+cat+":"+sym
                old=store.get(key,[]) or []
                if not any(x["bar"]==bar for x in old):
                    store.put(key,sorted(old+[row],key=lambda x:x["bar"])[-3000:])
                    with LOCK:
                        COUNTS["saved"]+=1;COUNTS["complete"]+=int(row["complete"]);LAST[cat+":"+sym]=row
                    logging.info("FLOW %s %s trades=%s coverage=%.5f complete=%s",cat,sym,row["trades"],row["coverage"],row["complete"])
            store.put("flow_status",status())
        except Exception:logging.exception("Flow storage error")
        time.sleep(15)
def status():
    with LOCK:return dict(COUNTS,time=time.time(),active_bars=len(BARS),last_closed=dict(LAST),bin_width_bps=1)
def selftest():
    b={"bar":0,"gap":False,"buy":4.,"sell":1.,"bv":400.,"sv":101.,"count":2,"hist":{46050:[4.,0.],46060:[0.,1.]},"large":0.}
    r=summarize(b,5.,100.,BAR+15000)
    assert r["complete"] and abs(r["flow_delta"]-.6)<1e-12
    assert not summarize(b,10.,100.,BAR+15000)["complete"]
    b["gap"]=True
    assert not summarize(b,5.,100.,BAR+15000)["complete"]
