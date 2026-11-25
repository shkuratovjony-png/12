"""Exchange-side demo execution only. Never authenticates to mainnet."""
import os,time,json,hmac,hashlib,logging
from decimal import Decimal,ROUND_DOWN,ROUND_UP
from datetime import datetime,timezone
from urllib.parse import urlencode
import requests
import store,market,league,paper_exec,spot_demo

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
DEFINITE={10001,10005,110003,110004,110007,110012,110013,110017,110024,110025,110028,110029,110092,110093,110094,110123,110124,110125,110126,110132,110134,110136}
RESTRICTED={110123,110124,110125,110126,110132,110134,110136}
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
    spot_demo.selftest()
    last_log=0;last_wallet=0;cash=equity=0.;raw_equity=0.
    while True:
        now=time.time()
        try:
            if not KEY or not SECRET or CONFIG!=HOST:
                VIEW={"status":"configuration_error","mode":"demo","capital_limit":1000}
                time.sleep(30);continue
            if now-last_wallet>=10:
                cash,raw_equity=wallet();last_wallet=now
                equity=raw_equity+spot_demo.inventory(s)
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
                # Pending spot fills and cash updates are asynchronous. Never raise the risk peak during reconciliation.
                if not s.get("spot_managed") or s["spot_managed"]["phase"]=="open":s["peak"]=max(s["peak"],equity)
                save(s)
            market.pin_demo([m["symbol"] for m in s["managed"].values()])
            live=positions()
            if not s["v019_reconciled"]:
                for k,m in list(s["managed"].items()):
                    if m["symbol"]=="XAUUSDT" and m["phase"]=="entry_pending" and not any(x[0]=="XAUUSDT" for x in live):
                        if not order_info(m["symbol"],m["entry_link"]):
                            s["blocked"]["XAUUSDT"]={"until":now+86400,"code":110123}
                            del s["managed"][k]
                s["v019_reconciled"]=True;save(s)
            if not s.get("v0191_ant_reconciled"):
                for k,m in list(s["managed"].items()):
                    if m["symbol"]=="ANTUSDT" and m["phase"]=="entry_pending" and not any(x[0]=="ANTUSDT" for x in live):
                        if not order_info(m["symbol"],m["entry_link"]):
                            s["blocked"]["ANTUSDT"]={"until":now+86400,"code":110126}
                            del s["managed"][k]
                s["v0191_ant_reconciled"]=True;save(s)
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
                    if m.get("grid"):
                        m["anchor"]=float(m["entry_price"]);m["add_count"]=0
                        m["spent"]=float(m["filled_qty"])*m["anchor"]
                    m["phase"]="open";save(s)
                    logging.info("BYBIT DEMO OPEN confirmed symbol=%s qty=%s price=%s probe=%s",sym,m["filled_qty"],m["entry_price"],m.get("probe",False))
                    # Position snapshot preceded order reconciliation. Refresh next cycle.
                    continue
                if m["phase"]=="add_pending":
                    o=order_info(sym,m["add_link"])
                    if not o or o.get("orderStatus") not in ("Filled","Cancelled","Rejected","PartiallyFilledCanceled","Deactivated"):
                        if now-m.get("add_sent",now)>120 and not m.get("add_uncertain_logged"):
                            m["add_uncertain_logged"]=True;save(s)
                            logging.warning("BYBIT GRID ADD unresolved %s; reserved",sym)
                        continue
                    qty=dec(o.get("cumExecQty") or 0)
                    if qty>0:
                        m["filled_qty"]=format(dec(m["filled_qty"])+qty,"f")
                        m["spent"]+=float(qty)*float(o["avgPrice"])
                        m["add_count"]+=1
                        m.setdefault("add_orders",[]).append(o.get("orderId"))
                        logging.info("BYBIT GRID ADD confirmed symbol=%s count=%s qty=%s price=%s",sym,m["add_count"],qty,o["avgPrice"])
                    m["add_attempt"]=m.get("add_attempt",0)+1
                    m["phase"]="open";m["add_retry_at"]=now+30;save(s)
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
                grid_exit=False
                if m.get("grid"):
                    book=market.scalp_quote("linear",sym)
                    if book:
                        avg=float(p.get("avgPrice") or m["entry_price"])
                        bid=book["bid"]
                        grid_exit=bid>=avg*(1+m["grid"]["tp"])
                        # No addition after exit trigger or stop; no overlapping requests.
                        if not halted and now<m["deadline"] and not grid_exit and m["add_count"]<m["grid"]["adds"] and now>=m.get("add_retry_at",0) and dec(p["size"])==dec(m["filled_qty"]) and bid>float(m["grid_stop"]) and book["ask"]<=m["anchor"]*(1-m["grid"]["step"]*(m["add_count"]+1)):
                            meta=instrument(sym);lot=meta["lotSizeFilter"];price=book["ask"]
                            left=max(0,m["notional"]-m["spent"])
                            target=min(left,m["notional"]/(m["grid"]["adds"]+1))
                            qty=down(target/price/1.003,lot["qtyStep"])
                            if dec(qty)>=dec(lot["minOrderQty"]) and dec(qty)*dec(price)>=dec(lot.get("minNotionalValue","5")) and paper_exec.fill(book,1,quantity=float(qty)) and time.time()-book["time"]<=2:
                                link="std-ga-"+k+str(m.get("add_attempt",0))
                                m.update(phase="add_pending",add_link=link,add_sent=now,add_uncertain_logged=False);save(s)
                                try:
                                    submit(sym,"Buy",qty,link,m["grid_stop"])
                                    logging.info("BYBIT GRID ADD submitted symbol=%s qty=%s",sym,qty)
                                except Exception as e:
                                    if isinstance(e,Rejected) and e.code in DEFINITE:
                                        m.update(phase="open",add_attempt=m.get("add_attempt",0)+1,add_retry_at=now+60);save(s)
                                    logging.warning("BYBIT GRID ADD error %s %s",sym,str(e)[:80])
                                continue
                if halted or grid_exit or m.get("probe") or (not m.get("direct_signal") and k not in active) or now>=m["deadline"]:
                    link="std-x-"+k+str(m.get("exit_attempt",0))
                    m.update(phase="exit_pending",exit_link=link,exit_sent=now);save(s)
                    try:submit(sym,"Sell" if m["side"]=="Buy" else "Buy",p["size"],link)
                    except Exception as e:
                        if isinstance(e,Rejected) and e.code in DEFINITE:
                            m["phase"]="open";m["exit_attempt"]=m.get("exit_attempt",0)+1;save(s)
                        logging.warning("BYBIT DEMO exit request error symbol=%s error=%s",sym,str(e)[:80])
            spot_selection={"status":"error"}
            try:
                spot_selection=spot_demo.tick(s,req,save,now,halted,cash,min(1000,max(0,1000+equity-s["initial_equity"]),max(0,equity)),sum(float(m["notional"]) for m in s["managed"].values()))
            except Exception as e:logging.warning("BYBIT SPOT worker error: %s",str(e)[:120])
            # DEMO ONLY: direct fresh strategy signals, not a mirror of the local portfolio.
            # Exchange-confirmed results rank the next experiments. No random/diagnostic orders.
            selection={"signals":0,"fresh":0,"cooldown":0,"quote":0,"minimum":0,"busy":0,"submitted":0}
            if not halted and cash>=10 and len(s["managed"])+int(bool(s.get("spot_managed")))<3:
                budget=min(1000,max(0,1000+equity-s["initial_equity"]),equity)
                exposure=sum(float(m["notional"]) for m in s["managed"].values())+float((s.get("spot_managed") or {}).get("notional",0))
                results={}
                for c in s["closed"]:
                    if c.get("probe") or c.get("exchange_pnl") is None or not c.get("strategy_id") or now-c.get("closed",0)>86400:continue
                    results.setdefault(c["strategy_id"],[]).append(c)
                def priority(q):
                    xs=results.get(q["key"],[])[-8:]
                    net=sum(float(c["exchange_pnl"])/max(1.,float(c["notional"])) for c in xs)
                    # Small-sample shrinkage; no claims of statistical validation.
                    return (net/(len(xs)+5),int(bool(q.get("research_evidence"))),float(q.get("rank",0)))
                intents=[q for q in league.snapshot(now)["signals"] if q["kind"]=="linear"]+league.grid_signals(now)
                selection["signals"]=len(intents)
                for q in sorted(intents,key=priority,reverse=True):
                    sym=q["symbol"];sid=q["key"];stamp=q["time"]
                    if now>q["expires"] or now-stamp<1 or now-stamp>120:continue
                    selection["fresh"]+=1
                    if s["blocked"].get(sym,{}).get("until",0)>now:selection["cooldown"]+=1;continue
                    xs=results.get(sid,[])[-8:]
                    # Two recent consecutive confirmed losses suspend the strategy for 15 min.
                    if len(xs)>=2 and all(c["exchange_pnl"]<0 for c in xs[-2:]) and now-xs[-1]["closed"]<900:selection["cooldown"]+=1;continue
                    if any(a[0]==sym for a in live) or any(m["symbol"]==sym for m in s["managed"].values()) or (s.get("spot_managed") or {}).get("symbol")==sym:selection["busy"]+=1;continue
                    if any(c.get("strategy_id")==sid and now-c.get("closed",0)<60 for c in s["closed"][-30:]):selection["cooldown"]+=1;continue
                    k=hashlib.sha256(("direct:"+sid+":"+str(stamp)).encode()).hexdigest()[:24]
                    if k in s["seen"]:continue
                    quote=market.scalp_quote("linear",sym)
                    if not quote or (quote["ask"]-quote["bid"])/quote["ask"]>.0015:selection["quote"]+=1;continue
                    # Demo trial budget: 2.5%; positive exchange feedback can raise it to 5%.
                    edge=sum(c["exchange_pnl"] for c in xs)
                    allocation=.05 if len(xs)>=5 and edge>0 else .025
                    # Permit a valid exchange minimum within the existing 5% risk ceiling.
                    grid=q["model"] if q["model"].get("demo_grid") else None
                    if grid and any(m.get("grid") for m in s["managed"].values()):continue
                    reserve=min(budget*.075,budget*.15-exposure) if grid else 0.
                    max_amount=min(reserve/(grid["adds"]+1) if grid else budget*.05,budget*.15-exposure)
                    amount=max_amount/1.003 if grid else min(budget*allocation,max_amount)
                    if amount<10:selection["minimum"]+=1;continue
                    try:
                        meta=instrument(sym);lot=meta["lotSizeFilter"]
                        side="Buy" if q["side"]==1 else "Sell"
                        price=quote["ask"] if side=="Buy" else quote["bid"]
                        step=dec(lot["qtyStep"]);minimum=dec(lot["minOrderQty"])
                        minimum=max(minimum,dec(lot.get("minNotionalValue","5"))/dec(price)*dec("1.01"))
                        minimum=(minimum/step).to_integral_value(rounding=ROUND_UP)*step
                        qty=max(minimum,dec(down(amount/price,step)))
                        amount=float(qty)*price
                        if amount>max_amount or amount<5:selection["minimum"]+=1;continue
                        fill=paper_exec.fill(quote,q["side"],quantity=float(qty))
                        if not fill:selection["quote"]+=1;continue
                        # Only use a fresh book; never submit a stale price estimate.
                        if time.time()-quote["time"]>2:selection["quote"]+=1;continue
                        stop=down(price*(1-q["side"]*(float(q["stop"]) if grid else min(.02,max(.003,float(q["stop"]))))),meta["priceFilter"]["tickSize"])
                        link="std-e-"+k
                        m={"symbol":sym,"side":side,"phase":"entry_pending","entry_link":link,"notional":amount,"deadline":now+max(60,min(1800,float(q["hold"]))),"strategy_id":sid,"research_evidence":bool(q.get("research_evidence")),"admission_tier":q.get("tier"),"direct_signal":True,"created":now}
                        if grid:
                            m.update(grid={"adds":int(grid["adds"]),"step":float(grid["step"]),"tp":float(grid["tp"])},grid_stop=stop,notional=reserve,deadline=now+max(900,min(86400,float(q["hold"]))),add_attempt=0)
                        s["seen"][k]=now;s["managed"][k]=m;save(s)
                        try:
                            submit(sym,side,format(qty,"f"),link,stop);selection["submitted"]+=1
                            logging.info("BYBIT DEMO STRATEGY submitted symbol=%s side=%s strategy=%s evidence=%s hold=%s",sym,side,sid,m["research_evidence"],m["deadline"]-now)
                        except Exception as e:reject_entry(s,k,m,e,now)
                        break
                    except Exception as e:logging.warning("BYBIT DEMO candidate skipped symbol=%s error=%s",sym,str(e)[:80])
            # Execution verified; no new non-strategy orders.
            s["seen"]={k:t for k,t in s["seen"].items() if now-t<86400 or k in s["managed"]}
            if now-last_log>=30:
                # Match closed exchange PnL only to known closing order IDs.
                # Do not attach diagnostic returns to the strategy league.
                for c in s["closed"][-30:]:
                    if c.get("exchange_pnl") is not None or not c.get("exit_order"):continue
                    try:
                        rows=req("GET","/v5/position/closed-pnl",{"category":"linear","symbol":c["symbol"],"limit":50}).get("list",[])
                        row=next((x for x in rows if x.get("orderId")==c["exit_order"]),None)
                        if row:
                            c["exchange_pnl"]=float(row["closedPnl"])
                            c["open_fee"]=float(row.get("openFee") or 0);c["close_fee"]=float(row.get("closeFee") or 0)
                            logging.info("BYBIT DEMO NET symbol=%s probe=%s pnl=%.6f",c["symbol"],c.get("probe",False),c["exchange_pnl"])
                    except Exception as e:logging.warning("BYBIT DEMO pnl read error: %s",str(e)[:80]);break
                save(s)
            VIEW={"grid_open":sum(bool(x.get("grid")) for x in s["managed"].values()),"grid_adds":sum(x.get("add_count",0) for x in s["managed"].values()),"grid_closed":sum(bool(x.get("grid")) for x in s["closed"]),"grid_pnl":sum(x.get("exchange_pnl",0) for x in s["closed"] if x.get("grid")),"status":"connected","mode":"demo","capital_limit":1000,"wallet_usdt":cash,"equity_usdt":equity,"initial_equity":s["initial_equity"],"halted":halted,"funding_requested":s.get("funding_requested"),"funding_ack":s.get("funding_ack",False),"managed":len(s["managed"]),"exchange_positions":len(live),"closed":sum(not x.get("probe") for x in s["closed"]),"strategy_pnl":sum(c.get("exchange_pnl",0) for c in s["closed"] if not c.get("probe")),"strategy_pnl_matched":sum(c.get("exchange_pnl") is not None for c in s["closed"] if not c.get("probe")),"diagnostic_pnl":sum(c.get("exchange_pnl",0) for c in s["closed"] if c.get("probe")),"diagnostics_enabled":False,"direct_strategy_mode":True,"selection":selection,"spot_selection":spot_selection,"spot_open":int(bool(s.get("spot_managed"))),"spot_closed":sum(x.get("market")=="spot" for x in s["closed"]),"spot_pnl":sum(x.get("exchange_pnl",0) for x in s["closed"] if x.get("market")=="spot"),"probes":s["probes"],"blocked":{k:v for k,v in s["blocked"].items() if v["until"]>now},"time":now}
            if now-last_log>=30:
                save(s);logging.info("BYBIT SPOT selection %s",spot_selection);logging.info("BYBIT DEMO selection %s",selection);logging.info("BYBIT DEMO connected wallet=%.4f equity=%.4f managed=%s exchange_positions=%s closed=%s halted=%s",cash,equity,len(s["managed"]),len(live),len(s["closed"]),halted);last_log=now
        except Exception as e:
            VIEW=dict(VIEW,status="error",error=str(e)[:100],time=now)
            logging.warning("BYBIT DEMO error: %s",str(e)[:100])
            time.sleep(15)
        time.sleep(3)
