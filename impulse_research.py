"""Read-only research, isolated from trading. No account keys or private endpoints."""
import os,time,json,threading,heapq,traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import numpy as np,pandas as pd,requests
ROOT=Path('/tmp/multicoin');ROOT.mkdir(exist_ok=True)
STATUS={'state':'starting'}; RESULTS={}; SESSION=requests.Session(); NEXT=0.
BASE='https://api.bybit.com/v5/market/'
START=pd.Timestamp('2026-08-11',tz='UTC'); END=pd.Timestamp('2026-11-22',tz='UTC')
F=.0006; SLIP=.0002; RISK=.005
NAMES=['Cameron','Wagner_proxy','Mancini','CIS','Nill_proxy']
CORE=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','LINKUSDT','AVAXUSDT','ADAUSDT','BNBUSDT','LTCUSDT']
import store,paper_feed
CHECKPOINT_KEY='research:impulse_pro:20260915:v2:checkpoint'
REPORT_KEY='research:impulse_pro:20260915:v2:report'
def db_put(key,value):
 # Retry DB failures in research only; never terminate the trading worker.
 while True:
  try:store.put(key,json.loads(json.dumps(value,default=json_number)));return
  except Exception as e:
   print('IMPULSE_DB_RETRY',type(e).__name__,flush=True);time.sleep(30)
def publish():
 db_put(REPORT_KEY,dict(status=dict(STATUS),results=dict(RESULTS),updated=time.time()))
def get(path,**params):
 global NEXT
 delay=4.;attempt=0
 while True:
  # Yield to scheduled trading scans and respect the existing shared API limiter.
  now=time.time()
  if now%3600<190 or now%300<50 or paper_feed.HTTP.locked():
   time.sleep(2);continue
  if time.monotonic()<NEXT:
   time.sleep(min(2,NEXT-time.monotonic()));continue
  NEXT=time.monotonic()+4
  try:
   d=paper_feed.request(path,**params)
   STATUS.update(state='running',retry_at=None,last_api_ok=time.time());return d
  except Exception as e:
   msg=str(e);attempt+=1
   wait=660 if 'HTTP 403' in msg else 120 if any(x in msg for x in ('cooldown','rate limit','HTTP 429')) else min(300,delay)
   STATUS.update(state='api_cooldown',retry_at=time.time()+wait,retry_attempt=attempt)
   print('IMPULSE_COOLDOWN',path,attempt,wait,type(e).__name__,flush=True);publish()
   time.sleep(wait);delay=min(900,max(delay*2,wait*2))
def universe():
 out={};cursor=''
 while True:
  r=get('instruments-info',limit=1000,**({'cursor':cursor} if cursor else {}))
  for x in r['list']:
   if x.get('contractType')=='LinearPerpetual' and x.get('settleCoin')=='USDT' and x.get('status')=='Trading':
    out[x['symbol']]=int(x.get('launchTime') or 0)
  cursor=r.get('nextPageCursor')
  if not cursor:return out
