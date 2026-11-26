"""Isolated breakout paper account. Public market data only; no order API."""
import time, math, json, logging, threading, copy
from collections import deque
import requests, websocket
import store, sir_live
KEY="breakout_paper_v1"
FEE=.0006
SLIP=.0002
RISK=.005
MAX_HOLD=120
MIN_NET=.0005 # minimum positive net as share of entry notional
VIEW={"status":"starting","equity":1000,"balance":1000,"positions":[],"closed":[]}
SCAN={"candidates":[],"universe":0,"scanned":0,"updated":0}
LOCK=threading.Lock()
OWNED=set()
META={}
def public(session,path,**params):
    r=session.get("https://api.bybit.com/v5/market/"+path,params={"category":"linear",**params},timeout=8)
    r.raise_for_status()
    d=r.json()
    if d.get("retCode")!=0:raise RuntimeError("Bybit public "+str(d.get("retCode")))
    return d["result"]
def initial():
    return {"balance":1000.,"positions":{},"closed":[],"count":0,"wins":0,"fees":0.,"funding":0.,"peak":1000.,"dd":0.,"gaps":0,"started":time.time(),"updated":0,"cooldown":{},"history":[]}
def get_meta(session,sym):
    if sym not in META or time.time()-META[sym][0]>3600:
        META[sym]=(time.time(),public(session,"instruments-info",symbol=sym)["list"][0])
    return META[sym][1]
def level_candidate(rows,price):
    # Inputs are completed one-minute bars only, ascending. Levels fixed before break.
    if len(rows)<30 or price<=0:return None
    highs=[float(r[2]) for r in rows];lows=[float(r[3]) for r in rows]
    upper=max(highs);lower=min(lows)
    width=(upper-lower)/price
    recent=(max(highs[-5:])-min(lows[-5:]))/price
    if width<=0 or recent>min(.012,width*.65):return None
    best=None
    for side,level,series in ((1,upper,highs),(-1,lower,lows)):
        dist=side*(level-price)/price
        touches=[j for j,v in enumerate(series) if abs(v-level)/level<=.001]
        if not .00015<=dist<=.003 or len(touches)<2 or touches[-1]-touches[0]<3:continue
        score=100*(1-dist/.003)+min(20,len(touches)*3)+20*(1-min(1,recent/width))
        item={"side":side,"level":level,"distance":dist,"score":score,"touches":len(touches),"compression":recent}
        if best is None or score>best["score"]:best=item
    return best
