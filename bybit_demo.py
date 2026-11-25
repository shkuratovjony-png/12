"""Exchange-side demo execution only. Never authenticates to mainnet."""
import os,time,json,hmac,hashlib,logging
from decimal import Decimal,ROUND_DOWN
from datetime import datetime,timezone
from urllib.parse import urlencode
import requests
import store,market

HOST="https://api-demo.bybit.com"
VIEW={"status":"starting","mode":"demo","capital_limit":1000}
KEY=os.getenv("BYBIT_DEMO_API_KEY","").strip()
SECRET=os.getenv("BYBIT_DEMO_API_SECRET","").strip()
CONFIG=os.getenv("BYBIT_DEMO_BASE_URL",HOST).strip().rstrip("/")
SESSION=requests.Session()
SESSION.trust_env=False
META={}
# Explicit business refusals are not ambiguous network failures.
class Rejected(RuntimeError):
    def __init__(self,code):
        self.code=int(code);super().__init__("Bybit code "+str(code))
DEFINITE={10001,10005,110003,110004,110007,110012,110013,110017,110024,110025,110028,110029,110092,110093,110094,110123,110124,110125,110132,110134,110136}
RESTRICTED={110123,110124,110125,110132,110134,110136}
PROBE_CORE=("ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","AVAXUSDT","BNBUSDT","BTCUSDT","LTCUSDT")
def reject_entry(s,k,m,e,now):
    if isinstance(e,Rejected) and e.code in DEFINITE:
        s["blocked"][m["symbol"]]={"until":now+(86400 if e.code in RESTRICTED else 900),"code":e.code}
        if m.get("probe"):s["probes"][m["probe_key"]]={"status":"rejected","code":e.code,"time":now}
        s["managed"].pop(k,None);save(s)
        logging.warning("BYBIT DEMO definitive rejection symbol=%s code=%s",m["symbol"],e.code)
    else:logging.warning("BYBIT DEMO entry request uncertain symbol=%s error=%s",m["symbol"],str(e)[:80])
def req(method,path,params=None,private=True):
    params=params or {}
    if CONFIG!=HOST or not KEY or not SECRET:raise RuntimeError("demo configuration missing or invalid")
    payload=urlencode(params) if method=="GET" else json.dumps(params,separators=(",",":"))
    headers={"Content-Type":"application/json"}
    if private:
        ts=str(int(time.time()*1000));window="5000"
        sig=hmac.new(SECRET.encode(),(ts+KEY+window+payload).encode(),hashlib.sha256).hexdigest()
        headers.update({"X-BAPI-API-KEY":KEY,"X-BAPI-TIMESTAMP":ts,"X-BAPI-RECV-WINDOW":window,"X-BAPI-SIGN":sig})
    # Never follow redirects or expose signed requests in logs.
    url=(HOST if private else "https://api.bybit.com")+path
    try:
        response=SESSION.request(method,url+("?"+payload if method=="GET" and payload else ""),data=payload if method=="POST" else None,headers=headers,timeout=8,allow_redirects=False)
        if response.status_code!=200:raise RuntimeError("HTTP "+str(response.status_code))
        data=response.json()
    except requests.RequestException:
        raise RuntimeError("Bybit network error") from None
    if data.get("retCode")!=0:raise Rejected(data.get("retCode"))
    return data.get("result") or {}
def wallet():
    a=req("GET","/v5/account/wallet-balance",{"accountType":"UNIFIED","coin":"USDT"})["list"][0]
    c=next((x for x in a.get("coin",[]) if x["coin"]=="USDT"),{})
    return float(c.get("walletBalance") or 0),float(c.get("equity") or 0)
def positions():
    out={};cursor=""
    for _ in range(20):
        args={"category":"linear","settleCoin":"USDT","limit":200}
        if cursor:args["cursor"]=cursor
        result=req("GET","/v5/position/list",args)
        for p in result.get("list",[]):
            if float(p.get("size") or 0)>0:out[(p["symbol"],int(p.get("positionIdx",0)))]=p
        cursor=result.get("nextPageCursor")
        if not cursor:return out
    raise RuntimeError("position pagination incomplete")
