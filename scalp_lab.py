"""Bounded second/minute research on observed public trades, paper only.
No order placement, no simulated fills at unseen historical prices.
A passive entry needs a later opposing trade strictly through its limit.
That is conservative evidence, not a guaranteed queue fill.
"""
import math,time,threading,logging
from collections import deque
import store,risk,paper_exec
LOCK=threading.RLock()
CORE=("BTCUSDT","ETHUSDT","SOLUSDT")
WINDOWS=(1,5,15,60,180,300)
HORIZONS=(15,30,60,180)
FAMILIES=("momentum","absorption","liquidity_sweep","depth_shift","passive")
SERIES={};IDS={};EPOCH={};ACTIVE={};VIEW={};LATEST={}
def wanted(cat,sym):
    return cat in ("linear","spot") and sym in CORE
def subscription(cat,sym):
    if not wanted(cat,sym):return
    with LOCK:
        key=(cat,sym);EPOCH[key]=int(time.time()*1000);SERIES[key]={};IDS[key]=(set(),deque())
def disconnect(cat):
    with LOCK:
        for k in list(EPOCH):
            if k[0]==cat:del EPOCH[k];SERIES.pop(k,None);IDS.pop(k,None)
def ingest(cat,sym,ticks):
    if not wanted(cat,sym):return
    key=(cat,sym);now=int(time.time()*1000)
    with LOCK:
        start=EPOCH.get(key)
        if start is None:return
        rows=SERIES[key];ids,q=IDS[key]
        for x in ticks:
            try:
                t=int(x["T"]);p=float(x["p"]);v=float(x["v"]);side=x["S"];uid=str(x["i"])
                if not uid or not 0<p<1e12 or not 0<v<1e15 or side not in ("Buy","Sell") or not max(start,now-2000)<=t<=now+1000:continue
                if uid in ids:continue
                ids.add(uid);q.append(uid)
                if len(q)>16384:ids.discard(q.popleft())
                sec=t//1000
                # [first_ms,last_ms,open,high,low,close,buy_qty,sell_qty,
                # buy_quote,sell_quote,count,min_sell,max_buy,sell_at_min,buy_at_max]
                b=rows.setdefault(sec,[t,t,p,p,p,p,0.,0.,0.,0.,0,None,None,0.,0.])
                if t<b[0]:b[0]=t;b[2]=p
                if t>=b[1]:b[1]=t;b[5]=p
                b[3]=max(b[3],p);b[4]=min(b[4],p);b[10]+=1
                if side=="Buy":
                    b[6]+=v;b[8]+=p*v
                    if b[12] is None or p>b[12]:b[12]=p;b[14]=v
                    elif p==b[12]:b[14]+=v
                else:
                    b[7]+=v;b[9]+=p*v
                    if b[11] is None or p<b[11]:b[11]=p;b[13]=v
                    elif p==b[11]:b[13]+=v
            except (KeyError,TypeError,ValueError,OverflowError):continue
        if len(rows)>950:
            for sec in list(rows):
                if sec<now//1000-900:del rows[sec]
def window(rows,end,seconds):
    parts=[(k,b) for k,b in rows.items() if end-seconds<=k<end]
    if not parts:return None
    parts.sort();b=[v for _,v in parts]
    return {"start":end-seconds,"end":end,"open":b[0][2],"high":max(x[3] for x in b),
        "low":min(x[4] for x in b),"close":b[-1][5],"buy":sum(x[6] for x in b),"sell":sum(x[7] for x in b),
        "buy_value":sum(x[8] for x in b),"sell_value":sum(x[9] for x in b),"trades":sum(x[10] for x in b),"observed_seconds":len(b)}
def features(rows,end,start,quote,prev):
    out={}
    mid=(quote["bid"]+quote["ask"])/2
    for n in WINDOWS:
        if start/1000>end-n:continue
        x=window(rows,end,n)
        if not x:continue
        vol=x["buy_value"]+x["sell_value"]
        prior=window(rows,end-n,n) if start/1000<=end-2*n else None
        move=x["close"]/x["open"]-1;flow=(x["buy_value"]-x["sell_value"])/max(vol,1e-12)
        sweep=0
        if prior:
            if x["low"]<prior["low"] and x["close"]>prior["low"]:sweep=1
            elif x["high"]>prior["high"] and x["close"]<prior["high"]:sweep=-1
        bd=quote["bid_depth"];ad=quote["ask_depth"]
        shift=0.
        if prev and prev["time"]>=end-5:
            shift=(bd-prev["bid_depth"])/max(bd+prev["bid_depth"],1e-12)-(ad-prev["ask_depth"])/max(ad+prev["ask_depth"],1e-12)
        out[n]={**x,"move":move,"flow":flow,"sweep":sweep,"depth":(bd-ad)/max(bd+ad,1e-12),
                "depth_shift":shift,"spread":(quote["ask"]-quote["bid"])/mid}
    return out
