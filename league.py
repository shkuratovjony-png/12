"""Paper-only champion/challenger competition; comparable daily net returns.
Selection is not statistical proof of future profit. No order API."""
import time,math,threading
LOCK=threading.RLock()
GROUPS={};SIGNALS={}
MIN_DAYS=7
MAX_DD=.08
def record(a,ret,now):
    e=a.setdefault("league_evidence",{"days":{},"last":0})
    k=str(int(now//86400));d=e["days"].setdefault(k,{"n":0,"net":0.})
    d["n"]+=1;d["net"]+=float(ret);e["last"]=now
    e["days"]={k:e["days"][k] for k in sorted(e["days"])[-30:]}
def assess(a,now,minimum):
    e=a.get("league_evidence",{});today=int(now//86400)
    # Completed UTC days only. Every model uses same normalized 10% allocation.
    d=[e.get("days",{}).get(str(i),{"n":0,"net":0.}) for i in range(today-14,today)]
    n=sum(x["n"] for x in d);days=sum(x["n"]>0 for x in d)
    v=[x["net"]*.1 for x in d];mean=sum(v)/len(v)
    sd=math.sqrt(sum((x-mean)**2 for x in v)/len(v))
    dd=float(a.get("dd",a.get("drawdown",1.)))
    score=mean-sd/math.sqrt(len(v))-dd/14
    eligible=n>=minimum and days>=MIN_DAYS and sum(x>0 for x in v)>=5 and score>0 and dd<=MAX_DD and now-e.get("last",0)<=72*3600
    return {"trades":n,"days":days,"net":sum(v),"score":score,"drawdown":dd,"eligible":eligible}
def update(group,rows):
    with LOCK:GROUPS[group]=(time.time(),rows)
def publish(key,kind,sym,side,model,stamp,expires,hold,stop):
    with LOCK:
        SIGNALS[key]={"key":key,"kind":kind,"symbol":sym,"side":side,"model":model,"time":stamp,"expires":expires,"hold":hold,"stop":stop}
def snapshot(now=None):
    now=time.time() if now is None else now
    with LOCK:
        for k in list(SIGNALS):
            if SIGNALS[k]["expires"]<now:del SIGNALS[k]
        rows=[dict(r) for ts,group in GROUPS.values() if now-ts<=150 for r in group]
        eligible=sorted((r for r in rows if r["eligible"]),key=lambda r:(-r["score"],r["key"]))
        leaders={}
        for r in eligible:leaders.setdefault(r["symbol"],r)
        signals=[dict(SIGNALS[r["key"]],rank=r["score"]) for r in leaders.values() if r["key"] in SIGNALS]
        signals.sort(key=lambda r:-r["rank"])
        return {"time":now,"evaluated":len(rows),"qualified":len(eligible),"leaders":list(leaders.values()),"top":eligible[:30],"signals":signals,
                "rule":"7 completed active UTC days, positive risk-adjusted net, fresh results, 30/100 closes, max 8% laboratory drawdown; one leader per underlying"}
def selftest():
    now=20*86400
    a={"dd":.001}
    for i in range(7,20):
        for j in range(8):record(a,.002,i*86400+100)
    assert assess(a,now,100)["eligible"]
    a["dd"]=.1;assert not assess(a,now,100)["eligible"]
    assert not assess({},now,30)["eligible"]