def dec(x):return Decimal(str(x))
def down(x,step):return format((dec(x)/dec(step)).to_integral_value(rounding=ROUND_DOWN)*dec(step),"f")
def instrument(sym):
    if sym not in META:
        m=req("GET","/v5/market/instruments-info",{"category":"linear","symbol":sym},False)["list"][0]
        if m["status"]!="Trading" or m["settleCoin"]!="USDT":raise RuntimeError("instrument not eligible")
        META[sym]=m
    return META[sym]
def save(s):store.put("bybit_demo_v1",s)
def identity(p):return hashlib.sha256((p["symbol"]+":"+str(p["opened"])+":"+str(p["side"])).encode()).hexdigest()[:24]
def order_info(sym,link):
    args={"category":"linear","symbol":sym,"orderLinkId":link}
    rows=req("GET","/v5/order/realtime",args).get("list",[])
    if not rows:rows=req("GET","/v5/order/history",args).get("list",[])
    return rows[0] if rows else None
def submit(sym,side,qty,link,stop=None):
    args={"category":"linear","symbol":sym,"side":side,"orderType":"Market","qty":qty,"positionIdx":0,"orderLinkId":link,"reduceOnly":stop is None}
    if stop is not None:args.update(stopLoss=stop,slTriggerBy="MarkPrice",tpslMode="Full",slOrderType="Market")
    return req("POST","/v5/order/create",args)
