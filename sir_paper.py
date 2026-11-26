"""Independent forward paper accounts. Public GET only; never accesses exchange credentials."""
import time, logging, math, copy
from datetime import datetime, timezone
import requests
import store, sir_live, paper_feed, short1042
INTERVALS=(1,5,15)
FEE=.0006
SLIP=.0002
BASE="https://api.bybit.com"
VIEW={str(i):{"status":"starting","equity":1000,"balance":1000} for i in INTERVALS}
SESSION=requests.Session()
META={}
BTC=None
def public(path,**params):
    return paper_feed.request(path,**params)["list"]
def bars(sym,i,n,end):
    if i in paper_feed.INTERVALS:
        return paper_feed.get_rows(sym,i,end,n)
    out={};until=end
    while len(out)<n:
        rows=public("kline",symbol=sym,interval=str(i),limit=min(1000,n-len(out)),end=until-1)
        if not rows:break
        for r in rows:
            if int(r[0])<until:out[int(r[0])]=(int(r[0]),*map(float,r[1:5]))
        old=min(int(r[0]) for r in rows)
        if old>=until:break
        until=old
    a=sorted(out.values())
    if not paper_feed.valid_rows(a,n,end,i):raise ValueError("Incomplete closed candles "+sym)
    return a[-n:]
def meta(sym):
    m=paper_feed.META.get(sym)
    if m:return m
    return public("instruments-info",symbol=sym)[0]
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
def diagnostics(s):
    return s.setdefault("diagnostics",{"cycles":0,"checked":0,"signals":0,"opened":0,"reasons":{},"last":[],"last_scan":0,"leaders":[]})
def note(d,sym,reason):
    d["reasons"][reason]=d["reasons"].get(reason,0)+1
    d["last"].append({"symbol":sym,"reason":reason})
    d["last"]=d["last"][-20:]
def enter(s,i,tickers,leaders,direction,now,end):
    d=diagnostics(s)
    side=-1
    for sym in leaders:
        if len(s["positions"])>=short1042.SLOTS:note(d,sym,"slots_full");break
        if sym in s["positions"]:note(d,sym,"already_open");continue
        d["checked"]+=1
        t=tickers[sym]
        m=meta(sym);lot=m["lotSizeFilter"];tick=m["priceFilter"]["tickSize"]
        if float(m["leverageFilter"]["maxLeverage"])<10:note(d,sym,"leverage");continue
        bid=float(t["bid1Price"]);ask=float(t["ask1Price"])
        if not 0<bid<=ask or (ask-bid)/ask>.0015:note(d,sym,"spread");continue
        stop,kind=short1042.signal(sym,i,end)
        if stop is None:note(d,sym,kind);continue
        d["signals"]+=1
        # Refresh executable quote after candle request. Do not fill stale signals.
        t=public("tickers",symbol=sym)[0]
        bid=float(t["bid1Price"]);ask=float(t["ask1Price"])
        if not 0<bid<=ask or (ask-bid)/ask>.0015:note(d,sym,"spread");continue
        if int(time.time()*1000)//(i*60000)*(i*60000)!=end:note(d,sym,"late");break
        entry=quote(t,side,True)
        stop=float(sir_live.tick_price(stop,tick,True))
        dist=side*(entry-stop)
        if not short1042.stop_ok(entry,stop):note(d,sym,"stop_distance");continue
        tp=float(sir_live.tick_price(entry+side*2*dist,tick,side==1))
        if tp<=0:note(d,sym,"invalid_tp");continue
        eq=equity(s,tickers);risk=short1042.risk(eq,s["monthbase"],short1042.macro(end/1000)["up6"])
        reserved=sum(p["qty"]*p["entry"]/10 for p in s["positions"].values())
        qty=sizing(eq,risk,entry,stop,max(0,min(eq,s["balance"])-reserved),lot)
        if qty<float(lot["minOrderQty"]) or qty*entry<max(10,float(lot.get("minNotionalValue") or 5)):note(d,sym,"size");continue
        fee=qty*entry*FEE
        s["balance"]-=fee;s["fees"]+=fee
        s["positions"][sym]={"symbol":sym,"side":side,"qty":qty,"entry":entry,"mark":float(t["markPrice"]),"sl":stop,"tp":tp,"opened":time.time(),"entry_fee":fee,"funding":0.,"next_funding":int(t.get("nextFundingTime") or 0),"signal":kind,"risk":risk}
        d["opened"]+=1;note(d,sym,"opened")
        logging.info("SHORT1042 PAPER M%s OPEN %s side=%s qty=%s",i,sym,side,qty)
def get_regime(now):
    return "short" if short1042.macro(now)["stable"] else "flat"
