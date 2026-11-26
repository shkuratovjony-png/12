"""Demo spot execution, same process and risk budget as the futures executor.
No leverage/borrowing. Own inventory only. Persist intent before every submission.
"""
import time,hashlib,logging,math
from decimal import Decimal,ROUND_DOWN
import market,league,paper_exec
META={}
TERMINAL={"Filled","Cancelled","Rejected","PartiallyFilledCanceled","Deactivated"}
REFUSALS={10001,10005,170010,170011,170019,170031,170105,170115,170116,170117,170121,170124,170130,170131,170136,170137,170140,170148,170151,170219,170224,170227,170228,170229,170241}
def dec(x):return Decimal(str(x))
def floor(x,step):return (dec(x)/dec(step)).to_integral_value(rounding=ROUND_DOWN)*dec(step)
def meta(req,sym):
    if sym not in META:
        m=req("GET","/v5/market/instruments-info",{"category":"spot","symbol":sym},False)["list"][0]
        if m.get("quoteCoin")!="USDT" or m["status"]!="Trading":raise ValueError("not eligible")
        META[sym]=m
    return META[sym]
def order(req,sym,link):
    args={"category":"spot","symbol":sym,"orderLinkId":link}
    rows=req("GET","/v5/order/realtime",args).get("list",[])
    if not rows:rows=req("GET","/v5/order/history",args).get("list",[])
    return rows[0] if rows else None
def submit(req,sym,side,qty,link):
    return req("POST","/v5/order/create",{"category":"spot","symbol":sym,"side":side,"orderType":"Market","qty":str(qty),"marketUnit":"quoteCoin" if side=="Buy" else "baseCoin","isLeverage":0,"orderLinkId":link,"slippageToleranceType":"Percent","slippageTolerance":"0.20","orderFilter":"Order"})
def fills(req,o,base):
    q=dec(o.get("cumExecQty") or "0");v=dec(o.get("cumExecValue") or "0")
    if q<=0:return (0.,0.,0.,0.)
    if v<=0:return None
    fees=o.get("cumFeeDetail")
    if not isinstance(fees,dict) or not fees:
        rows=[];cursor=""
        for _ in range(10):
            args={"category":"spot","orderId":o["orderId"],"limit":100}
            if cursor:args["cursor"]=cursor
            data=req("GET","/v5/execution/list",args);rows.extend(data.get("list",[]));cursor=data.get("nextPageCursor")
            if not cursor:break
        if cursor:return None
        unique={r["execId"]:r for r in rows};rows=list(unique.values())
        if sum(dec(r.get("execQty") or 0) for r in rows)!=q:return None
        fees={}
        for r in rows:
            f=dec(r.get("execFee") or "0");coin=r.get("feeCurrency")
            if f and not coin:return None
            if coin:fees[coin]=dec(fees.get(coin,0))+f
    if any(c not in (base,"USDT") and dec(f) for c,f in fees.items()):return None
    return float(q),float(v),float(dec(fees.get(base,0))),float(dec(fees.get("USDT",0)))
def inventory(s):
    m=s.get("spot_managed")
    if not m or m["phase"]!="open":return 0.
    q=market.scalp_quote("spot",m["symbol"])
    return m["remaining"]*(q["bid"] if q else m["last_bid"])
