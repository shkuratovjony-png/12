"""Independent forward paper accounts. Public GET only; never accesses exchange credentials."""
import time, logging, math, copy
from datetime import datetime, timezone
import requests
import store, sir_live
INTERVALS=(1,5,15)
FEE=.0006
SLIP=.0002
BASE="https://api.bybit.com"
VIEW={str(i):{"status":"starting","equity":1000,"balance":1000} for i in INTERVALS}
SESSION=requests.Session()
META={}
BTC=None
def public(path,**params):
    r=SESSION.get(BASE+"/v5/market/"+path,params={"category":"linear",**params},timeout=8)
    r.raise_for_status()
    d=r.json()
    if d.get("retCode")!=0:raise RuntimeError("Public Bybit "+str(d.get("retCode")))
    time.sleep(.15)
    return d["result"]["list"]
def bars(sym,i,n,end):
    out={}
    until=end
    while len(out)<n:
        rows=public("kline",symbol=sym,interval=str(i),limit=min(1000,n-len(out)),end=until-1)
        if not rows:break
        for r in rows:
            if int(r[0])<until:out[int(r[0])]=(int(r[0]),*map(float,r[1:5]))
        old=min(int(r[0]) for r in rows)
        if old>=until:break
        until=old
    a=sorted(out.values())
    if len(a)<n or a[-1][0]!=end-i*60000 or any(y[0]-x[0]!=i*60000 for x,y in zip(a,a[1:])):
        raise ValueError("Incomplete closed candles "+sym)
    return a[-n:]
def meta(sym):
    if sym not in META or time.time()-META[sym][0]>3600:
        META[sym]=(time.time(),public("instruments-info",symbol=sym)[0])
    return META[sym][1]
def initial():
    return {"balance":1000.,"positions":{},"closed":[],"count":0,"wins":0,"fees":0.,"funding":0.,"gross":0.,"peak":1000.,"dd":0.,"month":None,"monthbase":1000.,"bar":0,"started":time.time(),"updated":0,"gaps":0,"history":[]}
def net(p,price):
    return p["side"]*p["qty"]*(price-p["entry"])
def quote(t,side,entry):
    # Long opens at ask, closes at bid; shorts opposite. Adverse slippage.
    buy=(side==1)==entry
    return float(t["ask1Price"] if buy else t["bid1Price"])*(1+SLIP if buy else 1-SLIP)
def equity(s,tickers):
    return s["balance"]+sum(net(p,float(tickers.get(sym,{}).get("markPrice") or p["mark"])) for sym,p in s["positions"].items())
def funding(s,p,t,now):
    # Actual published funding rates, mark at observation as notional approximation.
    while p["next_funding"] and now*1000>=p["next_funding"]:
        ts=p["next_funding"]
        rows=public("funding/history",symbol=p["symbol"],endTime=ts,limit=1)
        if not rows or int(rows[0]["fundingRateTimestamp"])!=ts:
            raise RuntimeError("Funding history pending "+p["symbol"])
        rate=float(rows[0]["fundingRate"])
        amount=-p["side"]*p["qty"]*float(t["markPrice"])*rate
        s["balance"]+=amount;s["funding"]+=amount;p["funding"]+=amount
        interval=int(meta(p["symbol"])["fundingInterval"])*60000
        p["next_funding"]=ts+interval
    advertised=int(t.get("nextFundingTime") or 0)
    if advertised>now*1000 and (not p["next_funding"] or p["next_funding"]>now*1000):
        p["next_funding"]=advertised
def close(s,sym,p,t,now,reason):
    px=quote(t,p["side"],False)
    gross=net(p,px);fee=px*p["qty"]*FEE
    result=gross-fee-p["entry_fee"]+p["funding"]
    s["balance"]+=gross-fee;s["fees"]+=fee;s["gross"]+=gross
    s["count"]+=1;s["wins"]+=int(result>0)
    s["closed"].append(dict(p,exit=px,closed=now,net=result,reason=reason,exit_fee=fee))
    del s["positions"][sym]
def manage(s,tickers,now):
    for sym,p in list(s["positions"].items()):
        t=tickers.get(sym)
        if not t:raise RuntimeError("Missing quote "+sym)
        funding(s,p,t,now)
        mark=float(t["markPrice"]);last=float(t["lastPrice"]);p["mark"]=mark
        side=p["side"]
        if side*(mark-p["sl"])<=0:close(s,sym,p,t,now,"SL")
        elif side*(last-p["tp"])>=0:close(s,sym,p,t,now,"TP")
def sizing(eq,risk,entry,stop,available,lot):
    dist=abs(entry-stop)
    q=min(eq*risk/(dist+FEE*(entry+stop)+SLIP*stop),available/(entry*(.1+FEE)),float(lot.get("maxMktOrderQty") or lot["maxOrderQty"]))
    return float(sir_live.tick_price(q,lot["qtyStep"]))