def signal(f,family,threshold):
    if family=="momentum":
        return 1 if f["flow"]>threshold and f["move"]>0 and f["depth"]>0 else -1 if f["flow"]<-threshold and f["move"]<0 and f["depth"]<0 else 0
    if family=="absorption":
        return 1 if f["flow"]<-threshold and f["move"]>=0 else -1 if f["flow"]>threshold and f["move"]<=0 else 0
    if family=="liquidity_sweep":return f["sweep"] if abs(f["flow"])>threshold/2 else 0
    if family=="depth_shift":
        return 1 if f["depth_shift"]>threshold and f["flow"]>0 else -1 if f["depth_shift"]<-threshold and f["flow"]<0 else 0
    if family=="passive":
        # Observe passive bid/ask entries when spread and book permit; no spoofing.
        return 1 if f["depth"]>threshold else -1 if f["depth"]<-threshold else 0
    return 0
def configs():
    # All models share the feed, not a wallet; fixed exploration grid + bounded evolution.
    return [(f,n,h,t) for f in FAMILIES for n in (1,5,15,60) for h in (15,60) for t in (.2,.45)]
def key_for(cat,sym,config):
    f,n,h,t=config;return "%s:%s:%s:%s:%s:%.4f"%(cat,sym,f,n,h,t)
def new_account(cat,sym,config):
    return {"cat":cat,"symbol":sym,"config":list(config),"balance":1000.,"equity":1000.,"peak":1000.,"dd":0.,
        "closed":0,"wins":0,"net":0.,"net2":0.,"signals":0,"rejected":0,"pending":None,"position":None,"last_eval":0,"last_trade":None}
def fee(cat,maker=False):
    # Conservative configurable estimates, not a promise of the user's fee tier.
    return .0015 if cat=="spot" else (.0002 if maker else .0006)
def quote_valid(q):
    return q and q["bid"]>0 and q["ask"]>=q["bid"] and q["bid_size"]>0 and q["ask_size"]>0 and q["ask"]/q["bid"]-1<=.002
def finish(a,p,q,now):
    side=p["side"];f=paper_exec.fill(q,-side,quantity=p["qty"])
    price=f["price"] if f else (q["bid"] if side==1 else q["ask"])*(1-side*.0001)
    net=side*p["qty"]*(price-p["price"])-p["qty"]*price*fee(a["cat"])
    a["equity"]=a["balance"]+net;a["peak"]=max(a["peak"],a["equity"])
    a["dd"]=max(a["dd"],1-a["equity"]/a["peak"])
    if not f:return
    if now-p["time"]<p["hold"] and side*(price/p["price"]-1)>-.003:return
    pnl=net-p["fee"];a["balance"]+=net;a["equity"]=a["balance"]
    a["closed"]+=1;a["wins"]+=int(pnl>0);ret=pnl/(p["qty"]*p["price"]);a["net"]+=ret;a["net2"]+=ret*ret
    a["last_trade"]={"time":now,"pnl":pnl,"return":ret,"side":side,"entry":p["price"],"exit":price,"duration":now-p["time"]}
    a["position"]=None
def step(a,f,q,rows,end,now):
    family,n,hold,threshold=a["config"]
    if not quote_valid(q):return
    if a["position"]:finish(a,a["position"],q,now);return
    p=a["pending"]
    if p:
        if now>p["expires"]:a["pending"]=None;a["rejected"]+=1;return
        if now<p["time"]+1:return
        side=p["side"];maker=p["maker"];amount=min(100.,a["balance"]*.1)
        if maker:
            price=p["limit"];qty=amount/price
            # Only trade-through at strictly better price than limit, after submission.
            # Require observed opposing volume at that price; no fill from touch.
            evidence=any(s>=p["first_second"] and ((side==1 and b[11] is not None and b[11]<price and b[13]>=qty) or (side==-1 and b[12] is not None and b[12]>price and b[14]>=qty)) for s,b in rows.items() if s<end)
            if not evidence:return
        else:
            fill=paper_exec.fill(q,side,notional=amount)
            if not fill:a["pending"]=None;a["rejected"]+=1;return
            price=fill["price"];qty=fill["qty"]
        cost=amount*fee(a["cat"],maker);a["balance"]-=cost;a["equity"]=a["balance"]
        a["position"]={"price":price,"qty":qty,"side":side,"fee":cost,"time":now,"hold":hold,"maker":maker,"latency_seconds":now-p["time"],"execution":fill if not maker else None};a["pending"]=None;return
    if not f or a["last_eval"]>=end or a["balance"]<20 or a["dd"]>.15:return
    a["last_eval"]=end
    side=signal(f,family,threshold)
    if not side or (a["cat"]=="spot" and side<0):return
    a["signals"]+=1
    a["pending"]={"side":side,"maker":family=="passive","limit":q["bid"] if side==1 else q["ask"],
        "time":now,"first_second":math.floor(now)+1,"expires":now+(10 if family=="passive" else 4)}
def score(a):
    n=a["closed"]
    if n<10:return -100.
    mean=a["net"]/n;sd=math.sqrt(max(0,a["net2"]/n-mean*mean))
    return mean-2*sd/math.sqrt(n)-a["dd"]*.1