def worker():
    global VIEW
    s=store.get("bybit_demo_v1",{}) or {}
    s.setdefault("started",time.time());s.setdefault("managed",{});s.setdefault("seen",{});s.setdefault("closed",[])
    s.setdefault("blocked",{});s.setdefault("probes",{});s.setdefault("probe_next",0)
    # Prior version logged an explicit 110123 rejection for XAUUSDT.
    # Reconcile exchange state below before releasing that reserved slot.
    s.setdefault("v019_reconciled",False)
    save(s)
    last_log=0;last_wallet=0;cash=equity=0.
    while True:
        now=time.time()
        try:
            if not KEY or not SECRET or CONFIG!=HOST:
                VIEW={"status":"configuration_error","mode":"demo","capital_limit":1000}
                time.sleep(30);continue
            if now-last_wallet>=10:
                cash,equity=wallet();last_wallet=now
                if not s.get("funding_checked"):
                    # Mark before request; ambiguous responses must never trigger a duplicate top-up.
                    s["funding_checked"]=True;s["funding_before"]=cash;s["funding_requested"]=max(0,round(1000-cash,6));save(s)
                    if cash<999.99:
                        req("POST","/v5/account/demo-apply-money",{"adjustType":0,"utaDemoApplyMoney":[{"coin":"USDT","amountStr":str(s["funding_requested"])}]})
                        s["funding_ack"]=True;save(s)
                        cash,equity=wallet()
                    logging.info("BYBIT DEMO FUNDING checked balance=%.4f",cash)
                if "initial_equity" not in s:
                    s["initial_equity"]=equity;s["peak"]=equity;s["day_start"]=equity;s["day"]=datetime.now(timezone.utc).date().isoformat()
                today=datetime.now(timezone.utc).date().isoformat()
                if s["day"]!=today:s["day"]=today;s["day_start"]=equity
                s["peak"]=max(s["peak"],equity);save(s)
            live=positions()
            if not s["v019_reconciled"]:
                for k,m in list(s["managed"].items()):
                    if m["symbol"]=="XAUUSDT" and m["phase"]=="entry_pending" and not any(x[0]=="XAUUSDT" for x in live):
                        if not order_info(m["symbol"],m["entry_link"]):
                            s["blocked"]["XAUUSDT"]={"until":now+86400,"code":110123}
                            del s["managed"][k]
                s["v019_reconciled"]=True;save(s)
            paper=store.get("paper",{}) or {}
            active={identity(p):p for p in paper.get("positions",[]) if p.get("market")=="linear"}
            # Risk is expressed in dollars against the requested 1k budget, not a large default demo wallet.
            halted=equity<=0 or equity<=s["peak"]-150 or equity<=s["day_start"]-30 or paper.get("halted",False)
            for k,m in list(s["managed"].items()):
                sym=m["symbol"];p=live.get((sym,0))
                if m["phase"]=="entry_pending":
                    o=order_info(sym,m["entry_link"])
                    if not o:
                        if now-m["created"]>120 and not m.get("uncertain_logged"):
                            m["uncertain_logged"]=True;save(s)
                            logging.warning("BYBIT DEMO unresolved entry symbol=%s; reservation retained",sym)
                        continue
                    if o.get("orderStatus") not in ("Filled","Cancelled","Rejected","PartiallyFilledCanceled","Deactivated"):continue
                    m["entry_order"]=o.get("orderId");m["filled_qty"]=o.get("cumExecQty","0");m["entry_price"]=o.get("avgPrice");m["entry_status"]=o.get("orderStatus")
                    if float(m["filled_qty"] or 0)<=0:
                        if m.get("probe"):s["probes"][m["probe_key"]]={"status":"no_fill","time":now}
                        del s["managed"][k];save(s);continue
                    m["phase"]="open";save(s)
                    logging.info("BYBIT DEMO OPEN confirmed symbol=%s qty=%s price=%s probe=%s",sym,m["filled_qty"],m["entry_price"],m.get("probe",False))
                    # Position snapshot preceded order reconciliation. Refresh next cycle.
                    continue
                if m["phase"]=="exit_pending":
                    o=order_info(sym,m["exit_link"])
                    if o and o.get("orderStatus") in ("Filled","Cancelled","Rejected","PartiallyFilledCanceled","Deactivated"):
                        m["exit_order"]=o.get("orderId");m["exit_price"]=o.get("avgPrice")
                        if p:
                            m["phase"]="open";m["exit_attempt"]=m.get("exit_attempt",0)+1;save(s)
                            continue
                    elif p:
                        if now-m.get("exit_sent",now)>15:
                            # An idempotent retry uses the same orderLinkId.
                            try:submit(sym,"Sell" if m["side"]=="Buy" else "Buy",p["size"],m["exit_link"])
                            except Exception:pass
                            m["exit_sent"]=now;save(s)
                        continue
                if not p:
                    if m.get("probe"):s["probes"][m["probe_key"]]={"status":"roundtrip_confirmed","time":now,"entry_price":m.get("entry_price"),"exit_price":m.get("exit_price")}
                    s["closed"]=(s["closed"]+[dict(m,closed=now,reason="exchange_position_flat")])[-200:]
                    del s["managed"][k];save(s)
                    logging.info("BYBIT DEMO CLOSE confirmed symbol=%s",sym);continue
                if p["side"]!=m["side"] or dec(p["size"])>dec(m["filled_qty"]):
                    m["conflict"]=True;save(s);continue
                if m.get("conflict"):continue
                if halted or (not m.get("probe") and k not in active) or now>=m["deadline"]:
                    link="std-x-"+k+str(m.get("exit_attempt",0))
                    m.update(phase="exit_pending",exit_link=link,exit_sent=now);save(s)
                    try:submit(sym,"Sell" if m["side"]=="Buy" else "Buy",p["size"],link)
                    except Exception as e:
                        if isinstance(e,Rejected) and e.code in DEFINITE:
                            m["phase"]="open";m["exit_attempt"]=m.get("exit_attempt",0)+1;save(s)
                        logging.warning("BYBIT DEMO exit request error symbol=%s error=%s",sym,str(e)[:80])
            if not halted and cash>=10 and len(s["managed"])<3:
                budget=min(1000,max(0,1000+equity-s["initial_equity"]),equity)
                exposure=sum(float(m["notional"]) for m in s["managed"].values())
                for k,p in active.items():
                    if k in s["seen"] or p["opened"]<s["started"] or now-p["opened"]>30 or p.get("scalp"):continue
                    sym=p["symbol"]
                    if s["blocked"].get(sym,{}).get("until",0)>now:continue
                    if any(a[0]==sym for a in live) or any(m["symbol"]==sym for m in s["managed"].values()):continue
                    amount=min(budget*.05, float(p["qty"])*float(p["entry"]),budget*.15-exposure)
                    if amount<10:continue
                    try:
                        meta=instrument(sym);lot=meta["lotSizeFilter"]
                        q=down(amount/float(p["entry"]),lot["qtyStep"])
                        if dec(q)<dec(lot["minOrderQty"]) or dec(q)*dec(p["entry"])<dec(lot.get("minNotionalValue","5")):continue
                        stop=down(float(p["entry"])*(1-p["side"]*min(.02,max(.003,float(p.get("stop",.0075))))),meta["priceFilter"]["tickSize"])
                        side="Buy" if p["side"]==1 else "Sell"
                        link="std-e-"+k
                        m={"symbol":sym,"side":side,"phase":"entry_pending","entry_link":link,"notional":amount,"deadline":p["opened"]+p.get("hold",900),"strategy_id":p.get("strategy_id"),"created":now}
                        s["seen"][k]=now;s["managed"][k]=m;save(s)
                        try:submit(sym,side,q,link,stop)
                        except Exception as e:reject_entry(s,k,m,e,now)
                        break
                    except Exception as e:logging.warning("BYBIT DEMO candidate skipped symbol=%s error=%s",sym,str(e)[:80])
            # Separate diagnostic round trips, not strategy evidence. One at a time.
            if not halted and cash>=50 and now>=s["probe_next"] and len(s["managed"])<3 and not any(m.get("probe") for m in s["managed"].values()):
                syms=list(dict.fromkeys(PROBE_CORE+tuple(market.SYMBOLS)))
                for sym in syms:
                    if s["blocked"].get(sym,{}).get("until",0)>now or any(x[0]==sym for x in live) or any(m["symbol"]==sym for m in s["managed"].values()):continue
                    direction=next((side for side in ("Buy","Sell") if sym+":"+side not in s["probes"]),None)
                    if direction is None:continue
                    pk=sym+":"+direction
                    s["probe_next"]=now+20
                    try:
                        meta=instrument(sym);lot=meta["lotSizeFilter"]
                        t=req("GET","/v5/market/tickers",{"category":"linear","symbol":sym},False)["list"][0]
                        ask=float(t["ask1Price"]);bid=float(t["bid1Price"]);mark=float(t["markPrice"])
                        if not (0<bid<=ask and mark>0) or (ask-bid)/ask>.002:raise RuntimeError("wide or invalid quote")
                        price=ask if direction=="Buy" else bid
                        budget=min(1000,max(0,1000+equity-s["initial_equity"]),equity)
                        exposure=sum(float(m["notional"]) for m in s["managed"].values())
                        amount=min(40,budget*.05,budget*.15-exposure)
                        q=down(amount/price,lot["qtyStep"])
                        if dec(q)<dec(lot["minOrderQty"]) or dec(q)*dec(price)<dec(lot.get("minNotionalValue","5")):
                            s["probes"][pk]={"status":"minimum_exceeds_budget","time":now};save(s);continue
                        stop=down(min(mark,bid)*.99 if direction=="Buy" else max(mark,ask)*1.01,meta["priceFilter"]["tickSize"])
                        k=hashlib.sha256(("probe:"+pk+":"+str(s["started"])).encode()).hexdigest()[:24]
                        link="std-p-"+k
                        m={"symbol":sym,"side":direction,"phase":"entry_pending","entry_link":link,"notional":amount,"deadline":now+45,"created":now,"probe":True,"probe_key":pk}
                        s["managed"][k]=m;s["probes"][pk]={"status":"submitted","time":now};save(s)
                        try:submit(sym,direction,q,link,stop)
                        except Exception as e:reject_entry(s,k,m,e,now)
                        logging.info("BYBIT DEMO PROBE attempted symbol=%s side=%s",sym,direction)
                        break
                    except Exception as e:
                        s["probes"][pk]={"status":"quote_or_instrument_error","time":now};save(s)
                        logging.warning("BYBIT DEMO PROBE skipped symbol=%s error=%s",sym,str(e)[:80])
                        break
            s["seen"]={k:t for k,t in s["seen"].items() if now-t<86400 or k in s["managed"]}
            VIEW={"status":"connected","mode":"demo","capital_limit":1000,"wallet_usdt":cash,"equity_usdt":equity,"initial_equity":s["initial_equity"],"halted":halted,"funding_requested":s.get("funding_requested"),"funding_ack":s.get("funding_ack",False),"managed":len(s["managed"]),"exchange_positions":len(live),"closed":sum(not x.get("probe") for x in s["closed"]),"probes":s["probes"],"blocked":{k:v for k,v in s["blocked"].items() if v["until"]>now},"time":now}
            if now-last_log>=30:
                save(s);logging.info("BYBIT DEMO connected wallet=%.4f equity=%.4f managed=%s exchange_positions=%s closed=%s halted=%s",cash,equity,len(s["managed"]),len(live),len(s["closed"]),halted);last_log=now
        except Exception as e:
            VIEW=dict(VIEW,status="error",error=str(e)[:100],time=now)
            logging.warning("BYBIT DEMO error: %s",str(e)[:100])
            time.sleep(15)
        time.sleep(3)
