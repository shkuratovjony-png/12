"""October research only. Recovery sizing uses realized outcomes, never the next trade's PnL.
No exchange orders. Risk caps are estimates, not guarantees against gaps.
"""
import heapq,json,time
from collections import defaultdict
from datetime import datetime,timezone
import pandas as pd
import store,impulse_adaptive as a,impulse_holdout as h,impulse_research as old,impulse_daily_risk as dr
KEY="research:adaptive_recovery:october:v1"
POLICIES=("fixed","recovery125","recovery150","recovery200","smart","anti")
BASE=.0025
CAP=.01
BUDGET=.015
TARGET=.01
def replay(events,policy,start=1000.):
    cash=peak=start;dd=used=0.;active=[];symbols=set();days={};seq=trades=wins=0;fees=funding=0.
    skipped=defaultdict(int);entry_days=set();cur=None;maxrisk=0.;maxstreak=0
    def roll(t):
        nonlocal cur
        day=t//1440
        if cur!=day:
            cur=day;days[day]={"start":cash,"net":0.,"loss":0,"win":0,"trades":0,"entries":0}
        return days[day]
    def settle():
        nonlocal cash,peak,dd,used,trades,wins,fees,funding,maxstreak
        end,_,sym,margin,pnl,fee,fu,risk=heapq.heappop(active)
        d=roll(end);symbols.remove(sym);used-=margin;cash+=pnl
        d["net"]+=pnl;d["trades"]+=1
        d["loss"]=d["loss"]+1 if pnl<0 else 0
        d["win"]=d["win"]+1 if pnl>0 else 0
        maxstreak=max(maxstreak,d["loss"])
        trades+=1;wins+=int(pnl>0);fees+=fee;funding+=fu
        peak=max(peak,cash);dd=max(dd,1-cash/peak)
    for t,score,sym,end,e,risk,net,fee,fu in sorted(events):
        while active and active[0][0]<t:settle()
        d=roll(t)
        if cash<=20 or sym in symbols or len(active)>=4:skipped["capacity"]+=1;continue
        if e<=0 or risk<=0:skipped["bad_input"]+=1;continue
        if d["net"]>=TARGET*d["start"]:skipped["target"]+=1;continue
        frac=BASE
        mult={"recovery125":1.25,"recovery150":1.5,"recovery200":2.}.get(policy)
        if mult and d["net"]<0:frac=min(CAP,BASE*mult**min(d["loss"],2))
        if policy=="anti":frac=min(CAP,BASE*1.5**min(d["win"],2)) if d["loss"]==0 else BASE/2
        desired=cash*frac
        if policy=="smart" and d["net"]<0:
            # 2R is a nominal target, not a forecast of the next realized payout.
            desired=min(cash*CAP,max(cash*BASE,(TARGET*d["start"]-d["net"])/2))
        reserved=sum(x[-1] for x in active)
        allowance=min(desired,max(0.,BUDGET*d["start"]+d["net"]-reserved))
        if allowance<=0:skipped["daily_budget"]+=1;continue
        q=min(allowance/risk,max(0.,cash-used)/(e*(.1+dr.F)))
        if q*e<10:skipped["size"]+=1;continue
        margin=q*e*(.1+dr.F);used+=margin;symbols.add(sym);seq+=1
        entry_days.add(t//1440);d["entries"]+=1;maxrisk=max(maxrisk,risk*q/cash)
        heapq.heappush(active,(end,seq,sym,margin,net*q,fee*q,fu*q,risk*q))
    while active:settle()
    daily={datetime.fromtimestamp(k*86400,timezone.utc).strftime("%Y-%m-%d"):{"pnl":round(v["net"],4),"roi":round(100*v["net"]/v["start"],4),"trades":v["trades"],"entries":v["entries"]} for k,v in sorted(days.items())}
    return dict(balance=round(cash,4),roi=round(100*(cash/start-1),4),dd=round(100*dd,4),trades=trades,wins=wins,days=len(entry_days),positive_days=sum(v["pnl"]>0 for v in daily.values()),negative_days=sum(v["pnl"]<0 for v in daily.values()),fees=round(fees,4),funding=round(funding,4),daily=daily,skipped=dict(skipped),max_risk_pct=round(100*maxrisk,4),max_loss_streak=maxstreak)
def report(state):
    events=state["events"]
    results={"control":dr.replay(events,"profit_lock")}
    results.update({p:replay(events,p) for p in POLICIES})
    for r in results.values():
        for t in pd.date_range(h.START,h.END-pd.Timedelta(days=1),freq="D"):
            r["daily"].setdefault(t.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0,"entries":0})
        r["daily"]=dict(sorted(r["daily"].items()))
        r["flat_days"]=sum(v["pnl"]==0 for v in r["daily"].values())
    state["result"]=results;state["updated"]=time.time()
    old.db_put(KEY,state)
    compact={k:{n:v[n] for n in ("balance","roi","dd","trades","wins","positive_days","negative_days","flat_days","fees","funding")} | {n:v[n] for n in ("max_risk_pct","max_loss_streak") if n in v} for k,v in results.items()}
    print("ADAPTIVE_RECOVERY_RESULT",json.dumps({"scanned":len(state["scanned"]),"universe":len(state["universe"]),"complete":state["complete"],"excluded_count":len(state["excluded"]),"result":compact},default=old.json_number),flush=True)
def run():
    if not store.URL:return
    state=store.get(KEY)
    if not state:
        # Reuse exactly the archived V3 baseline candidate events, not selected winners.
        prev=store.get("research:adaptive_entry_quality:october:v1")
        if not prev:raise RuntimeError("October checkpoint unavailable")
        state={"universe":prev["universe"],"scanned":prev["scanned"],"excluded":prev["excluded"],"events":prev["events"]["baseline"],"complete":prev["complete"],"reused":len(prev["scanned"])}
    report(state)
    if state["complete"]:return
    for sym in state["universe"]:
        if sym in state["scanned"]:continue
        hourly=a.window(sym,60,h.START-pd.Timedelta(days=32),h.END)
        if hourly is None:state["excluded"].append(sym+":H1")
        else:
            allowed=a.eligible(hourly,h.START,h.END)
            if allowed:
                m=a.window(sym,5,h.START-pd.Timedelta(minutes=120),h.END+pd.Timedelta(minutes=65))
                if m is None:state["excluded"].append(sym+":M5")
                else:
                    sig=a.setups(m,allowed,h.START,h.END)
                    if sig:
                        rates=h.funding(sym)
                        if not rates:state["excluded"].append(sym+":funding")
                        else:state["events"].extend(a.exits(sym,m,sig,rates,*a.VARIANTS[h.MODEL],end=h.END))
        state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(state["universe"])
        report(state)