def key(i):return "short1042_paper_m"+str(i)
def worker():
    global VIEW
    states={i:store.get(key(i),None) or initial() for i in INTERVALS}
    logging.info("SHORT1042 PAPER M1 M5 M15 ready; independent 1000 USDT accounts; no exchange orders")
    while True:
        try:
            now=time.time()
            tickers={t["symbol"]:t for t in public("tickers")}
            # Reconcile exits and persist before doing potentially slow research.
            for i,s in list(states.items()):
                try:
                    n=copy.deepcopy(s)
                    if n["updated"] and now-n["updated"]>45:n["gaps"]+=1
                    manage(n,tickers,now)
                    eq=equity(n,tickers);month=datetime.fromtimestamp(now,timezone.utc).strftime("%Y-%m")
                    if n["month"]!=month:n["month"]=month;n["monthbase"]=eq
                    n["peak"]=max(n["peak"],eq);n["dd"]=max(n["dd"],100*(1-eq/n["peak"]));n["updated"]=now
                    if not n["history"] or now-n["history"][-1][0]>=60:n["history"]=(n["history"]+[[now,eq]])[-1440:]
                    store.put(key(i),n);states[i]=n
                    VIEW={**VIEW,str(i):{**n,"equity":eq,"regime":VIEW[str(i)].get("regime","waiting"),"status":"active","model":"SHORT 1042","positions":list(n["positions"].values()),"closed":n["closed"][-50:]}}
                except Exception as ex:
                    VIEW={**VIEW,str(i):{**VIEW[str(i)],"status":"error","error":str(ex)[:150]}}
                    logging.warning("SHORT1042 PAPER M%s manage: %s",i,str(ex)[:150])
            now=time.time();scan_now=now-5
            due=[i for i,s in states.items() if s["bar"]<int(scan_now//(i*60))*i*60000]
            if due:
                macro=short1042.macro(scan_now)
                direction="short" if macro["stable"] else "flat"
                ranked,universe=short1042.rank(tickers.values(),paper_feed.instruments())
                for i in due:
                    s=states[i];n=copy.deepcopy(s)
                    try:
                        end=int(scan_now//(i*60))*i*60000
                        n["bar"]=end;d=diagnostics(n);d["cycles"]+=1;d["last_scan"]=time.time();d["last"]=[]
                        d["leaders"]=[t["symbol"] for t in ranked];d["universe"]=universe;d["eligible"]=len(ranked)
                        eq=equity(n,tickers)
                        if direction!="short":note(d,"BTCUSDT","unstable_btc")
                        elif eq<20:note(d,"—","low_equity")
                        elif time.time()-end/1000>min(180,i*60) or int(time.time()//(i*60))*i*60000!=end:note(d,"—","late")
                        elif not ranked:note(d,"—","no_leaders")
                        else:enter(n,i,tickers,d["leaders"],direction,now,end)
                        eq=equity(n,tickers);n["peak"]=max(n["peak"],eq);n["dd"]=max(n["dd"],100*(1-eq/n["peak"]))
                        store.put(key(i),n);states[i]=n
                        VIEW={**VIEW,str(i):{**n,"equity":eq,"regime":direction,"macro":macro,"status":"active","model":"SHORT 1042","positions":list(n["positions"].values()),"closed":n["closed"][-50:]}}
                        logging.info("SHORT1042 PAPER M%s SCAN regime=%s checked=%s signals=%s leaders=%s decisions=%s",i,direction,d["checked"],d["signals"],d["leaders"],d["last"])
                    except Exception as ex:
                        VIEW={**VIEW,str(i):{**VIEW[str(i)],"status":"error","error":str(ex)[:150]}}
                        logging.warning("SHORT1042 PAPER M%s scan: %s",i,str(ex)[:150])
            time.sleep(5)
        except Exception as ex:
            VIEW={k:{**v,"status":"error","error":str(ex)[:150]} for k,v in VIEW.items()}
            logging.warning("SHORT1042 PAPER feed error: %s",str(ex)[:150]);time.sleep(10)
def selftest():
    s=initial()
    p={"symbol":"TEST","side":1,"qty":2.,"entry":100.,"entry_fee":.12,"funding":-.01}
    s["positions"]["TEST"]=p;s["balance"]-=.13;s["fees"]+=.12;s["funding"]-=.01
    t={"bid1Price":"110","ask1Price":"111"}
    close(s,"TEST",p,t,1,"TP")
    assert s["count"]==1 and s["wins"]==1
    assert abs(s["balance"]-1000-s["closed"][0]["net"])<1e-8
    assert quote(t,-1,True)<110 and quote(t,-1,False)>111
    d=diagnostics(s);note(d,"TEST","no_pattern");assert d["reasons"]["no_pattern"]==1 and d["last"][0]["symbol"]=="TEST"
