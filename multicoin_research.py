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
def get(path,**params):
 global NEXT
 for a in range(3):
  time.sleep(max(0,NEXT-time.monotonic())); NEXT=time.monotonic()+1.2
  try:
   r=SESSION.get(BASE+path,params=dict(category='linear',**params),timeout=20)
   if r.status_code in (403,429):raise RuntimeError('API blocked '+str(r.status_code))
   r.raise_for_status();d=r.json()
   if d.get('retCode') in (10006,10018):raise RuntimeError('API rate limited '+str(d['retCode']))
   if d.get('retCode')!=0:raise ValueError(str(d)[:200])
   return d['result']
  except Exception as e:
   print('RESEARCH_RETRY',path,a,str(e)[:150],flush=True)
   if 'blocked' in str(e) or 'rate limited' in str(e):raise
   if a==2:raise
   time.sleep(2**a)
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
def simulate(events):
 # Realized drawdown only, conservative no reuse of margin or proceeds within the same minute.
 cash=peak=1000.;dd=fees=funding=0.;active=[];syms=set();used=0.;n=wins=0;days=set();coins=set();duration=0;seq=0;months={}
 def settle():
  nonlocal cash,peak,dd,used,n,wins,fees,funding,duration
  end,_,sym,margin,net,fee,fu,entry=heapq.heappop(active)
  syms.remove(sym);used-=margin;cash+=net;n+=1;wins+=net>0;fees+=fee;funding+=fu;duration+=end-entry
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
   RESULTS[label]=r;print('RESEARCH_RESULT',label,json.dumps(r,separators=(',',':')),flush=True)
 r=dict(period=[str(start),str(end)],included=included,excluded=excluded,rows=rows,results={k:simulate(v) for k,v in ev.items()},complete=True)
 RESULTS[label]=r;print('RESEARCH_RESULT',label,json.dumps(r,separators=(',',':')),flush=True)
def run():
 try:
  meta=universe();STATUS.update(state='running',listed=len(meta));print('RESEARCH_UNIVERSE',len(meta),flush=True)
  stage('pilot_7d_core',CORE,meta,END-pd.Timedelta(days=7),END)
  stage('market_7d',sorted(meta),meta,END-pd.Timedelta(days=7),END)
  stage('core_103d',CORE,meta,START,END)
  # Full-market 103-day data takes substantially longer; only attempt after successful smaller stages.
  stage('market_103d',sorted(meta),meta,START,END)
  STATUS.update(state='complete')
 except Exception as e:
  STATUS.update(state='failed',error=str(e));traceback.print_exc()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/status' or self.path=='/':
   data=json.dumps(dict(status=STATUS,results=RESULTS),default=str).encode()
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  else:self.send_error(404)
if __name__=='__main__':
 threading.Thread(target=run,daemon=True).start()
 ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','10000'))),Handler).serve_forever()
