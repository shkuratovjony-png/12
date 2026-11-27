"""Adaptive historical replay. Separate from live trading; same risk and conservative market fees."""
import time,json,math,traceback
import numpy as np,pandas as pd
import store,paper_feed,impulse_research as old
KEY="research:impulse_adaptive:20260915:v1"
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
def eligible(h):
 rv=h.volume.rolling(24).sum()/(h.volume.shift(24).rolling(720).sum()/30)
 ret=h.close/h.close.shift(24)-1;turn=h.turnover.rolling(24).sum()
 # Earlier selection. Both directions, no BTC regime gate.
 out={}
 for side in (1,-1):
  mask=(side*ret>=.03)&(rv>=2)&(turn>=5e6)
  for t in h.index[mask.fillna(False)]:
   hour=t+pd.Timedelta(hours=1)
   if START<=hour<END:out[hour]=(side,float(rv.loc[t]))
 return out
def setups(m,allowed):
 out=[];ts=m.index
 for side in (1,-1):
  o=side*m.open;c=side*m.close;h=m.high if side==1 else -m.low;l=m.low if side==1 else -m.high
  impulse=side*(m.close.shift(2)/m.open.shift(4)-1)
  signal=(impulse>=.006)&((c>o).shift(2).rolling(3).sum()>=2)&(c.shift(1)<o.shift(1))&(c>h.shift(1))&(c>o)
  for i in np.flatnonzero(signal.fillna(False).to_numpy())+1:
   if i<5 or i+6>=len(m):continue
   t=ts[i];f=allowed.get(t.floor("h"))
   if f is None or f[0]!=side or not START<=t<END:continue
   if ts[i+6]-ts[i-5]!=pd.Timedelta(minutes=55):continue
   e=float(m.open.iloc[i])*(1+side*SLIP)
   stop=float(m.low.iloc[i-2] if side==1 else m.high.iloc[i-2])*(1-side*.0002)
   dist=side*(e-stop)
   # Do not arbitrarily widen a technical stop. Reject uneconomic distances.
   if not .01<=dist/e<=.03 or side*(float(m.open.iloc[i])-stop)<=0:continue
   out.append((i,side,e,stop,dist,float(f[1])))
 return out
def funding(sym):
 d=get("funding/history",symbol=sym,startTime=int(START.timestamp()*1000),endTime=int(END.timestamp()*1000),limit=200)
 return {int(x["fundingRateTimestamp"])//60000:float(x["fundingRate"]) for x in d.get("list",[]) if "fundingRateTimestamp" in x and "fundingRate" in x}
def exits(sym,m,signals,rates):
 out=[];rows=m[["open","high","low","close"]].to_numpy();ts=m.index
 for i,side,e,stop,dist,score in signals:
  tp=e+side*2*dist;st=stop;fu=0.;best=e
  for j in range(i,i+7):
   a,h,l,c=rows[j];bar=int(ts[j].timestamp()/60)
   if j>i and bar in rates:fu+=side*a*rates[bar]
   if j>i and (ts[j]>=END or j-i==6):px=a;break
   if j>i and side*(a-st)<=0:px=a;break
   if j>i and side*(a-tp)>=0:px=tp;break
   if (l<=st if side==1 else h>=st):px=st;break
   if (h>=tp if side==1 else l<=tp):px=tp;break
   favorable=h if side==1 else l
   if side*(favorable-best)>0:best=favorable
   # Trail only after a completed candle has moved at least 1R.
   # A break-even stop accounts for estimated round-trip fees and slippage.
   if side*(best-e)>=dist:
    breakeven=e+side*e*(2*F+SLIP)
    if side*(breakeven-st)>0:st=breakeven
  ex=px*(1-side*SLIP);fee=F*(e+ex);net=side*(ex-e)-fee-fu
  risk=dist+F*(e+stop)+SLIP*stop
  out.append([int(ts[i].timestamp()/60),-score,sym,int(ts[j].timestamp()/60),e,risk,net,fee,fu])
 return out
def run(pilot=False):
 if not store.URL:return
 saved=store.get(old.CHECKPOINT_KEY)
 if not saved:return
 state=store.get(KEY,{"universe":saved["universe"],"scanned":[],"events":[],"excluded":[],"candidates":{},"complete":False})
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
    m=window(sym,5,START-pd.Timedelta(minutes=30),END+pd.Timedelta(minutes=35))
    if m is None:state["excluded"].append(sym+":M5")
    else:
     sig=setups(m,allowed)
     state["candidates"][sym]=len(sig)
     if sig:
      rates=funding(sym)
      if not rates:state["excluded"].append(sym+":funding")
      else:state["events"].extend(exits(sym,m,sig,rates))
  state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(syms)
  stats=old.simulate(state["events"]);state["result"]=stats;state["updated"]=time.time()
  old.db_put(KEY,state)
  print("ADAPTIVE_RESULT",json.dumps(dict(scanned=len(state["scanned"]),universe=len(syms),pilot=pilot,complete=state["complete"],candidates=len(state["candidates"]),excluded=state["excluded"],results=stats),default=old.json_number,separators=(",",":")),flush=True)
