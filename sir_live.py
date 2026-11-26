"""SIR v1: hourly closed-bar signals, Bybit DEMO only. Legacy engine stays disabled."""
import time, logging, math, hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import store

KEY="sir_demo_v1"
VIEW={"status":"starting","budget_start":1000,"mode":"demo"}
STATE=None
LAST_REFRESH=0
TERMINAL={"Filled","Cancelled","Rejected","PartiallyFilledCanceled","Deactivated"}
def save():
    store.put(KEY,STATE)
def ema(xs,span):
    x=xs[0]; a=2/(span+1)
    for y in xs[1:]: x+=a*(y-x)
    return x
def regime(xs):
    p=xs[-1]; a=ema(xs,480); b=ema(xs,1200)
    return ("short" if p<a<b else "long" if p>a>b else "flat",a,b)
def pattern(rows,side,kind):
    # Exact hourly pattern from sirtest.py; exclude signal bar in preceding blocks.
    h=[r[2] if side==1 else -r[3] for r in rows]
    l=[r[3] if side==1 else -r[2] for r in rows]
    c=[side*r[4] for r in rows]; t=len(rows)-1
    if t<24 or side*(rows[t][4]/rows[t-24][4]-1)<=0:return None
    lows=[min(l[t-12:t-8]),min(l[t-8:t-4]),min(l[t-4:t])]
    highs=[max(h[t-12:t-8]),max(h[t-8:t-4]),max(h[t-4:t])]
    lev=max(h[t-6:t]); touches=[i for i in range(t-12,t) if h[i]>=lev-.0025*rows[t][4]]
    low2=[min(l[t-6:t-4]),min(l[t-4:t-2]),min(l[t-2:t])]
    br=lows[-1]>lows[0] and low2[0]<low2[1]<low2[2] and c[t]>lev and len(touches)>=2 and touches[-1]-touches[0]>=2
    if br:return (side*min(l[t-3:t+1]),"breakout")
    if kind=="breakout":return None
    a=min(range(t-12,t-8),key=lambda i:l[i]); b=min(range(t-8,t-4),key=lambda i:l[i])
    line=l[b]+(l[b]-l[a])/(b-a)*(t-b)
    bo=lows[0]<lows[1]<lows[2] and highs[0]<highs[1]<highs[2] and abs(l[t]-line)<=.003*rows[t][4] and c[t]>h[t-1] and c[t]>side*rows[t][1]
    if bo:return (side*min(l[t-2:t+1]),"bounce")
    return None
def bars(api,sym,n,end):
    out={}
    while len(out)<n:
        rows=api.req("GET","/v5/market/kline",{"category":"linear","symbol":sym,"interval":"60","limit":min(1000,n-len(out)),"end":end-1},False)["list"]
        if not rows:break
        for row in rows:
            ts=int(row[0])
            if ts<end:out[ts]=(ts,*map(float,row[1:5]))
        old=min(int(r[0]) for r in rows)
        if old>=end:break
        end=old
    xs=sorted(out.values())
    if len(xs)<n or any(b[0]-a[0]!=3600000 for a,b in zip(xs,xs[1:])):raise ValueError("incomplete hourly history "+sym)
    return xs[-n:]
def tick_price(x,step,up=False):
    a=Decimal(str(x)); b=Decimal(str(step))
    return format((a/b).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)*b,"f")
def view_update(**kw):
    global VIEW
    VIEW=dict(VIEW,**kw)
def selftest():
    assert regime([float(x) for x in range(1,1501)])[0]=="long"
    assert regime([float(x) for x in range(1500,0,-1)])[0]=="short"
    assert regime([10.]*1500)[0]=="flat"
    assert tick_price(1.234,"0.01",True)=="1.24"
    assert tick_price(1.234,"0.01")=="1.23"