def summary(accounts,now,feeds,errors):
    ranked=sorted(accounts.values(),key=score,reverse=True)
    families={}
    for a in ranked:
        f=a["config"][0];v=families.setdefault(f,{"models":0,"signals":0,"closed":0,"open":0,"wins":0})
        v["models"]+=1;v["signals"]+=a["signals"];v["closed"]+=a["closed"];v["open"]+=int(a["position"] is not None);v["wins"]+=a["wins"]
    return {"time":now,"models":len(accounts),"signals":sum(a["signals"] for a in ranked),"open":sum(a["position"] is not None for a in ranked),
        "closed":sum(a["closed"] for a in ranked),"pending":sum(a["pending"] is not None for a in ranked),"families":families,"feeds":feeds,"errors":errors,
        "top":[{"market":a["cat"],"symbol":a["symbol"],"config":a["config"],"closed":a["closed"],"wins":a["wins"],"equity":a["equity"],"score":score(a),"avg":a["net"]/max(1,a["closed"]),"drawdown":a["dd"]} for a in ranked[:15]]}
def worker(market):
    global VIEW
    saved=store.get("scalp_lab",{}) or {};accounts=saved.get("accounts",{});generation=saved.get("generation",0);last_evolve=saved.get("last_evolve",0)
    # Discard stale pending intents at restart, never invent their fills.
    for a in accounts.values():a["pending"]=None
    last_save=0.;previous={};last_bar_save=0.
    while True:
        try:
            now=time.time();end=int(now)-2;feeds={};errors={}
            for cat in ("linear","spot"):
                for sym in CORE:
                    key=(cat,sym);label=cat+":"+sym
                    try:
                        q=market.scalp_quote(cat,sym)
                        with LOCK:
                            start=EPOCH.get(key);rows={k:list(v) for k,v in SERIES.get(key,{}).items()}
                        if start is None or not q:continue
                        f=features(rows,end,start,q,previous.get(key));previous[key]=q
                        feeds[label]={"seconds":len(rows),"windows":{str(n):{k:v for k,v in x.items() if k in ("open","high","low","close","trades","flow","depth","spread")} for n,x in f.items()}}
                        for config in configs():
                            k=key_for(cat,sym,config)
                            if k not in accounts:accounts[k]=new_account(cat,sym,config)
                        for a in accounts.values():
                            if a["cat"]==cat and a["symbol"]==sym:step(a,f.get(a["config"][1]),q,rows,end,now)
                        if now-last_bar_save>=60:
                            # Persist actual 1s OHLCV aggregates, not raw tick IDs.
                            old=store.get("scalp_bars:"+label,[]) or []
                            by={int(x[0]):x for x in old}
                            by.update({k:[k,*v[:11]] for k,v in rows.items() if k<end})
                            store.put("scalp_bars:"+label,[by[k] for k in sorted(by)[-3600:]])
                    except Exception as e:errors[label]=str(e)[:160]
            if now-last_bar_save>=60:last_bar_save=now
            if now-last_evolve>=1800:
                # Keep original hypotheses and mutate thresholds of models with positive lower-confidence score.
                winners=sorted((a for a in accounts.values() if a["closed"]>=20 and score(a)>0),key=score,reverse=True)[:12]
                for a in winners:
                    if len(accounts)>=1152:break
                    f,n,h,t=a["config"]
                    for nt in (round(max(.1,t*.8),4),round(min(.9,t*1.2),4)):
                        c=(f,n,h,nt);k=key_for(a["cat"],a["symbol"],c)
                        if k not in accounts:accounts[k]=new_account(a["cat"],a["symbol"],c)
                if winners:generation+=1
                last_evolve=now
            if now-last_save>=30:
                view=summary(accounts,now,feeds,errors);view["generation"]=generation
                store.put("scalp_lab",{"accounts":accounts,"generation":generation,"last_evolve":last_evolve,"summary":view})
                VIEW=view;last_save=now
                logging.info("SCALP cycle: models=%s signals=%s pending=%s open=%s closed=%s generation=%s feeds=%s errors=%s",view["models"],view["signals"],view["pending"],view["open"],view["closed"],generation,list(feeds),errors)
        except Exception:logging.exception("Scalp lab cycle")
        time.sleep(1)
def status():return VIEW or (store.get("scalp_lab",{}) or {}).get("summary",{})
def selftest():
    q={"bid":100.,"ask":100.01,"bid_size":10.,"ask_size":10.,"bid_depth":1000.,"ask_depth":500.,"time":10,"bids":[[100.,10.]],"asks":[[100.01,10.]]}
    a=new_account("linear","BTCUSDT",("momentum",1,15,.2))
    f={"flow":.8,"move":.001,"depth":.5}
    step(a,f,q,{},10,10.)
    assert a["pending"] and not a["position"]
    step(a,f,q,{},10,10.5)
    assert not a["position"]
    step(a,f,q,{},11,11.1)
    assert a["position"]
    step(a,f,q,{},27,27.)
    assert a["closed"]==1 and a["balance"]<1000
    a=new_account("linear","BTCUSDT",("passive",1,15,.2))
    step(a,f,q,{},10,10.)
    step(a,f,q,{},12,12.)
    assert not a["position"]
