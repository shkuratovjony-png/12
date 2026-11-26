"""Sergey's discretionary video experiment, reconstructed as a public-data paper model.
Source 7viwWe2zq44: 01:19, 02:17–02:50, 05:02–09:21, 15:17–16:20,
20:43, 22:01–24:46, 28:25, 29:39–31:01. No private/order endpoints.
"""
import time, copy, logging
import requests
import store, sir_live, sir_paper, paper_feed
KEY="sergey_paper_v1"
FEE=.0006
SLIP=.0002
SESSION=requests.Session()
VIEW={"status":"starting","equity":1000,"balance":1000,"positions":[],"closed":[]}
META={}
def public(path,**params):
    return paper_feed.request(path,**params)
def instruments():
    global META
    META=paper_feed.instruments()
def bars(sym,i,now):
    end=int(now//(i*60))*i*60000
    shared=paper_feed.get_rows(sym,i,end)
    if shared:return shared
    raw=public("kline",symbol=sym,interval=str(i),end=end-1,limit=30)["list"]
    a=sorted([(int(r[0]),*map(float,r[1:5])) for r in raw if int(r[0])<end])
    if len(a)!=30 or a[-1][0]!=end-i*60000 or any(y[0]-x[0]!=i*60000 for x,y in zip(a,a[1:])):return None
    return a
def setup(rows,side,price):
    # Objective approximation of manually drawn levels; use closed bars plus observed current price.
    if not rows or len(rows)<30 or price<=0:return None
    h=[r[2] if side==1 else -r[3] for r in rows]
    l=[r[3] if side==1 else -r[2] for r in rows]
    c=[side*r[4] for r in rows]
    # Local trend, not BTC; higher lows/highs and direction over preceding 24 bars.
    if c[-1]<=c[-24]:return None
    px=side*price;tol=price*.0015
    hi=max(h[-8:]);touch=[j for j in range(18,30) if h[j]>=hi-price*.0025]
    lows=[min(l[-12:-8]),min(l[-8:-4]),min(l[-4:])]
    if len(touch)>=2 and touch[-1]-touch[0]>=2 and lows[-1]>lows[0] and c[-1]<=hi+tol and px>hi and px-hi<=price*.006:
        return (side*min(l[-5:]),"horizontal_breakout",hi*side)
    pivh=[j for j in range(17,29) if h[j]>=h[j-1] and h[j]>=h[j+1]]
    if len(pivh)>=2:
        a,b=pivh[-2:]
        if b-a>=2 and h[b]<h[a]:
            slope=(h[b]-h[a])/(b-a);line=h[b]+slope*(30-b)
            if c[-1]<=line-slope+tol and px>line and px-line<=price*.006 and px>=c[-1]:
                return (side*min(l[-5:]),"diagonal_breakout",line*side)
    pivl=[j for j in range(12,29) if l[j]<=l[j-1] and l[j]<=l[j+1]]
    if len(pivl)>=2:
        a,b=pivl[-2:]
        if b-a>=2 and l[b]>l[a]:
            slope=(l[b]-l[a])/(b-a);line=l[b]+slope*(29-b)
            if abs(l[-1]-line)<=price*.003 and c[-1]>side*rows[-1][1] and px>h[-1] and px-h[-1]<=price*.006:
                return (side*min(l[-3:]),"trend_bounce",line*side)
    # Also accept the existing candle-confirmed pattern, for setups already closed.
    sig=sir_live.pattern(rows,side,"both")
    if sig and side*(price-rows[-1][4])>=-price*.002 and abs(price-rows[-1][4])/price<=.006:
        return (sig[0],sig[1],rows[-1][4])
    return None
def initial():
    s=sir_paper.initial()
    s.update(session_start=0.,session_base=1000.,session_entries=0,used=[],reentry={},diagnostics={"cycles":0,"checked":0,"signals":0,"opened":0,"reasons":{},"last":[],"last_scan":0,"leaders":[]})
    return s
def note(d,sym,reason):
    d["reasons"][reason]=d["reasons"].get(reason,0)+1;d["last"].append({"symbol":sym,"reason":reason})
def funding(s,p,t,now):
    while p["next_funding"] and now*1000>=p["next_funding"]:
        ts=p["next_funding"]
        rows=public("funding/history",symbol=p["symbol"],endTime=ts,limit=1)["list"]
        if not rows or int(rows[0]["fundingRateTimestamp"])!=ts:raise RuntimeError("Funding pending "+p["symbol"])
        amount=-p["side"]*p["qty"]*float(t["markPrice"])*float(rows[0]["fundingRate"])
        s["balance"]+=amount;s["funding"]+=amount;p["funding"]+=amount
        p["next_funding"]=ts+p["funding_interval"]
    advertised=int(t.get("nextFundingTime") or 0)
    if advertised>now*1000 and (not p["next_funding"] or p["next_funding"]>now*1000):p["next_funding"]=advertised
def manage(s,ticks,now):
    for sym,p in list(s["positions"].items()):
        t=ticks.get(sym)
        if not t:raise RuntimeError("Missing quote "+sym)
        funding(s,p,t,now)
        p["mark"]=float(t["markPrice"]);last=float(t["lastPrice"]);side=p["side"]
        if side*(p["mark"]-p["sl"])<=0:
            sir_paper.close(s,sym,p,t,now,"SL")
            s["reentry"][sym]=now+60
        elif side*(last-p["tp"])>=0:sir_paper.close(s,sym,p,t,now,"TP")
def candidates(ticks,now):
    v=[t for t in ticks.values() if t["symbol"] in META and float(t.get("lastPrice") or 0)>0 and float(t.get("bid1Price") or 0)>0 and float(t.get("ask1Price") or 0)>0]
    ranked=sorted(v,key=lambda t:float(t.get("price24hPcnt") or 0))
    chosen=[(t["symbol"],1) for t in reversed(ranked[-2:]) if float(t["price24hPcnt"])>0]+[(t["symbol"],-1) for t in ranked[:2] if float(t["price24hPcnt"])<0]
    # Newly listed perpetuals, as in video; seven days is a reconstruction choice.
    new=sorted((t for t in v if 0<now*1000-int(META[t["symbol"]].get("launchTime") or 0)<7*86400000),key=lambda t:abs(float(t.get("price24hPcnt") or 0)),reverse=True)
    for t in new[:2]:
        if t["symbol"] not in [a for a,_ in chosen] and float(t.get("price24hPcnt") or 0)!=0:
            chosen.append((t["symbol"],1 if float(t["price24hPcnt"])>0 else -1))
    return chosen
def enter(s,sym,side,rows,i,t,d,now):
    m=META[sym];lot=m["lotSizeFilter"];tick=m["priceFilter"]["tickSize"]
    if float(m["leverageFilter"]["maxLeverage"])<10:note(d,sym,"leverage");return False
    bid=float(t["bid1Price"]);ask=float(t["ask1Price"])
    if not 0<bid<=ask or (ask-bid)/ask>.002:note(d,sym,"spread");return False
    sig=setup(rows,side,float(t["lastPrice"]))
    if not sig:return False
    d["signals"]+=1
    # Source suggests hiding SL behind swing by 0.5%; use this buffer.
    entry=sir_paper.quote(t,side,True)
    stop=float(sir_live.tick_price(sig[0]*(1-side*.005),tick,side==-1))
    dist=side*(entry-stop)
    if dist<=0 or dist/entry>=.08:note(d,sym,"stop_distance");return False
    tp=float(sir_live.tick_price(entry+side*2*dist,tick,side==1))
    if tp<=0:note(d,sym,"invalid_tp");return False
    eq=sir_paper.equity(s,{sym:t})
    reserved=sum(p["qty"]*p["entry"]/10 for p in s["positions"].values())
    avail=max(0,min(eq,s["balance"])-reserved)
    qty=sir_paper.sizing(s["session_base"],.05,entry,stop,avail,lot)
    if qty<float(lot["minOrderQty"]) or qty*entry<max(10,float(lot.get("minNotionalValue") or 5)):note(d,sym,"size");return False
    fee=qty*entry*FEE;s["balance"]-=fee;s["fees"]+=fee
    s["positions"][sym]={"symbol":sym,"side":side,"qty":qty,"entry":entry,"mark":float(t["markPrice"]),"sl":stop,"tp":tp,"opened":now,"entry_fee":fee,"funding":0.,"next_funding":int(t.get("nextFundingTime") or 0),"funding_interval":int(m["fundingInterval"])*60000,"signal":sig[1],"interval":i,"risk":.05}
    s["session_entries"]+=1;s["used"].append(sym);s["reentry"].pop(sym,None)
    d["opened"]+=1;note(d,sym,"opened")
    logging.info("SERGEY PAPER OPEN %s side=%s M%s qty=%s SL=%s TP=%s",sym,side,i,qty,stop,tp)
    return True
def worker():
    global VIEW
    s=store.get(KEY,None) or initial();last_meta=0.;cache={}
    logging.info("SERGEY PAPER ready; independent virtual account; no exchange orders")
    while True:
        try:
            now=time.time()
            if not META or now-last_meta>600:instruments();last_meta=now
            ticks={t["symbol"]:t for t in public("tickers")["list"]}
            n=copy.deepcopy(s);manage(n,ticks,now)
            eq=sir_paper.equity(n,ticks)
            if now-n["session_start"]>=86400 and not n["positions"]:
                n.update(session_start=now,session_base=eq,session_entries=0,used=[],reentry={})
                cache={}
            d=n["diagnostics"]
            if now-n["session_start"]<1200 and n["session_entries"]<5 and eq>=20:
                d["cycles"]+=1;d["last_scan"]=now;d["last"]=[]
                ranked=candidates(ticks,now)
                d["leaders"]=[sym+(" LONG" if side==1 else " SHORT") for sym,side in ranked]
                for sym,side in ranked:
                    if n["session_entries"]>=5:break
                    if sym in n["positions"]:note(d,sym,"already_open");continue
                    if sym in n["used"] and (sym not in n["reentry"] or n["used"].count(sym)>=2):note(d,sym,"session_used");continue
                    if n["reentry"].get(sym,0)>now:note(d,sym,"cooldown");continue
                    d["checked"]+=1
                    valid=False
                    for i in (15,5):
                        end=int(time.time()//(i*60))*i*60000
                        k=(sym,i)
                        if k not in cache or cache[k][0]!=end:cache[k]=(end,bars(sym,i,time.time()))
                        rows=cache[k][1]
                        if not rows:continue
                        valid=True
                        # Refresh quote after loading candle history.
                        fresh=public("tickers",symbol=sym)["list"][0]
                        if enter(n,sym,side,rows,i,fresh,d,time.time()):break
                    else:note(d,sym,"no_pattern" if valid else "stale_feed")
            eq=sir_paper.equity(n,ticks);n["peak"]=max(n["peak"],eq);n["dd"]=max(n["dd"],100*(1-eq/n["peak"]))
            n["updated"]=time.time()
            if not n["history"] or now-n["history"][-1][0]>=60:n["history"]=(n["history"]+[[now,eq]])[-1440:]
            store.put(KEY,n);s=n
            active=now-n["session_start"]<1200 and n["session_entries"]<5
            VIEW={**n,"equity":eq,"positions":list(n["positions"].values()),"closed":n["closed"][-50:],"status":"active","regime":"Поиск входов" if active else "Сопровождение / ожидание следующей сессии","error":None}
            time.sleep(10 if active or n["positions"] else 30)
        except Exception as e:
            VIEW={**VIEW,"status":"error","error":str(e)[:150]}
            logging.warning("SERGEY PAPER error %s",str(e)[:150]);time.sleep(30)
def selftest():
    s=initial();assert s["balance"]==1000 and s["session_entries"]==0
    assert setup([],1,100) is None
    note(s["diagnostics"],"TEST","no_pattern");assert s["diagnostics"]["reasons"]["no_pattern"]==1
