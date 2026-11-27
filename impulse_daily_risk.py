"""Read-only portfolio replay with causal daily risk overlays.
No order placement, no market requests. Days UTC, realized PnL only.
Daily budgets are estimated stop-risk, not guaranteed loss limits.
"""
import heapq
from collections import defaultdict
from datetime import datetime,timezone
F=.0006
POLICIES={
 "base":(False,None,None),
 "soft":(True,None,None),
 "budget":(True,.015,None),
 "profit_lock":(True,.015,(.0075,.005)),
}
def replay(events,policy="base",start=1000.):
 soft,budget,lock=POLICIES[policy]
 cash=peak=start;dd=used=0.;active=[];symbols=set();days={};seq=0;trades=0;wins=0;fees=0.;funding=0.;skipped=defaultdict(int);entry_days=set();cur=None
 def roll(t):
  nonlocal cur
  day=t//1440
  if cur!=day:
   cur=day
   days[day]={"start":cash,"net":0.,"peak":0.,"loss_streak":0,"trades":0,"wins":0,"entries":0}
  return days[day]
 def settle():
  nonlocal cash,peak,dd,used,trades,wins,fees,funding
  end,_,sym,margin,net,fee,fu,risk=heapq.heappop(active)
  d=roll(end)
  symbols.remove(sym);used-=margin;cash+=net
  d["net"]+=net;d["peak"]=max(d["peak"],d["net"]);d["trades"]+=1;d["wins"]+=int(net>0)
  d["loss_streak"]=d["loss_streak"]+1 if net<0 else 0
  trades+=1;wins+=int(net>0);fees+=fee;funding+=fu;peak=max(peak,cash);dd=max(dd,1-cash/peak)
 for t,score,sym,end,e,risk,net,fee,fu in sorted(events):
  while active and active[0][0]<t:settle()
  d=roll(t)
  if sym in symbols or len(active)>=4 or cash<=20:skipped["capacity"]+=1;continue
  if not (e>0 and risk>0):skipped["bad_input"]+=1;continue
  fraction=.005
  if soft:
   if d["loss_streak"]>=2:fraction*=.5
   if d["loss_streak"]>=3 or d["net"]<=-.01*d["start"]:fraction=min(fraction,.00125)
  allowance=cash*fraction
  # Include all outstanding positions, including positions carried over midnight.
  reserved=sum(x[-1] for x in active)
  if budget is not None:allowance=min(allowance,max(0.,d["net"]+budget*d["start"]-reserved))
  if lock is not None and d["peak"]>=lock[0]*d["start"]:
   floor=max(0.,d["peak"]-lock[1]*d["start"])
   allowance=min(allowance,max(0.,d["net"]-floor-reserved))
  if allowance<=0:skipped["daily_budget"]+=1;continue
  q=min(allowance/risk,max(0.,cash-used)/(e*(.1+F)))
  if q*e<10:skipped["size"]+=1;continue
  margin=q*e*(.1+F);used+=margin;symbols.add(sym);seq+=1;entry_days.add(t//1440);d["entries"]+=1
  heapq.heappush(active,(end,seq,sym,margin,net*q,fee*q,fu*q,risk*q))
 while active:settle()
 daily={datetime.fromtimestamp(k*86400,timezone.utc).strftime("%Y-%m-%d"):{"pnl":round(v["net"],4),"roi":round(100*v["net"]/v["start"],4) if v["start"]>0 else None,"trades":v["trades"],"entries":v["entries"]} for k,v in sorted(days.items())}
 return dict(balance=round(cash,4),roi=round(100*(cash/start-1),4),dd=round(100*dd,4),trades=trades,wins=wins,days=len(entry_days),positive_days=sum(v["pnl"]>0 for v in daily.values()),negative_days=sum(v["pnl"]<0 for v in daily.values()),fees=round(fees,4),funding=round(funding,4),daily=daily,skipped=dict(skipped))
def compare(variants):
 import impulse_research as old
 out={}
 for name,ev in variants.items():
  base=replay(ev)
  expected=old.simulate(ev)
  if abs(base["balance"]-expected["balance"])>.011 or base["trades"]!=expected["trades"]:raise AssertionError("daily replay mismatch: "+name)
  out[name]={p:replay(ev,p) for p in POLICIES}
 return out
