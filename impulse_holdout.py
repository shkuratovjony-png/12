"""Frozen September winner, October out-of-sample historical test.
No tuning, no order placement. Uses the same universe and execution/risk rules.
"""
import time,json
import pandas as pd
import store,impulse_adaptive as a,impulse_daily_risk as dr,impulse_research as old
KEY="research:adaptive_holdout:20261001:v1"
START=pd.Timestamp("2026-10-01",tz="UTC")
END=pd.Timestamp("2026-11-01",tz="UTC")
MODEL="M5_30m_switch"
def funding(sym,start=START,end=END):
 lo=int(start.timestamp()*1000);hi=int(end.timestamp()*1000)
 result={}
 # Backward pagination; include end boundary because positions may exit at END.
 while hi>=lo:
  d=a.get("funding/history",symbol=sym,startTime=lo,endTime=hi,limit=200)
  rows=d.get("list",[])
  if not rows:break
  stamps=[int(x["fundingRateTimestamp"]) for x in rows]
  for x,t in zip(rows,stamps):
   if lo<=t<=hi:result[t//60000]=float(x["fundingRate"])
  nxt=min(stamps)-1
  if nxt>=hi:raise ValueError("funding pagination failed")
  if len(rows)<200:break
  hi=nxt
 return result
def report(state):
 r=dr.replay(state["events"],"profit_lock")
 # Calendar coverage includes zero days, plus boundary settlement if present.
 for t in pd.date_range(START,END-pd.Timedelta(days=1),freq="D"):
  r["daily"].setdefault(t.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0,"entries":0})
 r["daily"]=dict(sorted(r["daily"].items()))
 r["flat_days"]=sum(v["pnl"]==0 for v in r["daily"].values())
 return r
def run():
 if not store.URL:return
 base=store.get(a.KEY)
 if not base or not base.get("complete"):return
 weekly=store.get(a.RISK_KEY)
 if weekly:
  r=weekly["models"][MODEL]["profit_lock"]
  print("ADAPTIVE_WEEK_FINAL",json.dumps(r,default=old.json_number,separators=(",",":")),flush=True)
 state=store.get(KEY,{"universe":base["universe"],"scanned":[],"excluded":[],"events":[],"candidates":{},"complete":False,"period":["2026-10-01","2026-10-31"],"model":MODEL,"policy":"profit_lock"})
 if state["complete"]:return
 for sym in state["universe"]:
  if sym in state["scanned"]:continue
  h=a.window(sym,60,START-pd.Timedelta(days=32),END)
  if h is None:state["excluded"].append(sym+":H1")
  else:
   allowed=a.eligible(h,START,END)
   if allowed:
    m=a.window(sym,5,START-pd.Timedelta(minutes=30),END+pd.Timedelta(minutes=65))
    if m is None:state["excluded"].append(sym+":M5")
    else:
     sig=a.setups(m,allowed,START,END)
     state["candidates"][sym]=len(sig)
     if sig:
      rates=funding(sym)
      if not rates:state["excluded"].append(sym+":funding")
      else:state["events"].extend(a.exits(sym,m,sig,rates,*a.VARIANTS[MODEL],end=END))
  state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(state["universe"])
  state["result"]=report(state);state["updated"]=time.time()
  old.db_put(KEY,state)
  print("ADAPTIVE_MONTH_RESULT",json.dumps({"scanned":len(state["scanned"]),"universe":len(state["universe"]),"symbol":sym,"complete":state["complete"],"excluded_count":len(state["excluded"]),"candidates":len(state["candidates"]),"result":state["result"]},default=old.json_number,separators=(",",":")),flush=True)
