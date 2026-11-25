"""Short-horizon spot-margin shadow experiments, no borrowing or exchange orders.
Observed discounted book fills; actual public VIP0 hourly rates, modeled fees.
No account-specific borrow availability, margin/liquidation or repayment simulation.
"""
import time,math,logging,collections
import store,market,paper_exec
VIEW={}
SYMS=("BTCUSDT","ETHUSDT","SOLUSDT")
FEE=.0015
def rates():
    out={}
    data=market.request("/v5/spot-margin-trade/data",vipLevel="No VIP")
    for tier in data.get("vipCoinList",[]):
        if tier.get("vipLevel")!="No VIP":continue
        for x in tier.get("list",[]):
            if x.get("borrowable") is True:
                r=float(x["hourlyBorrowRate"])
                if math.isfinite(r) and r>=0:out[x["currency"]]=r
    return out
def worker():
    global VIEW
    s=store.get("margin_lab_v1",{}) or {}
    histories={sym:collections.deque(maxlen=30) for sym in SYMS}
    pending={};rr={};rate_time=0;last_save=0
    while True:
        now=time.time()
        try:
            if now-rate_time>300:
                try:rr=rates();rate_time=now
                except Exception as e:logging.warning("MARGIN rates unavailable: %s",str(e)[:100]);rate_time=now;rr={}
            for sym in SYMS:
                q=market.scalp_quote("spot",sym)
                if not q:continue
                mid=(q["ask"]+q["bid"])/2
                h=histories[sym];h.append((now,mid))
                for look in (30,120):
                    old=next((p for t,p in reversed(h) if now-t>=look),None)
                    for family in ("trend","reversal"):
                        for hold in (60,300):
                            k=f"{sym}:{look}:{family}:{hold}"
                            m=s.setdefault(k,{"closed":0,"net":0.,"wins":0,"equity":1000.,"peak":1000.,"dd":0.})
                            p=m.get("position")
                            if p:
                                f=paper_exec.fill(q,-p["side"],quantity=p["qty"])
                                if not f:continue
                                move=p["side"]*(f["price"]/p["price"]-1)
                                if now-p["time"]>=hold or move<=-.005:
                                    # Conservative full notional interest, two hourly charges minimum.
                                    interest=max(2,math.ceil((now-p["time"])/3600)+1)*p["rate"]*p["notional"]
                                    net=p["side"]*(f["price"]-p["price"])*p["qty"]-FEE*(p["notional"]+f["notional"])-interest
                                    m["equity"]+=net;m["peak"]=max(m["peak"],m["equity"])
                                    m["dd"]=max(m["dd"],1-m["equity"]/m["peak"])
                                    m["closed"]+=1;m["net"]+=net;m["wins"]+=int(net>0);m["position"]=None
                                continue
                            if m["dd"]>=.15 or old is None or (q["ask"]-q["bid"])/mid>.0015:continue
                            move=mid/old-1
                            if abs(move)<.0015:pending.pop(k,None);continue
                            side=(1 if move>0 else -1)*(1 if family=="trend" else -1)
                            coin="USDT" if side==1 else sym[:-4]
                            if coin not in rr or now-rate_time>600:continue
                            intent=pending.get(k)
                            if not intent or intent[0]!=side:pending[k]=(side,now);continue
                            if now-intent[1]<1:continue
                            f=paper_exec.fill(q,side,notional=min(100,m["equity"]*.1))
                            if f:
                                m["position"]={"side":side,"price":f["price"],"qty":f["qty"],"notional":f["notional"],"rate":rr[coin],"time":now}
                                pending.pop(k,None)
            if now-last_save>=30:
                store.put("margin_lab_v1",s);last_save=now
                VIEW={"time":now,"mode":"shadow_only","rates":rr,"models":len(s),"closed":sum(m["closed"] for m in s.values()),"positive":sum(m["closed"]>0 and m["net"]>0 for m in s.values()),"open":sum(bool(m.get("position")) for m in s.values()),"top":sorted([{"id":k,"closed":m["closed"],"net":m["net"],"dd":m["dd"]} for k,m in s.items()],key=lambda m:m["net"],reverse=True)[:6]}
                logging.info("MARGIN LAB %s",VIEW)
        except Exception:logging.exception("MARGIN LAB error")
        time.sleep(5)