def tick(s,req,save,now,halted,cash,budget,exposure,allow_entry=False):
    m=s.get("spot_managed")
    blocked=s.setdefault("spot_blocked",{})
    selection={"signals":0,"submitted":0,"status":"idle"}
    if m:
        sym=m["symbol"];info=meta(req,sym);lot=info["lotSizeFilter"];base=info["baseCoin"]
        phase=m["phase"];selection["status"]=phase
        if phase in ("entry_pending","exit_pending"):
            link=m["entry_link"] if phase=="entry_pending" else m["exit_link"]
            o=order(req,sym,link)
            if not o or o.get("orderStatus") not in TERMINAL:return selection
            f=fills(req,o,base)
            if f is None:
                selection["status"]="awaiting_fee_reconciliation";return selection
            qty,value,basefee,quotefee=f
            if phase=="entry_pending":
                if qty<=0:
                    s["spot_managed"]=None;blocked[sym]=now+60;save(s);return selection
                m.update(phase="open",remaining=max(0,qty-basefee),cost=value+quotefee,proceeds=0.,entry_order=o["orderId"],entry_price=value/qty,last_bid=value/qty,exit_attempt=0)
                save(s);logging.info("BYBIT SPOT OPEN confirmed symbol=%s qty=%.10f cost=%.6f strategy=%s",sym,m["remaining"],m["cost"],m["strategy_id"])
            else:
                m["remaining"]=max(0,m["remaining"]-qty-max(0,basefee));m["proceeds"]+=value-quotefee
                m["exit_attempt"]+=1;m["phase"]="open";m["retry_at"]=now+3
                m["exit_order"]=o["orderId"];save(s)
            return selection
        q=market.scalp_quote("spot",sym)
        if q:m["last_bid"]=q["bid"]
        # If the stream goes stale, the deadline still triggers a safe market sell.
        bid=m["last_bid"];qty=floor(m["remaining"],lot["basePrecision"])
        if qty<=0 or float(qty)*bid<float(lot["minOrderAmt"]):
            net=m["proceeds"]-m["cost"] # dust conservatively valued at zero
            closed=dict(m,market="spot",closed=now,exchange_pnl=net,notional=m["cost"],dust_qty=m["remaining"],probe=False)
            s["closed"]=(s["closed"]+[closed])[-500:];s["spot_managed"]=None;save(s)
            logging.info("BYBIT SPOT CLOSE confirmed symbol=%s net=%.6f dust=%.10f",sym,net,m["remaining"])
            return selection
        if now>=m.get("retry_at",0) and (halted or now>=m["deadline"] or bid/m["entry_price"]-1<=-m["stop"]):
            # Sell only bot-owned quantity, never existing account holdings.
            link="std-sx-"+m["id"]+str(m["exit_attempt"])
            m.update(phase="exit_pending",exit_link=link);save(s)
            try:submit(req,sym,"Sell",format(qty,"f"),link)
            except Exception as e:
                if getattr(e,"code",None) in REFUSALS:
                    m.update(phase="open",exit_attempt=m["exit_attempt"]+1,retry_at=now+15);save(s)
                logging.warning("BYBIT SPOT exit error symbol=%s error=%s",sym,str(e)[:80])
        return selection
    if not allow_entry or halted or cash<50 or len(s["managed"])>=3:return selection
    intents=[q for q in league.snapshot(now)["signals"] if q["kind"]=="spot" and q["side"]==1]
    selection["signals"]=len(intents)
    def rank(q):
        xs=[x for x in s["closed"] if x.get("market")=="spot" and x.get("strategy_id")==q["key"]][-8:]
        return (sum(x["exchange_pnl"]/max(1,x["notional"]) for x in xs)/(len(xs)+5),bool(q.get("research_evidence")),q.get("rank",0))
    for q in sorted(intents,key=rank,reverse=True):
        sym=q["symbol"];sid=q["key"]
        if now-q["time"]<1 or now>q["expires"] or blocked.get(sym,0)>now:continue
        if any(x["symbol"]==sym for x in s["managed"].values()):continue
        xs=[x for x in s["closed"] if x.get("market")=="spot" and x.get("strategy_id")==sid][-8:]
        if xs and now-xs[-1]["closed"]<60:continue
        if len(xs)>=2 and now-xs[-1]["closed"]<900 and all(x["exchange_pnl"]<0 for x in xs[-2:]):continue
        k=hashlib.sha256(("spot:"+sid+":"+str(q["time"])).encode()).hexdigest()[:22]
        if k in s["seen"]:continue
        book=market.scalp_quote("spot",sym)
        if not book or (book["ask"]-book["bid"])/book["ask"]>.0015:continue
        try:
            info=meta(req,sym);lot=info["lotSizeFilter"]
            amount=floor(min(budget*.025,budget*.15-exposure,cash*.95),lot["quotePrecision"])
            if amount<max(dec("10"),dec(lot["minOrderAmt"])*2):continue
            if not paper_exec.fill(book,1,notional=float(amount)) or time.time()-book["time"]>2:continue
            link="std-sb-"+k
            m={"id":k,"market":"spot","symbol":sym,"strategy_id":sid,"phase":"entry_pending","entry_link":link,"notional":float(amount),"deadline":now+max(60,min(300,float(q["hold"]))),"stop":min(.01,max(.003,float(q["stop"]))),"created":now}
            s["spot_managed"]=m;s["seen"][k]=now;save(s)
            try:
                submit(req,sym,"Buy",format(amount,"f"),link);selection["submitted"]=1
                logging.info("BYBIT SPOT STRATEGY submitted symbol=%s strategy=%s notional=%s",sym,sid,amount)
            except Exception as e:
                if getattr(e,"code",None) in REFUSALS:
                    s["spot_managed"]=None;blocked[sym]=now+(86400 if e.code==170241 else 900);save(s)
                logging.warning("BYBIT SPOT entry error symbol=%s error=%s",sym,str(e)[:80])
            break
        except Exception as e:logging.warning("BYBIT SPOT candidate skipped symbol=%s error=%s",sym,str(e)[:80])
    return selection
def selftest():
    assert floor("0.019999","0.001")==dec("0.019")
    class Fake:
        def __call__(self,*args,**kwargs):raise AssertionError("no request needed")
    assert fills(Fake(),{"cumExecQty":"1","cumExecValue":"100","cumFeeDetail":{"BTC":"0.001"}},"BTC")== (1.,100.,.001,0.)
