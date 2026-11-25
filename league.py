"""Paper-only champion/challenger competition; comparable daily net returns.
Selection is not statistical proof of future profit. No order API."""
import time,math,threading
LOCK=threading.RLock()
GROUPS={};SIGNALS={}
RECENT_SECONDS=12*3600
MAX_DD=.08
def record(a,ret,now):
    e=a.setdefault("league_evidence",{"days":{},"last":0})
    k=str(int(now//86400));d=e["days"].setdefault(k,{"n":0,"net":0.})
    d["n"]+=1;d["net"]+=float(ret);e["last"]=now
    recent=e.setdefault("recent",[]);recent.append([now,float(ret)])
    e["recent"]=[x for x in recent[-512:] if now-x[0]<=RECENT_SECONDS]
    e["days"]={k:e["days"][k] for k in sorted(e["days"])[-30:]}
def assess(a,now,minimum):
    e=a.get("league_evidence",{});today=int(now//86400)
    recent=[x for x in e.get("recent",[]) if 0<=now-x[0]<=RECENT_SECONDS]
    # Old records contain only daily totals. Permit small provisional allocation
    # based on today's and yesterday's totals only until precise recent evidence accrues.
    fast=10 if minimum>=100 else 3
    legacy=False
    if len(recent)>=fast:
        vals=[x[1] for x in recent];n=len(vals);net=sum(vals)
        mean=net/n;sd=math.sqrt(sum((x-mean)**2 for x in vals)/n)
        days=len({int(x[0]//86400) for x in recent})
        score=mean-sd/math.sqrt(n)*.5
    else:
        d=[e.get("days",{}).get(str(i),{"n":0,"net":0.}) for i in (today-1,today)]
        n=sum(x["n"] for x in d);days=sum(x["n"]>0 for x in d);net=sum(x["net"] for x in d)
        mean=net/max(1,n);score=mean*.5;legacy=True
    dd=float(a.get("dd",a.get("drawdown",1.)))
    eligible=n>=fast and net>0 and score>0 and dd<=MAX_DD and 0<=now-e.get("last",0)<=7200
    # Provisional paper entry, not evidence sufficient for real-money trading.
    tier="none";allocation=0.
    if eligible:
        tier="trial";allocation=.025
        if not legacy and n>=(30 if minimum>=100 else 10) and dd<=.04:
            tier="developing";allocation=.05
        if not legacy and n>=(100 if minimum>=100 else 30) and dd<=.025 and mean>0 and score>0:
            tier="leader";allocation=.10
    pilot=minimum<100 and not eligible and dd<=.02 and n<fast and net>=0 and float(a.get("net_sum",0))>=0 and (n==0 or 0<=now-e.get("last",0)<=RECENT_SECONDS)
    return {"pilot":pilot,"trades":n,"days":days,"net":net*.1,"score":score,"drawdown":dd,"eligible":eligible,"tier":tier,"allocation":allocation,"evidence":"daily_legacy" if legacy else "last_12h"}
def update(group,rows):
    with LOCK:GROUPS[group]=(time.time(),rows)
def publish(key,kind,sym,side,model,stamp,expires,hold,stop):
    with LOCK:
        SIGNALS[key]={"key":key,"kind":kind,"symbol":sym,"side":side,"model":model,"time":stamp,"expires":expires,"hold":hold,"stop":stop}
def grid_signals(now=None):
    now=time.time() if now is None else now
    with LOCK:
        return [dict(q,rank=0.,research_evidence=bool(q["model"].get("historical_approved")),tier="grid_demo",allocation=.075) for q in SIGNALS.values() if q["model"].get("demo_grid") and q["time"]<=now<=q["expires"]]
def blocked(trades,now):
    groups={}
    for t in trades:
        k=t.get("strategy_id")
        if k and now-t.get("closed",0)<86400:groups.setdefault(k,[]).append(t)
    return {k for k,ts in groups.items() if len(ts)>=2 and now-ts[-1]["closed"]<1800 and sum(t["pnl"] for t in ts[-min(5,len(ts)):])<0 and (ts[-1]["pnl"]<0 and ts[-2]["pnl"]<0 or len(ts)>=5)}
def revoke(category,symbol=None):
    with LOCK:
        for k in list(SIGNALS):
            r=SIGNALS[k]
            if r["kind"]==category and (symbol is None or r["symbol"]==symbol):del SIGNALS[k]
def snapshot(now=None,excluded=()):
    now=time.time() if now is None else now
    with LOCK:
        for k in list(SIGNALS):
            if SIGNALS[k]["expires"]<now:del SIGNALS[k]
        rows=[dict(r) for ts,group in GROUPS.values() if now-ts<=150 for r in group]
        eligible=sorted((r for r in rows if r["eligible"] and r["key"] not in excluded),key=lambda r:(-r["score"],r["key"]))
        leaders={}
        for r in eligible:leaders.setdefault(r["symbol"],r)
        # Best qualified model with a current signal on each underlying; idle leaders do not block contenders.
        ready={}
        for r in eligible:
            if r["key"] in SIGNALS:ready.setdefault(r["symbol"],dict(SIGNALS[r["key"]],rank=r["score"],allocation=r["allocation"],tier=r["tier"],research_evidence=True))
        signals=sorted(ready.values(),key=lambda r:-r["rank"])
        import hashlib
        pilots=sorted((r for r in rows if (r.get("pilot") or r.get("historical")) and not r["eligible"] and r["key"] not in excluded and r["key"] in SIGNALS),key=lambda r:(-int(bool(r.get("historical")) or r["trades"]>0 and r["net"]>0),-r["trades"],-r.get("historical_score",0),-r["score"],hashlib.sha256((str(int(now//900))+r["key"]).encode()).hexdigest()))
        used=set(ready)
        for r in pilots:
            if r["symbol"] in used:continue
            used.add(r["symbol"])
            signals.append(dict(SIGNALS[r["key"]],rank=r["score"],allocation=.025 if r.get("historical") else .03,tier="practice",research_evidence=bool(r.get("historical") or r["trades"]>0 and r["net"]>0)))
        return {"time":now,"evaluated":len(rows),"qualified":len(eligible),"practice_signals":sum(s["tier"]=="practice" for s in signals),"cooldown":sorted(excluded),"leaders":list(leaders.values()),"top":eligible[:30],"signals":signals,
                "rule":"Paper-only fast admission: 3 swing / 10 scalp closes, positive net and risk-adjusted score, evidence fresh within 2h, 2.5/5/10% allocation, max 8% lab drawdown; no calendar wait; 3% practice on fresh forward signals with no observed net losses"}
def selftest():
    now=20*86400+3600
    a={"dd":.001}
    for i in range(3):record(a,.002,now-60+i)
    assert assess(a,now,30)["eligible"] and assess(a,now,30)["allocation"]==.025
    assert not assess(a,now,100)["eligible"]
    for i in range(30):record(a,.002,now-30+i)
    assert assess(a,now,30)["allocation"]==.10
    assert assess(a,now,100)["allocation"]==.05
    assert not assess(a,now+7201,30)["eligible"]
    a["dd"]=.1;assert not assess(a,now,30)["eligible"]
    assert not assess({},now,30)["eligible"]
    assert assess({"drawdown":0.,"net_sum":0.},now,30)["pilot"]
    assert not assess({"drawdown":0.,"net_sum":-.01},now,30)["pilot"]
    assert not assess({"dd":0.},now,100)["pilot"]
    b={"dd":.001}
    for i in range(10):record(b,-.002,now-20+i)
    assert not assess(b,now,100)["eligible"]
