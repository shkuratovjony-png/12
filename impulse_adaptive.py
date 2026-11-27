"""Adaptive historical replay. Separate from live trading; same risk and conservative market fees."""
import time,json,math,traceback
import numpy as np,pandas as pd
import store,paper_feed,impulse_research as old
KEY="research:impulse_adaptive:20260915:v2"
VARIANTS={"M5_30m":(6,2,1,False),"M5_15m":(3,2,1,False),"M5_60m":(12,2,1,False),"M5_60m_fixed":(12,2,None,False),"M5_30m_aligned":(6,2,1,True),"M5_60m_aligned":(12,2,1,True),"M5_30m_switch":(6,2,1,"switch"),"M5_60m_switch":(12,2,1,"switch")}
START=pd.Timestamp("2026-09-15",tz="UTC");END=pd.Timestamp("2026-09-22",tz="UTC")
F=.0006;SLIP=.0002;NEXT=0.
def get(path,**params):
 global NEXT
 while True:
  now=time.time()
  if now%3600<190 or now%300<50 or paper_feed.HTTP.locked():
   time.sleep(2);continue
  if time.monotonic()<NEXT:
   time.sleep(min(2,NEXT-time.monotonic()));continue
  NEXT=time.monotonic()+4
  try:return paper_feed.request(path,**params)
  except Exception as e:
   msg=str(e);wait=660 if 'HTTP 403' in msg else 120 if any(x in msg for x in ('cooldown','rate limit','HTTP 429')) else 30
   print("ADAPTIVE_COOLDOWN",path,wait,type(e).__name__,flush=True);time.sleep(wait)
def window(sym,interval,a,b):
 a=int(a.timestamp()*1000);b=int(b.timestamp()*1000);step=interval*60000;rows=[]
 for p in range(a,b,1000*step):
  q=min(b,p+1000*step)
  d=get("kline",symbol=sym,interval=str(interval),start=p,end=q-1,limit=1000)
  rows.extend(x for x in d["list"] if p<=int(x[0])<q)
 if not rows:return None
 d=pd.DataFrame(rows,columns=["time","open","high","low","close","volume","turnover"]).astype(float)
 d["time"]=pd.to_datetime(d.time.astype("int64"),unit="ms",utc=True)
 d=d.set_index("time").sort_index();d=d[~d.index.duplicated()]
 expected=pd.date_range(pd.Timestamp(a,unit="ms",tz="UTC"),pd.Timestamp(b-step,unit="ms",tz="UTC"),freq=f"{interval}min")
 return d if d.index.equals(expected) else None
def eligible(h,start=START,end=END):
 rv=h.volume.rolling(24).sum()/(h.volume.shift(24).rolling(720).sum()/30)
 ret=h.close/h.close.shift(24)-1;turn=h.turnover.rolling(24).sum()
 recent=h.close/h.close.shift(6)-1;ema=h.close.ewm(span=12,adjust=False).mean();slope=ema/ema.shift(3)-1
 # Earlier selection. Both directions, no BTC regime gate.
 out={}
 for side in (1,-1):
  mask=(side*ret>=.03)&(rv>=2)&(turn>=5e6)
  for t in h.index[mask.fillna(False)]:
   hour=t+pd.Timedelta(hours=1)
   if start<=hour<end:
    direction=1 if recent.loc[t]>0 and slope.loc[t]>0 else -1 if recent.loc[t]<0 and slope.loc[t]<0 else 0
    out[hour]=(side,float(rv.loc[t]),direction)
 return out
def setups(m,allowed,start=START,end=END):
 out=[];ts=m.index
 for side in (1,-1):
  o=side*m.open;c=side*m.close;h=m.high if side==1 else -m.low;l=m.low if side==1 else -m.high
  impulse=side*(m.close.shift(2)/m.open.shift(4)-1)
  signal=(impulse>=.006)&((c>o).shift(2).rolling(3).sum()>=2)&(c.shift(1)<o.shift(1))&(c>h.shift(1))&(c>o)
  for i in np.flatnonzero(signal.fillna(False).to_numpy())+1:
   if i<5 or i+12>=len(m):continue
   t=ts[i];f=allowed.get(t.floor("h"))
   if f is None or side not in (f[0],f[2]) or not start<=t<end:continue
   if ts[i+12]-ts[i-5]!=pd.Timedelta(minutes=85):continue
   e=float(m.open.iloc[i])*(1+side*SLIP)
   stop=float(m.low.iloc[i-2] if side==1 else m.high.iloc[i-2])*(1-side*.0002)
   dist=side*(e-stop)
   # Do not arbitrarily widen a technical stop. Reject uneconomic distances.
   if not .01<=dist/e<=.03 or side*(float(m.open.iloc[i])-stop)<=0:continue
   out.append((i,side,e,stop,dist,float(f[1]),f[0]==side,f[2]==side))
 return out
