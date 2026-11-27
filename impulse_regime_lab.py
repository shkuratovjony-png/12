"""Research-only regime models. Uses closed bars; no orders or account keys.
This module is staged separately so the current ADAPTIVE V2 run is not interrupted.
"""
import numpy as np,pandas as pd
import impulse_adaptive as a
F=.0006;SLIP=.0002
NAMES=("trend_pullback","range_reclaim","regime_combined")
def hourly_context(h,start,end):
 close=h.close
 movement=close.diff().abs().rolling(12).sum()
 efficiency=(close-close.shift(12)).abs()/movement.replace(0,np.nan)
 ema=close.ewm(span=12,adjust=False).mean()
 trend=np.sign(close/close.shift(6)-1)
 slope=np.sign(ema-ema.shift(3))
 turnover=h.turnover.rolling(24).sum()
 out={}
 for t in h.index:
  hour=t+pd.Timedelta(hours=1)
  if not start<=hour<end or not np.isfinite(efficiency.loc[t]) or turnover.loc[t]<5e6:continue
  er=float(efficiency.loc[t]);direction=int(trend.loc[t]) if trend.loc[t]==slope.loc[t] else 0
  out[hour]=(er,direction)
 return out
def candidates(sym,m,context,start,end,rates):
 result={k:[] for k in NAMES}
 atr=pd.concat([m.high-m.low,(m.high-m.close.shift()).abs(),(m.low-m.close.shift()).abs()],axis=1).max(axis=1).rolling(14).mean()
 rows=m[["open","high","low","close"]].to_numpy();ts=m.index
 for side in (1,-1):
  o=side*m.open;c=side*m.close;hi=m.high if side==1 else -m.low;lo=m.low if side==1 else -m.high
  ema=c.ewm(span=20,adjust=False).mean()
  support=lo.shift(1).rolling(12).min();resistance=hi.shift(1).rolling(12).max()
  midpoint=(support+resistance)/2
  # Reclaim of a prior one-hour extreme; not an arbitrary fade of an active trend.
  reclaim=(lo<support)&(c>support)&(c>o)
  # Trend entry only after a pullback to a local average and reclaim.
  pullback=(lo.shift(1)<=ema.shift(1))&(c>ema)&(c>hi.shift(1))&(c>o)
  for family,mask in (("trend_pullback",pullback),("range_reclaim",reclaim)):
   for k in np.flatnonzero(mask.fillna(False).to_numpy()):
    i=k+1
    if k<20 or i+12>=len(rows):continue
    t=ts[i];ctx=context.get(t.floor("h"))
    if ctx is None or not start<=t<end:continue
    if ts[i+12]-ts[k-20]!=pd.Timedelta(minutes=165):continue
    er,direction=ctx
    if family=="trend_pullback":
     if er<.4 or direction!=side:continue
    elif er>.25:continue
    v=float(atr.iloc[k])
    if not np.isfinite(v) or v<=0:continue
    e=float(rows[i,0])*(1+side*SLIP)
    swing=float(min(lo.iloc[k-1],lo.iloc[k]))
    st=side*(swing-.15*v)
    dist=side*(e-st)
    if not .008<=dist/e<=.035 or side*(float(rows[i,0])-st)<=0:continue
    tp=e+side*2*dist if family=="trend_pullback" else side*float(midpoint.iloc[k])
    # Reward must cover modeled cost and still justify the stop.
    cost=e*(2*F+2*SLIP)
    if side*(tp-e)-cost<1.5*(dist+cost):continue
    best=e;fu=0.;initial=st;hold=6 if family=="range_reclaim" else 12
    for j in range(i,i+hold+1):
     op,h,l,cl=rows[j];minute=int(ts[j].timestamp()/60)
     if j>i and minute in rates:fu+=side*op*rates[minute]
     if j>i and (j-i==hold or ts[j]>=end):px=op;break
     if j>i and side*(op-st)<=0:px=op;break
     if j>i and side*(op-tp)>=0:px=tp;break
     if (l<=st if side==1 else h>=st):px=st;break
     if (h>=tp if side==1 else l<=tp):px=tp;break
     favorable=h if side==1 else l
     if side*(favorable-best)>0:best=favorable
     if side*(best-e)>=dist:
      be=e+side*e*(2*F+SLIP)
      if side*(be-st)>0:st=be
    ex=px*(1-side*SLIP);fee=F*(e+ex);risk=dist+F*(e+initial)+SLIP*initial
    event=[int(t.timestamp()/60),-float((side*(tp-e)-cost)/risk),sym,int(ts[j].timestamp()/60),e,risk,side*(ex-e)-fee-fu,fee,fu]
    result[family].append(event);result["regime_combined"].append(event)
 return result

KEY="research:impulse_regime:20260915:v3"
def run():
 import store,impulse_research as old,impulse_daily_risk as dr,json,time
 if not store.URL:return
 base=store.get(a.KEY)
 if not base or not base.get("complete"):
  print("REGIME_WAIT: V2 comparison incomplete",flush=True);return
 start,end=a.START,a.END
 state=store.get(KEY,{"universe":base["universe"],"scanned":[],"excluded":[],"events":{k:[] for k in NAMES},"complete":False})
 if state["complete"]:return
 for sym in state["universe"]:
  if sym in state["scanned"]:continue
  h=a.window(sym,60,start-pd.Timedelta(days=2),end)
  if h is None:state["excluded"].append(sym+":H1")
  else:
   context=hourly_context(h,start,end)
   context={t:v for t,v in context.items() if (v[0]>=.4 and v[1]) or v[0]<=.25}
   if context:
    m=a.window(sym,5,start-pd.Timedelta(minutes=120),end+pd.Timedelta(minutes=65))
    if m is None:state["excluded"].append(sym+":M5")
    else:
     rates=a.funding(sym)
     if not rates:state["excluded"].append(sym+":funding")
     else:
      result=candidates(sym,m,context,start,end,rates)
      for name,ev in result.items():state["events"][name].extend(ev)
  state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(state["universe"])
  state["result"]={name:dr.replay(ev,"soft") for name,ev in state["events"].items()}
  state["updated"]=time.time()
  old.db_put(KEY,state)
  print("REGIME_RESULT",json.dumps({"scanned":len(state["scanned"]),"universe":len(state["universe"]),"complete":state["complete"],"results":state["result"]},default=old.json_number,separators=(",",":")),flush=True)