def download(sym,start,end,launch):
 a=max(int(start.timestamp()*1000),((launch+59999)//60000)*60000);b=int(end.timestamp()*1000)
 if a>=b:return None
 fn=ROOT/(sym+'_'+start.strftime('%Y%m%d')+'.csv.gz')
 if fn.exists():return pd.read_csv(fn,index_col='time',parse_dates=True)
 rows=[];p=a
 while p<b:
  endpage=min(p+1000*60000,b)
  d=get('kline',symbol=sym,interval='1',start=p,end=endpage-1,limit=1000)
  rows.extend(r for r in d['list'] if p<=int(r[0])<endpage)
  p=endpage
 if not rows:return None
 m=pd.DataFrame(rows,columns=['time','open','high','low','close','volume','turnover']).astype(float)
 m['time']=pd.to_datetime(m.time.astype('int64'),unit='ms',utc=True)
 m=m.set_index('time').sort_index();m=m[~m.index.duplicated()]
 expected=pd.date_range(pd.Timestamp(a,unit='ms',tz='UTC'),pd.Timestamp(b-60000,unit='ms',tz='UTC'),freq='min')
 if not m.index.equals(expected):
  print('RESEARCH_GAPS',sym,len(m),len(expected),flush=True);return None
 m.to_csv(fn,compression='gzip')
 return m
agg={'open':'first','high':'max','low':'min','close':'last','volume':'sum','turnover':'sum'}
def signed(d,s):
 return (d.open,d.high,d.low,d.close) if s==1 else (-d.open,-d.low,-d.high,-d.close)
def generate(m):
 out={k:[] for k in NAMES};idx=m.index
 liquid=m.turnover.shift(1).rolling(1440,min_periods=1440).sum()
 rv=m.turnover.shift(1).rolling(5).mean()/m.turnover.shift(6).rolling(60).mean()
 def add(key,d,mask,s,stop,target,hold,step):
  for t in d.index[mask.fillna(False)]:
   i=idx.searchsorted(t+pd.Timedelta(minutes=step))
   if i>=len(idx) or not np.isfinite(stop.loc[t]) or liquid.iloc[i]<5e6 or not np.isfinite(liquid.iloc[i]):continue
   score=float(rv.iloc[i]);score=score if np.isfinite(score) else 0.
   out[key].append((i,s,float(s*stop.loc[t]),None if target is None else float(s*target.loc[t]),hold,score))
 for s in (1,-1):
  o,h,l,c=signed(m,s);p=m.close;v=m.turnover
  imp=s*(p.shift(3)/p.shift(8)-1);iv=v.shift(3).rolling(5).mean();base=v.shift(8).rolling(60).mean()
  mask=(imp>=.003)&(iv>=2*base)&(c.shift(1)<o.shift(1))&(c.shift(2)<o.shift(2))&(v.shift(1).rolling(2).mean()<iv)&(c>h.shift(1))&(c>o)&(l.shift(1).rolling(2).min()>c.shift(8)+.5*(c.shift(3)-c.shift(8)))
  add('Cameron',m,mask,s,l.shift(1).rolling(2).min()-.0002*p,None,60,1)
  lev=h.shift(1).rolling(20).max();first=(c>lev)&(c.shift(1)<=lev.shift(1));trig=h.where(first).shift(1).ffill(limit=3);anchor=l.where(first).shift(1).ffill(limit=3)
  mask=(c>trig)&(c.shift(1)<=trig)&(v>v.shift(1).rolling(30).mean())
  add('Wagner_proxy',m,mask,s,anchor-.0002*p,None,1,1)
  d=m.resample('5min').agg(agg);o,h,l,c=signed(d,s);p=d.close;v=d.turnover
  sup=l.shift(1).rolling(24).min();res=h.shift(1).rolling(24).max();sweep=(l<sup-.0003*p)&(c>sup)&(c>o)
  mask=sweep.shift(1,fill_value=False)&(c>sup.shift(1))&(c>c.shift(1))
  add('Mancini',d,mask,s,l.shift(1)-.0002*p,((sup+res)/2).shift(1),120,5)
  mask=(s*p.pct_change(12)>=.005)&(c>h.shift(1).rolling(12).max())&(v>=2*v.shift(1).rolling(48).mean())
  add('CIS',d,mask,s,l.rolling(3).min()-.0002*p,None,60,5)
  d=m.resample('15min').agg(agg);o,h,l,c=signed(d,s);p=d.close;v=d.turnover
  rh=h.shift(1).rolling(4).max();rl=l.shift(1).rolling(4).min();w=rh-rl
  impulse=p.shift(5).pct_change(4).abs();avg=v.shift(5).rolling(4).mean();normal=v.shift(9).rolling(48).mean()
  mask=(impulse>=.008)&(avg>=1.5*normal)&(w/p<=.006)&(l<=rl+.15*w)&(c>rl+.25*w)&(c>o)&(c<rh)
  add('Nill_proxy',d,mask,s,np.minimum(l,rl)-.0002*p,rh,240,15)
 return out
def candidates(sym,m,start):
 bars=m[['open','high','low','close']].to_numpy();ts=m.index.asi8//60000000000
 startmin=int(start.timestamp()/60);out={k:[] for k in NAMES}
 for name,signals in generate(m).items():
  for i,s,st,tp,hold,score in signals:
   if ts[i]<startmin:continue
   o=bars[i,0];e=o*(1+s*SLIP);dist=s*(e-st)
   if dist<=0:continue
   if dist/e<.0015:st=e-s*.0015*e;dist=.0015*e
   if s*(o-st)<=0 or dist/e>.03:continue
   if tp is None:tp=e+s*2*dist
   if not np.isfinite(tp) or s*(tp-e)<dist:continue
   last=min(i+hold,len(bars)-1);fund=0.
   for j in range(i,last+1):
    a,h,l,c=bars[j]
    if j>i and s*(a-st)<=0:px=a;break
    if j>i and s*(a-tp)>=0:px=tp;break
    if j-i>=hold:px=a;break
    if j>i and ts[j]%480==0:fund+=a*.0001
    if (l<=st if s==1 else h>=st):px=st;break
    if (h>=tp if s==1 else l<=tp):px=tp;break
    if j==last:px=c;break
   ex=px*(1-s*SLIP);fee=F*(e+ex);pnl=s*(ex-e)-fee-fund
   out[name].append((int(ts[i]),-score,sym,int(ts[j]),e,dist+F*(e+st)+SLIP*st,pnl,fee,fund))
 return out
def json_number(x):
 if isinstance(x,np.generic):return x.item()
 raise TypeError(type(x).__name__)
def simulate(events):
 # Realized drawdown only, conservative no reuse of margin or proceeds within the same minute.
 cash=peak=1000.;dd=fees=funding=0.;active=[];syms=set();used=0.;n=wins=0;days=set();coins=set();duration=0;seq=0;months={}
 def settle():
  nonlocal cash,peak,dd,used,n,wins,fees,funding,duration
  end,_,sym,margin,net,fee,fu,entry=heapq.heappop(active)
  syms.remove(sym);used-=margin;cash+=net;n+=1;wins+=int(net>0);fees+=fee;funding+=fu;duration+=end-entry
  peak=max(peak,cash);dd=max(dd,1-cash/peak)
  months[pd.Timestamp(end*60,unit='s',tz='UTC').strftime('%Y-%m')]=cash
 for t,score,sym,end,e,risk,net,fee,fu in sorted(events):
  while active and active[0][0]<t:settle()
  if sym in syms or len(active)>=4 or cash<=20:continue
  q=min(cash*RISK/risk,max(0,cash-used)/(e*(.1+F)))
  if q*e<10:continue
  margin=q*e*(.1+F);used+=margin;syms.add(sym);coins.add(sym);days.add(t//1440);seq+=1
  heapq.heappush(active,(end,seq,sym,margin,net*q,fee*q,fu*q,t))
 while active:settle()
 prev=1000.;rets={}
 for month,value in sorted(months.items()):rets[month]=round(100*(value/prev-1),4);prev=value
 return dict(balance=round(cash,2),roi=round(100*(cash/1000-1),4),realized_dd=round(dd*100,4),trades=n,wins=wins,days=len(days),coins=len(coins),fees=round(fees,2),funding=round(funding,2),mean_minutes=round(duration/n,2) if n else 0,months=rets)
def stage(label,syms,meta,start,end):
 ev={k:[] for k in NAMES};included=[];excluded=[];rows=0
 for sym in syms:
  STATUS.update(stage=label,symbol=sym,completed=len(included),excluded=len(excluded),total=len(syms))
  if sym not in meta:excluded.append(sym);continue
  m=download(sym,start-pd.Timedelta(days=1),end,meta[sym])
  if m is None:excluded.append(sym);continue
  rows+=len(m);included.append(sym)
  for k,v in candidates(sym,m,start).items():ev[k].extend(v)
  print('RESEARCH_DATA',label,sym,len(m),'completed',len(included),'of',len(syms),flush=True)
  if len(included) in (2,5,10,20,50,100) or sym==syms[-1]:
   r=dict(period=[str(start),str(end)],included=list(included),excluded=list(excluded),rows=rows,results={k:simulate(v) for k,v in ev.items()},complete=False)
   RESULTS[label]=r;print('RESEARCH_RESULT',label,json.dumps(r,separators=(',',':'),default=json_number),flush=True)
 r=dict(period=[str(start),str(end)],included=included,excluded=excluded,rows=rows,results={k:simulate(v) for k,v in ev.items()},complete=True)
 RESULTS[label]=r;print('RESEARCH_RESULT',label,json.dumps(r,separators=(',',':'),default=json_number),flush=True)
def read_window(sym,interval,start,end):
 a=int(start.timestamp()*1000);b=int(end.timestamp()*1000);step=int(interval)*60000
 rows=[]
 for p in range(a,b,step*1000):
  q=min(b,p+step*1000)
  d=get('kline',symbol=sym,interval=str(interval),start=p,end=q-1,limit=1000)
  rows.extend(x for x in d['list'] if p<=int(x[0])<q)
 if not rows:return None
 d=pd.DataFrame(rows,columns=['time','open','high','low','close','volume','turnover']).astype(float)
 d['time']=pd.to_datetime(d.time.astype('int64'),unit='ms',utc=True)
 d=d.set_index('time').sort_index();return d[~d.index.duplicated()]
def micro_events(sym,m,allowed,start,end):
 # Signals on CLOSED M1 bars; earliest entry at next open.
 o,h,l,c,v=(m[x] for x in ['open','high','low','close','volume'])
 impulse=c.shift(2)/o.shift(6)-1
 base=o.shift(6);top=h.shift(2).rolling(5).max()
 low=l.shift(1);vol=v.shift(2).rolling(5).mean()
 signal=(impulse>=.007)&((c>o).shift(2).rolling(5).sum()>=3)&(c.shift(1)<o.shift(1))&(low>=base+.5*(top-base))&(v.shift(1)<vol)&(c>h.shift(1))&(c>o)&(v>v.shift(1))
 rows=m[['open','high','low','close']].to_numpy();ts=m.index;out=[]
 for i in np.flatnonzero(signal.fillna(False).to_numpy())+1:
  if i+15>=len(m):continue
  t=ts[i];score=allowed.get(t.floor('h'))
  if score is None or t<start or t>=end:continue
  if (ts[i+15]-ts[i-7])!=pd.Timedelta(minutes=22):continue
  entry=rows[i,0]*(1+SLIP);st=rows[i-2,2]*(1-.0002)
  dist=entry-st
  if st>=rows[i,0] or dist/entry<.0015 or dist/entry>.03:continue
  tp=entry+2*dist;fu=0.;peak=entry
  for j in range(i,i+16):
   a,b,d,z=rows[j]
   if j>i and ts[j]>=end:px=a;break
   if j>i and a<=st:px=a;break
   if j>i and a>=tp:px=tp;break
   if j-i==15:px=a;break
   if j>i and int(ts[j].timestamp()/60)%480==0:fu+=a*.0001
   if d<=st:px=st;break
   if b>=tp:px=tp;break
   peak=max(peak,b)
   if j-i>=2 and peak<entry+.5*dist:
    # Stalled impulse, close on following bar open, not same close.
    j+=1;px=rows[j,0];break
  ex=px*(1-SLIP);fee=F*(entry+ex)
  out.append((int(t.timestamp()/60),-float(score),sym,int(ts[j].timestamp()/60),entry,dist+F*(entry+st)+SLIP*st,ex-entry-fee-fu,fee,fu))
 return out
DIAG_KEY='research:impulse_pro:20260915:v2:diagnostics'
def diagnostics(events,scanned,total,complete=False):
 try:
  import impulse_diagnostics
  data=impulse_diagnostics.analyze(events)
  check=simulate(events)
  if abs(data['baseline']['balance']-check['balance'])>.02 or data['baseline']['n']!=check['trades']:
   raise RuntimeError('Diagnostic replay does not match baseline')
  data.update(scanned=scanned,universe=total,complete=complete,updated=time.time())
  store.put(DIAG_KEY,json.loads(json.dumps(data,default=json_number)))
  groups=data['groups']
  summary=dict(scanned=scanned,universe=total,complete=complete,baseline=data['baseline'],by_day=groups['by_day'],by_exit_proxy=groups['by_exit_proxy'],by_stop=groups['by_stop'],by_rvol=groups['by_rvol'],worst_coins=sorted(groups['by_coin'].items(),key=lambda p:p[1]['net'])[:8],best_coins=sorted(groups['by_coin'].items(),key=lambda p:p[1]['net'],reverse=True)[:5],variants=data['variants'])
  print('IMPULSE_DIAGNOSTICS',json.dumps(summary,ensure_ascii=False,separators=(',',':'),default=json_number),flush=True)
 except Exception:
  traceback.print_exc()
def targeted(start,end,meta):
 syms=sorted(s for s in meta if s not in ('BTCUSDT','ETHUSDT') and meta[s]<int((start-pd.Timedelta(days=31)).timestamp()*1000))
 events=[];scanned=[];selected={};excluded=[];hrows=mrows=0
 saved=store.get(CHECKPOINT_KEY)
 if saved and saved.get('period')==[str(start),str(end)]:
  syms=saved['universe'];events=[tuple(x) for x in saved['events']];scanned=saved['scanned'];selected=saved['selected'];excluded=saved['excluded'];hrows=saved['hrows'];mrows=saved['mrows']
  print('IMPULSE_RESUMED',len(scanned),'of',len(syms),flush=True)
  diagnostics(events,len(scanned),len(syms),len(scanned)==len(syms))
 def save():
  data=dict(period=[str(start),str(end)],universe=syms,events=events,scanned=scanned,selected=selected,excluded=excluded,hrows=hrows,mrows=mrows)
  db_put(CHECKPOINT_KEY,data)
 def report(complete=False):
  result=dict(period=[str(start),str(end)],universe=len(syms),scanned=len(scanned),excluded=excluded,selected=selected,hourly_rows=hrows,minute_rows=mrows,signals=len(events),results=simulate(events),complete=complete)
  RESULTS['Cameron_5x_10pct']=result
  STATUS.update(completed=len(scanned),total=len(syms));publish()
  print('CAMERON_RESULT',json.dumps(result,default=json_number,separators=(',',':')),flush=True)
  if complete or len(scanned)%25==0:diagnostics(events,len(scanned),len(syms),complete)
 for sym in syms:
  if sym in scanned:continue
  STATUS.update(stage='Cameron historical scan',symbol=sym,completed=len(scanned),total=len(syms))
  histstart=start-pd.Timedelta(days=32)
  h=read_window(sym,60,histstart,end)
  if h is None or not h.index.equals(pd.date_range(histstart,end-pd.Timedelta(hours=1),freq='h')):
   excluded.append(sym);scanned.append(sym);save()
   report()
   continue
  hrows+=len(h)
  # Rolling 24h volume vs average daily volume over preceding 30 FULL days.
  volume24=h.volume.rolling(24).sum()
  baseline=h.volume.shift(24).rolling(720).sum()/30
  ratio=volume24/baseline
  gain=h.close/h.close.shift(24)-1
  turnover=h.turnover.rolling(24).sum()
  mask=(gain>=.10)&(ratio>=5)&(turnover>=5e6)&(baseline>0)
  hours=h.index[mask.fillna(False)]+pd.Timedelta(hours=1)
  hours=hours[(hours>=start)&(hours<end)]
  allowed={t:float(ratio.loc[t-pd.Timedelta(hours=1)]) for t in hours}
  if len(hours):
   selected[sym]=len(hours)
   # Only request minutes around qualifying hours; merge overlapping ranges.
   windows=[]
   for t in hours:
    a=t-pd.Timedelta(minutes=15);b=t+pd.Timedelta(minutes=75)
    if windows and a<=windows[-1][1]:windows[-1]=(windows[-1][0],max(b,windows[-1][1]))
    else:windows.append((a,b))
   for a,b in windows:
    m=read_window(sym,1,a,b)
    if m is None or not m.index.equals(pd.date_range(a,b-pd.Timedelta(minutes=1),freq='min')):
     excluded.append(sym+':M1:'+str(a));continue
    mrows+=len(m);events.extend(micro_events(sym,m,allowed,start,end))
   print('CAMERON_CANDIDATE',sym,len(hours),len(events),flush=True)
  scanned.append(sym);save();report()
 report(True)
def run():
 try:
  if not store.URL:raise RuntimeError('PostgreSQL required; research not started on ephemeral storage')
  saved_report=store.get(REPORT_KEY)
  if saved_report and saved_report.get('results',{}).get('Cameron_5x_10pct',{}).get('complete'):
   saved=store.get(CHECKPOINT_KEY)
   if saved:diagnostics(saved['events'],len(saved['scanned']),len(saved['universe']),True)
   print('IMPULSE_ALREADY_COMPLETE',flush=True);return
  if saved_report:RESULTS.update(saved_report.get('results',{}))
  STATUS.update(state='starting');publish()
  meta=universe();STATUS.update(state='running',listed=len(meta));print('RESEARCH_UNIVERSE',len(meta),flush=True)
  targeted(pd.Timestamp('2026-09-15',tz='UTC'),pd.Timestamp('2026-09-22',tz='UTC'),meta)
  STATUS.update(state='complete');publish()
 except Exception as e:
  STATUS.update(state='failed',error=str(e));traceback.print_exc()
  if store.URL:publish()