def funding(sym):
 d=get("funding/history",symbol=sym,startTime=int(START.timestamp()*1000),endTime=int(END.timestamp()*1000),limit=200)
 return {int(x["fundingRateTimestamp"])//60000:float(x["fundingRate"]) for x in d.get("list",[]) if "fundingRateTimestamp" in x and "fundingRate" in x}
def exits(sym,m,signals,rates,hold=6,target_r=2,trail_r=1,aligned=False,end=END):
 out=[];rows=m[["open","high","low","close"]].to_numpy();ts=m.index
 for i,side,e,stop,dist,score,daily,alignment in signals:
  if aligned=='switch':
   if not alignment:continue
  elif not daily or (aligned and not alignment):continue
  tp=e+side*target_r*dist;st=stop;fu=0.;best=e
  for j in range(i,i+hold+1):
   a,h,l,c=rows[j];bar=int(ts[j].timestamp()/60)
   if j>i and bar in rates:fu+=side*a*rates[bar]
   if j>i and (ts[j]>=end or j-i==hold):px=a;break
   if j>i and side*(a-st)<=0:px=a;break
   if j>i and side*(a-tp)>=0:px=tp;break
   if (l<=st if side==1 else h>=st):px=st;break
   if (h>=tp if side==1 else l<=tp):px=tp;break
   favorable=h if side==1 else l
   if side*(favorable-best)>0:best=favorable
   # Trail only after a completed candle has moved at least 1R.
   # A break-even stop accounts for estimated round-trip fees and slippage.
   if trail_r is not None and side*(best-e)>=trail_r*dist:
    breakeven=e+side*e*(2*F+SLIP)
    if side*(breakeven-st)>0:st=breakeven
  ex=px*(1-side*SLIP);fee=F*(e+ex);net=side*(ex-e)-fee-fu
  risk=dist+F*(e+stop)+SLIP*stop
  out.append([int(ts[i].timestamp()/60),-score,sym,int(ts[j].timestamp()/60),e,risk,net,fee,fu])
 return out
RISK_KEY="research:impulse_adaptive:20260915:v2:daily_risk"
def publish_daily_risk(state):
 try:
  import impulse_daily_risk as dr
  data=dr.compare(state["events"])
  report={"scanned":len(state["scanned"]),"universe":len(state["universe"]),"complete":state["complete"],"updated":time.time(),"models":data}
  store.put(RISK_KEY,json.loads(json.dumps(report,default=old.json_number)))
  compact={name:{p:{k:v[k] for k in ("roi","dd","trades","days","positive_days","negative_days")} for p,v in policies.items()} for name,policies in data.items()}
  print("ADAPTIVE_DAILY_RISK",json.dumps(dict(scanned=report["scanned"],universe=report["universe"],complete=report["complete"],models=compact),default=old.json_number,separators=(",",":")),flush=True)
 except Exception:
  traceback.print_exc()
def run(pilot=False):
 if not store.URL:return
 saved=store.get(old.CHECKPOINT_KEY)
 if not saved:return
 state=store.get(KEY,{"universe":saved["universe"],"scanned":[],"events":{k:[] for k in VARIANTS},"excluded":[],"candidates":{},"complete":False})
 if state["scanned"]:publish_daily_risk(state)
 if state.get("complete"):return
 syms=state["universe"]
 # Deterministic pilot: first 8 alphabetical previously selected instruments,
 # explicitly not an unbiased market sample. Finish entire frozen universe later.
 pilot_syms=sorted(saved.get("selected",{}))[:8]
 if not pilot_syms and pilot:return
 order=pilot_syms if pilot else list(dict.fromkeys(pilot_syms+syms))
 for sym in order:
  if sym in state["scanned"]:continue
  h=window(sym,60,START-pd.Timedelta(days=32),END)
  if h is None:state["excluded"].append(sym)
  else:
   allowed=eligible(h)
   if allowed:
    # At most 2016 five-minute bars for the week, fetched in three pages.
    m=window(sym,5,START-pd.Timedelta(minutes=30),END+pd.Timedelta(minutes=65))
    if m is None:state["excluded"].append(sym+":M5")
    else:
     sig=setups(m,allowed)
     state["candidates"][sym]=len(sig)
     if sig:
      rates=funding(sym)
      if not rates:state["excluded"].append(sym+":funding")
      else:
       for name,args in VARIANTS.items():state["events"][name].extend(exits(sym,m,sig,rates,*args))
  state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(syms)
  stats={name:old.simulate(ev) for name,ev in state["events"].items()};state["result"]=stats;state["updated"]=time.time()
  old.db_put(KEY,state)
  if pilot or state["complete"] or len(state["scanned"])%25==0:publish_daily_risk(state)
  print("ADAPTIVE_COMPARE",json.dumps(dict(scanned=len(state["scanned"]),universe=len(syms),pilot=pilot,complete=state["complete"],candidates=len(state["candidates"]),excluded=state["excluded"],results=stats),default=old.json_number,separators=(",",":")),flush=True)