def step(api,legacy,live,cash,equity,now):
    global STATE,LAST_REFRESH
    if api.CONFIG!=api.HOST or api.HOST!="https://api-demo.bybit.com":raise RuntimeError("DEMO host required")
    if STATE is None:
        selftest()
        STATE=store.get(KEY,None)
        if STATE is None:
            if live or legacy.get("managed") or legacy.get("spot_managed"):
                view_update(status="waiting_legacy_flat");return
            # No changes to exchange balances. Dedicated 1000 USDT virtual sub-budget.
            STATE={"wallet0":cash,"month":None,"monthbase":1000.,"positions":{},"closed":[],"last_bar":0,"started":now}
            save()
    st=STATE; owned=st["positions"]
    # All uncertain requests remain reserved; no blind retry.
    external=any(k[0] not in owned or k[1]!=0 for k in live)
    for sym,m in list(owned.items()):
        p=live.get((sym,0))
        if m["phase"]=="pending":
            o=api.order_info(sym,m["link"])
            if not o:continue
            if o.get("orderStatus") not in TERMINAL:continue
            if float(o.get("cumExecQty") or 0)<=0:
                del owned[sym];save();continue
            m.update(phase="filled",entry=float(o["avgPrice"]),qty=float(o["cumExecQty"]),order=o.get("orderId"))
            save()
            # Snapshot could precede the fill.
            continue
        if p:
            if p["side"]!=m["side"] or float(p["size"])>m["qty"]+1e-8:
                m["conflict"]=True;save();continue
            if not p.get("stopLoss") or float(p["stopLoss"])<=0 or not p.get("takeProfit") or float(p["takeProfit"])<=0:
                # Restore the original protective orders; never increase position.
                api.req("POST","/v5/position/trading-stop",{"category":"linear","symbol":sym,"positionIdx":0,"tpslMode":"Full","stopLoss":m["sl"],"takeProfit":m["tp"],"slTriggerBy":"MarkPrice","tpTriggerBy":"LastPrice"})
            continue
        rows=api.req("GET","/v5/position/closed-pnl",{"category":"linear","symbol":sym,"limit":50}).get("list",[])
        match=[r for r in rows if float(r.get("createdTime") or 0)>=m["created"]*1000-5000 and r.get("side")!=m["side"] and abs(float(r.get("qty") or 0)-m["qty"])<=max(1e-8,m["qty"]*1e-6)]
        # Bybit closed PnL side semantics can vary; accept only unique full-size match with entry price.
        if not match:
            match=[r for r in rows if float(r.get("createdTime") or 0)>=m["created"]*1000-5000 and abs(float(r.get("qty") or 0)-m["qty"])<=max(1e-8,m["qty"]*1e-6) and abs(float(r.get("avgEntryPrice") or 0)-m["entry"])<=m["entry"]*.0005]
        if len(match)!=1:
            m["reconcile_wait"]=True;save();continue
        r=match[0]; net=float(r["closedPnl"])
        st["closed"].append(dict(m,symbol=sym,net=net,closed=now,exit=float(r.get("avgExitPrice") or 0),open_fee=float(r.get("openFee") or 0),close_fee=float(r.get("closeFee") or 0)))
        del owned[sym];save()
        logging.info("SIR DEMO CLOSED %s %s net=%.5f",sym,m["side"],net)
    # Account wallet delta includes actual booked fees/funding; unrelated activity blocks new trades.
    balance=1000+cash-st["wallet0"]
    unreal=sum(float(live.get((sym,0),{}).get("unrealisedPnl") or 0) for sym in owned)
    budget=balance+unreal
    month=datetime.fromtimestamp(now,timezone.utc).strftime("%Y-%m")
    if st["month"]!=month:
        st["month"]=month;st["monthbase"]=budget;save()
    risk=.025 if budget<st["monthbase"] else .05
    stats={s:{"n":sum(x["side"]==s for x in st["closed"]),"net":sum(x["net"] for x in st["closed"] if x["side"]==s)} for s in ("Sell","Buy")}
    view_update(status="active",balance=balance,equity=budget,risk=risk,month_base=st["monthbase"],positions=list(owned.values()),closed=st["closed"][-30:],stats=stats,external=external,updated=now)
    if external or legacy.get("managed") or legacy.get("spot_managed") or any(m.get("conflict") or m.get("reconcile_wait") or m["phase"]=="pending" for m in owned.values()):
        view_update(status="blocked_reconciliation");return
    # Once per hour, closed candle only; never chase an old signal.
    end=int(now//3600)*3600000
    if st["last_bar"]>=end:return
    if now-LAST_REFRESH<60:return
    LAST_REFRESH=now
    btc=bars(api,"BTCUSDT",2000,end)
    if btc[-1][0]!=end-3600000:raise ValueError("stale BTC candle")
    direction,a,b=regime([r[4] for r in btc])
    ts=api.req("GET","/v5/market/tickers",{"category":"linear"},False)["list"]
    eligible=[]
    for x in ts:
        try:
            if x["symbol"].endswith("USDT") and float(x["turnover24h"])>=5000000 and float(x["lastPrice"])>0 and float(x["bid1Price"])>0 and float(x["ask1Price"])>0:
                eligible.append(x)
        except (KeyError,ValueError):continue
    # Rank rolling 24h tickers within the liquid perpetual universe; verify metadata before use.
    def top(side,n):
        result=[]
        for x in sorted(eligible,key=lambda x:side*float(x["price24hPcnt"]),reverse=True):
            if side*float(x["price24hPcnt"])<=0:break
            try:
                meta=api.instrument(x["symbol"])
                if meta.get("contractType")!="LinearPerpetual":continue
                result.append(x)
                if len(result)>=n:break
            except Exception:continue
        return result
    shorts=top(-1,2); longs=top(1,3)
    view_update(regime=direction,btc=btc[-1][4],ema20=a,ema50=b,universe=len(eligible),short_leaders=[x["symbol"] for x in shorts],long_leaders=[x["symbol"] for x in longs],bar=end//1000)
    logging.info("SIR DEMO scan regime=%s universe=%s shorts=%s longs=%s budget=%.2f",direction,len(eligible),[x["symbol"] for x in shorts],[x["symbol"] for x in longs],budget)
    # Publish on startup, but only enter in first 180 seconds after close.
    if now-end/1000>180 or direction=="flat" or budget<20 or len(owned)>=2:
        st["last_bar"]=end;save();return
    # Audit exchange orders before entries. Own protective orders are permitted; unrelated orders block.
    cursor=""
    for _ in range(20):
        args={"category":"linear","settleCoin":"USDT","openOnly":0,"limit":50}
        if cursor:args["cursor"]=cursor
        page=api.req("GET","/v5/order/realtime",args)
        if any(o["symbol"] not in owned or not o.get("reduceOnly") for o in page.get("list",[])):
            view_update(status="blocked_external_orders");return
        cursor=page.get("nextPageCursor")
        if not cursor:break
    else:return
    st["last_bar"]=end;save()
    side=-1 if direction=="short" else 1
    for x in (shorts if side==-1 else longs):
        sym=x["symbol"]
        if sym in owned or len(owned)>=2:continue
        try:
            rows=bars(api,sym,30,end)
            if rows[-1][0]!=end-3600000:continue
            sig=pattern(rows,side,"breakout" if side==-1 else "both")
            if not sig:continue
            stop,kind=sig
            meta=api.instrument(sym); lot=meta["lotSizeFilter"]; tick=meta["priceFilter"]["tickSize"]
            if float(meta["leverageFilter"]["maxLeverage"])<10:continue
            bid=float(x["bid1Price"]); ask=float(x["ask1Price"])
            if (ask-bid)/ask>.0015 or ask<bid:continue
            entry=(ask if side==1 else bid)*(1+side*.0002)
            sl=tick_price(stop,tick,side==-1); dist=side*(entry-float(sl))
            if dist<=0 or dist/entry>=.08:continue
            tp=tick_price(entry+side*2*dist,tick,side==1)
            if float(tp)<=0:continue
            reserved=sum(float(m["notional"])/10 for m in owned.values())
            avail=max(0,min(balance,budget)-reserved)
            # Include stop slippage and entry/exit fees as in the historical sizing.
            q=min(budget*risk/(dist+.0006*(entry+float(sl))+.0002*float(sl)),avail/(entry*(.1+.0006)),float(lot.get("maxMktOrderQty") or lot["maxOrderQty"]))
            qty=api.down(q,lot["qtyStep"])
            if float(qty)<float(lot["minOrderQty"]) or float(qty)*entry<max(10,float(lot.get("minNotionalValue") or 5)):continue
            try:api.req("POST","/v5/position/set-leverage",{"category":"linear","symbol":sym,"buyLeverage":"10","sellLeverage":"10"})
            except api.Rejected as ex:
                if ex.code!=110043:raise
            # Recheck position immediately before submitting, and ensure the signal still fresh.
            if any(k[0]==sym for k in api.positions()) or time.time()-end/1000>180:continue
            link="sir-"+hashlib.sha256((sym+str(end)+str(side)).encode()).hexdigest()[:28]
            m={"symbol":sym,"side":"Buy" if side==1 else "Sell","phase":"pending","link":link,"created":time.time(),"qty":float(qty),"notional":float(qty)*entry,"sl":sl,"tp":tp,"signal":kind,"risk":risk,"bar":end//1000,"strategy":"sir_short_v1" if side==-1 else "sir_long_experimental_v1"}
            owned[sym]=m;save()
            try:
                api.req("POST","/v5/order/create",{"category":"linear","symbol":sym,"side":m["side"],"orderType":"Market","qty":qty,"positionIdx":0,"orderLinkId":link,"reduceOnly":False,"stopLoss":sl,"takeProfit":tp,"tpslMode":"Full","slTriggerBy":"MarkPrice","tpTriggerBy":"LastPrice","slOrderType":"Market","tpOrderType":"Market","slippageToleranceType":"Percent","slippageTolerance":"0.15"})
                logging.info("SIR DEMO SUBMITTED %s %s qty=%s SL=%s TP=%s",sym,m["side"],qty,sl,tp)
            except api.Rejected as ex:
                if ex.code in api.DEFINITE:del owned[sym];save()
                logging.warning("SIR DEMO order rejected %s code=%s",sym,ex.code)
                break
            except Exception:
                logging.warning("SIR DEMO ambiguous submission %s; reservation retained",sym)
                break
            # Wait for confirmation before another entry.
            break
        except Exception as ex:
            logging.warning("SIR DEMO candidate %s skipped %s",sym,str(ex)[:100])
    view_update(positions=list(owned.values()))