def enter(s,i,tickers,leaders,direction,now,end):
    side=-1 if direction=="short" else 1
    for sym in leaders:
        if len(s["positions"])>=2:break
        if sym in s["positions"]:continue
        t=tickers[sym]
        m=meta(sym);lot=m["lotSizeFilter"];tick=m["priceFilter"]["tickSize"]
        if float(m["leverageFilter"]["maxLeverage"])<10:continue
        bid=float(t["bid1Price"]);ask=float(t["ask1Price"])
        if not 0<bid<=ask or (ask-bid)/ask>.0015:continue
        rows=bars(sym,i,30,end)
        sig=sir_live.pattern(rows,side,"breakout" if side==-1 else "both")
        if not sig:continue
        # Refresh executable quote after candle request. Do not fill stale signals.
        t=public("tickers",symbol=sym)[0]
        bid=float(t["bid1Price"]);ask=float(t["ask1Price"])
        if not 0<bid<=ask or (ask-bid)/ask>.0015:continue
        if int(time.time()*1000)//(i*60000)*(i*60000)!=end:break
        entry=quote(t,side,True)
        stop=float(sir_live.tick_price(sig[0],tick,side==-1))
        dist=side*(entry-stop)
        if dist<=0 or dist/entry>=.08:continue
        tp=float(sir_live.tick_price(entry+side*2*dist,tick,side==1))
        if tp<=0:continue
        eq=equity(s,tickers);risk=.025 if eq<s["monthbase"] else .05
        reserved=sum(p["qty"]*p["entry"]/10 for p in s["positions"].values())
        qty=sizing(eq,risk,entry,stop,max(0,min(eq,s["balance"])-reserved),lot)
        if qty<float(lot["minOrderQty"]) or qty*entry<max(10,float(lot.get("minNotionalValue") or 5)):continue
        fee=qty*entry*FEE
        s["balance"]-=fee;s["fees"]+=fee
        s["positions"][sym]={"symbol":sym,"side":side,"qty":qty,"entry":entry,"mark":float(t["markPrice"]),"sl":stop,"tp":tp,"opened":time.time(),"entry_fee":fee,"funding":0.,"next_funding":int(t.get("nextFundingTime") or 0),"signal":sig[1],"risk":risk}
        logging.info("PAPER M%s OPEN %s side=%s qty=%s",i,sym,side,qty)
def get_regime(now):
    global BTC
    end=int(now//3600)*3600000
    if BTC is None or BTC[0]!=end:
        b=bars("BTCUSDT",60,2000,end)
        BTC=(end,sir_live.regime([r[4] for r in b])[0])
    return BTC[1]
def leaders(tickers,side,n):
    eligible=[t for t in tickers.values() if t["symbol"].endswith("USDT") and float(t.get("turnover24h") or 0)>=5000000 and float(t.get("bid1Price") or 0)>0 and float(t.get("ask1Price") or 0)>0 and side*float(t.get("price24hPcnt") or 0)>0]
    out=[]
    for t in sorted(eligible,key=lambda t:side*float(t["price24hPcnt"]),reverse=True):
        if meta(t["symbol"]).get("contractType")=="LinearPerpetual":
            out.append(t["symbol"])
            if len(out)>=n:break
    return out
def worker():
    global VIEW
    states={i:store.get("sir_paper_m"+str(i),None) or initial() for i in INTERVALS}
    logging.info("PAPER M1 M5 M15 ready; public data only")
    while True:
        try:
            now=time.time()
            tickers={t["symbol"]:t for t in public("tickers")}
            direction=get_regime(now)
            due=[i for i,s in states.items() if s["bar"]<int(now//(i*60))*i*60000]
            short=leaders(tickers,-1,2) if due and direction=="short" else []
            long=leaders(tickers,1,3) if due and direction=="long" else []
            for i,s in states.items():
                try:
                    # Work on a copy; commit complete accounting before publishing.
                    n=copy.deepcopy(s)
                    if n["updated"] and now-n["updated"]>45:n["gaps"]+=1
                    manage(n,tickers,now)
                    eq=equity(n,tickers)
                    month=datetime.fromtimestamp(now,timezone.utc).strftime("%Y-%m")
                    if n["month"]!=month:n["month"]=month;n["monthbase"]=eq
                    end=int(now//(i*60))*i*60000
                    if n["bar"]<end:
                        n["bar"]=end
                        if direction!="flat" and eq>=20 and now-end/1000<=min(180,i*60):
                            enter(n,i,tickers,short if direction=="short" else long,direction,now,end)
                    eq=equity(n,tickers);n["peak"]=max(n["peak"],eq)
                    n["dd"]=max(n["dd"],100*(1-eq/n["peak"]))
                    n["updated"]=now
                    if not n["history"] or now-n["history"][-1][0]>=60:
                        n["history"]=(n["history"]+[[now,eq]])[-1440:]
                    store.put("sir_paper_m"+str(i),n);states[i]=n
                    VIEW={**VIEW,str(i):{**n,"equity":eq,"regime":direction,"status":"active","short_leaders":short,"long_leaders":long,"positions":list(n["positions"].values()),"closed":n["closed"][-50:]}}
                except Exception as ex:
                    VIEW={**VIEW,str(i):{**VIEW[str(i)],"status":"error","error":str(ex)[:150]}}
                    logging.warning("PAPER M%s error: %s",i,str(ex)[:150])
            time.sleep(10)
        except Exception as ex:
            VIEW={k:{**v,"status":"error","error":str(ex)[:150]} for k,v in VIEW.items()}
            logging.warning("PAPER feed error: %s",str(ex)[:150])
            time.sleep(60)
def selftest():
    s=initial()
    p={"symbol":"TEST","side":1,"qty":2.,"entry":100.,"entry_fee":.12,"funding":-.01}
    s["positions"]["TEST"]=p;s["balance"]-=.13;s["fees"]+=.12;s["funding"]-=.01
    t={"bid1Price":"110","ask1Price":"111"}
    close(s,"TEST",p,t,1,"TP")
    assert s["count"]==1 and s["wins"]==1
    assert abs(s["balance"]-1000-s["closed"][0]["net"])<1e-8
    assert quote(t,-1,True)<110 and quote(t,-1,False)>111