def scanner():
    global SCAN
    session=requests.Session();cache={};cursor=0
    while True:
        try:
            now=time.time()
            ticks=public(session,"tickers")["list"]
            eligible=[t for t in ticks if t["symbol"].endswith("USDT") and float(t.get("turnover24h") or 0)>=5e6 and float(t.get("lastPrice") or 0)>0 and float(t.get("bid1Price") or 0)>0 and float(t.get("ask1Price") or 0)>0]
            eligible.sort(key=lambda t:float(t["turnover24h"]),reverse=True)
            # Rotate through the 48 most liquid candidates; limit REST load.
            pool=eligible[:48]
            if pool:
                batch=[pool[(cursor+j)%len(pool)] for j in range(min(12,len(pool)))]
                cursor=(cursor+len(batch))%len(pool)
            else:batch=[]
            end=int(now//60)*60000
            for t in batch:
                sym=t["symbol"]
                try:
                    m=get_meta(session,sym)
                    if m.get("contractType")!="LinearPerpetual" or float(m["leverageFilter"]["maxLeverage"])<10:continue
                    raw=public(session,"kline",symbol=sym,interval="1",limit=30,end=end-1)["list"]
                    rows=sorted([r for r in raw if int(r[0])<end],key=lambda r:int(r[0]))
                    if len(rows)==30 and int(rows[-1][0])==end-60000 and all(int(b[0])-int(a[0])==60000 for a,b in zip(rows,rows[1:])):
                        cache[sym]=(now,rows,m)
                except Exception as e:logging.warning("BREAKOUT scan %s: %s",sym,str(e)[:100])
                time.sleep(.25)
            out=[]
            for t in pool:
                sym=t["symbol"];item=cache.get(sym)
                if not item or now-item[0]>150:continue
                bid=float(t["bid1Price"]);ask=float(t["ask1Price"])
                if not 0<bid<=ask or (ask-bid)/ask>.001:continue
                c=level_candidate(item[1],float(t["lastPrice"]))
                if c:
                    out.append(dict(c,symbol=sym,lot=item[2]["lotSizeFilter"],updated=item[0],spread=(ask-bid)/ask))
            out.sort(key=lambda c:c["score"],reverse=True)
            SCAN={"candidates":out[:3],"universe":len(eligible),"scanned":sum(now-v[0]<=150 for v in cache.values()),"updated":time.time()}
            time.sleep(12)
        except Exception as e:
            logging.warning("BREAKOUT scanner error %s",str(e)[:120]);time.sleep(30)
def depth_price(levels,qty,buy):
    remaining=qty;cost=0.
    for price,size in levels:
        take=min(remaining,size);cost+=price*take;remaining-=take
        if remaining<=max(1e-12,qty*1e-10):return cost/qty*(1+SLIP if buy else 1-SLIP)
    return None
def net_at(p,exit):
    return p["side"]*p["qty"]*(exit-p["entry"])-p["entry_fee"]-exit*p["qty"]*FEE+p["funding"]
def exit_reason(p,px,now,pressure):
    net=net_at(p,px)
    # Loss exits must remain honest; positive exits cover all modeled costs.
    if p["side"]*(px-p["sl"])<=0:return "SL"
    if net>=p["entry"]*p["qty"]*MIN_NET:return "NET_TP"
    if now-p["opened"]>=MAX_HOLD:return "TIME"
    if now-p["opened"]>=10 and pressure<.40:return "FLOW_REVERSAL"
    return None
def book_levels(b):
    return sorted(b["b"].items(),reverse=True)[:50],sorted(b["a"].items())[:50]
def publish(s,status,books,err=None):
    global VIEW
    eq=s["balance"];positions=[]
    for sym,p in s["positions"].items():
        b=books.get(sym)
        px=p.get("mark",p["entry"])
        if b and time.monotonic()-b["at"]<2:
            bids,asks=book_levels(b)
            est=depth_price(bids if p["side"]==1 else asks,p["qty"],p["side"]==-1)
            if est is not None:px=est
        eq+=p["side"]*p["qty"]*(px-p["entry"])-px*p["qty"]*FEE
        positions.append(dict(p,mark=px,net_exit=net_at(p,px)))
    s["peak"]=max(s["peak"],eq);s["dd"]=max(s["dd"],100*(1-eq/s["peak"]))
    VIEW={**s,"positions":positions,"closed":s["closed"][-50:],"equity":eq,"status":status,"error":err,"regime":"breakout","candidates":[{k:v for k,v in c.items() if k!="lot"} for c in SCAN["candidates"]],"universe":SCAN["universe"],"scanned":SCAN["scanned"],"scan_updated":SCAN["updated"],"updated":time.time()}
    return eq
def run():
    s=store.get(KEY,None) or initial()
    threading.Thread(target=scanner,daemon=True,name="breakout-scan").start()
    session=requests.Session()
    logging.info("BREAKOUT PAPER ready; no exchange orders")
    while True:
        ws=None;books={};trades={};ticks={};armed={};subscribed=set();last_ping=0.;last_sub=0.;last_save=0.;last_eval=0.
        try:
            ws=websocket.create_connection("wss://stream.bybit.com/v5/public/linear",timeout=.5)
            while True:
                now=time.time();mono=time.monotonic()
                if mono-last_sub>=2:
                    candidates={c["symbol"]:c for c in SCAN["candidates"] if now-c["updated"]<150 and now-SCAN["updated"]<45}
                    wanted=set(candidates)|set(s["positions"])
                    for op,syms in (("unsubscribe",subscribed-wanted),("subscribe",wanted-subscribed)):
                        if syms:
                            ws.send(json.dumps({"op":op,"args":[prefix+sym for sym in sorted(syms) for prefix in ("orderbook.50.","publicTrade.","tickers.")]}))
                    for sym in subscribed-wanted:
                        books.pop(sym,None);trades.pop(sym,None);ticks.pop(sym,None);armed.pop(sym,None)
                    subscribed=wanted;last_sub=mono
                if mono-last_ping>=18:ws.send(json.dumps({"op":"ping"}));last_ping=mono
                try:
                    raw=ws.recv()
                    if not raw:raise RuntimeError("WebSocket closed")
                    msg=json.loads(raw)
                    if msg.get("op") in ("subscribe","unsubscribe") and msg.get("success") is False:raise RuntimeError("Subscription rejected")
                    topic=msg.get("topic","");sym=topic.rsplit(".",1)[-1];data=msg.get("data")
                    if topic.startswith("orderbook.") and isinstance(data,dict):
                        if msg.get("type")=="snapshot" or data.get("u")==1:books[sym]={"b":{},"a":{},"at":mono}
                        b=books.get(sym)
                        if b:
                            for k in ("b","a"):
                                for p,q in data.get(k,[]):
                                    p=float(p);q=float(q)
                                    if q>0:b[k][p]=q
                                    else:b[k].pop(p,None)
                            b["at"]=mono
                    elif topic.startswith("publicTrade.") and isinstance(data,list):
                        q=trades.setdefault(sym,deque(maxlen=3000))
                        for t in data:q.append((float(t["T"])/1000,float(t["p"]),float(t["v"]),1 if t["S"]=="Buy" else -1))
                    elif topic.startswith("tickers.") and isinstance(data,dict):
                        ticks[sym]={**(ticks.get(sym,{}) if msg.get("type")!="snapshot" else {}),**data,"at":mono}
                except websocket.WebSocketTimeoutException:pass
                if mono-last_eval<.2:continue
                last_eval=mono;dirty=False
                eq=publish(s,"active" if any(mono-b["at"]<2 for b in books.values()) else "waiting_feed",books)
                for sym in set(s["positions"])|set(candidates):
                    b=books.get(sym);q=trades.get(sym);t=ticks.get(sym,{})
                    if not b or mono-b["at"]>2 or not t or mono-t["at"]>5:continue
                    bids,asks=book_levels(b)
                    if not bids or not asks or not 0<bids[0][0]<=asks[0][0]:continue
                    bid,ask=bids[0][0],asks[0][0]
                    flow=[a for a in (q or []) if now-3<=a[0]<=now+.5]
                    buy=sum(p*v for _,p,v,side in flow if side==1);sell=sum(p*v for _,p,v,side in flow if side==-1)
                    total=buy+sell;frac=buy/total if total else .5
                    p=s["positions"].get(sym)
                    if p:
                        # Normal trades cannot overlap funding (entry guard below).
                        # If an outage crosses funding, settle actual published rate before exit.
                        if p.get("next_funding") and now*1000>=p["next_funding"]:
                            try:
                                ts=p["next_funding"]
                                h=public(session,"funding/history",symbol=sym,endTime=ts,limit=1)["list"]
                                if not h or int(h[0]["fundingRateTimestamp"])!=ts:continue
                                amount=-p["side"]*p["qty"]*float(t.get("markPrice") or (bid+ask)/2)*float(h[0]["fundingRate"])
                                s["balance"]+=amount;s["funding"]+=amount;p["funding"]+=amount
                                p["next_funding"]=ts+p["funding_interval"];dirty=True
                                store.put(KEY,s)
                                if now*1000>=p["next_funding"]:continue
                            except Exception as ex:logging.warning("BREAKOUT funding pending %s",str(ex)[:100]);continue
                        px=depth_price(bids if p["side"]==1 else asks,p["qty"],p["side"]==-1)
                        if px is None:continue
                        p["mark"]=px
                        reason=exit_reason(p,px,now,frac if p["side"]==1 else 1-frac)
                        if reason:
                            fee=px*p["qty"]*FEE;net=net_at(p,px)
                            s["balance"]+=p["side"]*p["qty"]*(px-p["entry"])-fee;s["fees"]+=fee
                            s["count"]+=1;s["wins"]+=int(net>0)
                            s["closed"].append(dict(p,exit=px,closed=now,net=net,reason=reason,exit_fee=fee))
                            del s["positions"][sym];s["cooldown"][sym]=now+180;armed.pop(sym,None);dirty=True
                            logging.info("BREAKOUT PAPER CLOSE %s %s net=%.5f",sym,reason,net)
                        continue
                    c=candidates.get(sym)
                    if not c or now-c["updated"]>150 or now-SCAN["updated"]>45 or not flow or eq<20 or len(s["positions"])>=2 or s["cooldown"].get(sym,0)>now:continue
                    side=c["side"];level=c["level"];last=flow[-1][1]
                    token=(side,level)
                    if side*(last-level)<0:
                        armed[sym]=(token,now);continue
                    if armed.get(sym,(None,0))[0]!=token or now-armed[sym][1]>15:continue
                    if side*(last-level)/level>.002 or (ask-bid)/ask>.001:continue
                    pressure=frac if side==1 else 1-frac
                    bd=sum(p*v for p,v in bids[:10]);ad=sum(p*v for p,v in asks[:10])
                    imbalance=(bd if side==1 else ad)/max(1e-12,bd+ad)
                    if len(flow)<8 or total<3000 or pressure<.68 or imbalance<.56:continue
                    nf=int(t.get("nextFundingTime") or 0)
                    if nf<=now*1000+300000:continue
                    m=META.get(sym)
                    if not m:continue
                    lot=c["lot"];base=ask if side==1 else bid
                    stop=level*(1-side*.0015)
                    reserved=sum(z["qty"]*z["entry"]/10 for z in s["positions"].values())
                    avail=max(0,min(eq,s["balance"])-reserved)
                    raw=min(eq*RISK/(abs(base-stop)+base*(2*FEE+2*SLIP)),avail*9.8/base,float(lot.get("maxMktOrderQty") or lot["maxOrderQty"]))
                    qty=float(sir_live.tick_price(raw,lot["qtyStep"]))
                    if qty<float(lot["minOrderQty"]) or qty*base<max(10,float(lot.get("minNotionalValue") or 5)):continue
                    entry=depth_price(asks if side==1 else bids,qty,side==1)
                    if entry is None or side*(entry-level)/level>.0025 or side*(entry-stop)<=0:continue
                    if qty*(abs(entry-stop)+FEE*(entry+stop)+SLIP*stop)>eq*RISK*1.05:continue
                    fee=entry*qty*FEE;s["balance"]-=fee;s["fees"]+=fee
                    s["positions"][sym]={"symbol":sym,"side":side,"qty":qty,"entry":entry,"sl":stop,"tp":None,"mark":entry,"entry_fee":fee,"funding":0.,"opened":now,"next_funding":nf,"funding_interval":int(m[1]["fundingInterval"])*60000,"level":level,"pressure":pressure,"imbalance":imbalance}
                    armed.pop(sym,None);dirty=True
                    logging.info("BREAKOUT PAPER OPEN %s side=%s qty=%s",sym,side,qty)
                if dirty or mono-last_save>=5:
                    s["updated"]=now
                    if not s["history"] or now-s["history"][-1][0]>=60:s["history"]=(s["history"]+[[now,eq]])[-1440:]
                    store.put(KEY,s);last_save=mono
        except Exception as e:
            s["gaps"]+=1
            publish(s,"reconnecting",{},str(e)[:150])
            logging.warning("BREAKOUT feed reconnect %s",str(e)[:120])
            time.sleep(5)
        finally:
            if ws:
                try:ws.close()
                except Exception:pass
def worker():
    while True:
        try:run()
        except Exception as e:
            logging.exception("BREAKOUT worker retry")
            time.sleep(30)
def selftest():
    p={"side":1,"qty":1.,"entry":100.,"entry_fee":.06,"funding":-.02,"sl":99.7,"opened":0}
    assert net_at(p,100.1)<0
    assert exit_reason(p,100.1,1,.7) is None
    assert exit_reason(p,100.3,1,.7)=="NET_TP"
    assert exit_reason(p,99.6,1,.7)=="SL"
    assert exit_reason(p,100.1,121,.7)=="TIME"
    assert depth_price([(100.,1.)],2.,True) is None
    assert abs(depth_price([(100.,1.),(101.,1.)],2.,True)-100.5*(1+SLIP))<1e-9
