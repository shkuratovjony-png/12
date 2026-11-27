"""Read-only diagnostics for stored Impulse events. No market requests or orders."""
import heapq, math
from collections import defaultdict
from datetime import datetime,timezone
F=.0006
SLIP=.0002
RISK=.005
def replay(events,fee_rate=F,min_stop=.0015,spacing=0,first_only=False,min_score=0):
 cash=peak=1000.;dd=used=0.;active=[];syms=set();last={};trades=[];seq=0
 skipped=defaultdict(int)
 def settle():
  nonlocal cash,peak,dd,used
  end,_,sym,margin,t=heapq.heappop(active)
  syms.remove(sym);used-=margin;cash+=t['net'];peak=max(peak,cash);dd=max(dd,1-cash/peak)
  t['balance']=cash;trades.append(t)
 for t,score,sym,end,e,risk,net,fee,fu in sorted(events):
  while active and active[0][0]<t:settle()
  st=(e*(1+F)-risk)/(1-F-SLIP)
  dist=(e-st)/e
  if dist<min_stop-1e-10 or -score<min_score:skipped['filter']+=1;continue
  if t-last.get(sym,-10**15)<spacing:skipped['spacing']+=1;continue
  if first_only and last.get(sym,-10**15)//1440==t//1440:skipped['repeat']+=1;continue
  if sym in syms or len(active)>=4 or cash<=20:skipped['capacity']+=1;continue
  ex=net+e+fee+fu
  newfee=fee_rate*(e+ex)
  newrisk=e-st+fee_rate*(e+st)+SLIP*st
  q=min(cash*RISK/newrisk,max(0,cash-used)/(e*(.1+fee_rate)))
  if q*e<10:skipped['size']+=1;continue
  margin=q*e*(.1+fee_rate);used+=margin;syms.add(sym);last[sym]=t;seq+=1
  gross=q*(ex-e);slip=q*((e-e/(1+SLIP))+(ex/(1-SLIP)-ex))
  raw_exit=ex/(1-SLIP);tp=e+2*(e-st)
  kind='stop_or_worse' if raw_exit<=st*(1+1e-8) else 'target' if raw_exit>=tp*(1-1e-8) else 'time_15m' if end-t>=15 else 'other_early'
  trade=dict(symbol=sym,entry=t,exit=end,minutes=end-t,stop_pct=100*dist,rvol=-score,net=gross-q*(newfee+fu),gross=gross,fee=q*newfee,slippage=slip,funding=q*fu,exit_proxy=kind)
  heapq.heappush(active,(end,seq,sym,margin,trade))
 while active:settle()
 def stats(a):
  pos=sum(t['net'] for t in a if t['net']>0);neg=-sum(t['net'] for t in a if t['net']<0)
  return dict(n=len(a),wins=sum(t['net']>0 for t in a),net=round(pos-neg,4),gross=round(sum(t['gross'] for t in a),4),fees=round(sum(t['fee'] for t in a),4),slippage=round(sum(t['slippage'] for t in a),4),avg_win=round(pos/max(1,sum(t['net']>0 for t in a)),4),avg_loss=round(neg/max(1,sum(t['net']<0 for t in a)),4),profit_factor=round(pos/neg,4) if neg else None)
 result=stats(trades);result.update(balance=round(cash,4),roi=round((cash/1000-1)*100,4),dd=round(dd*100,4),days=len({t['entry']//1440 for t in trades}),skipped=dict(skipped))
 groups={}
 for name,key in [('by_day',lambda t:datetime.fromtimestamp(t['exit']*60,timezone.utc).strftime('%Y-%m-%d')),('by_coin',lambda t:t['symbol']),('by_exit_proxy',lambda t:t['exit_proxy']),('by_stop',lambda t:'0.15–0.3%' if t['stop_pct']<.3 else '0.3–0.5%' if t['stop_pct']<.5 else '0.5–1%' if t['stop_pct']<1 else '1–3%'),('by_rvol',lambda t:'5–8x' if t['rvol']<8 else '8–12x' if t['rvol']<12 else '12x+')]:
  d=defaultdict(list)
  for t in trades:d[key(t)].append(t)
  groups[name]={k:stats(v) for k,v in sorted(d.items())}
 return result,groups,trades
def analyze(events):
 base,groups,trades=replay(events)
 variants={}
 for name,kw in [('fee_0.02pct_fixed_fills',{'fee_rate':.0002}),('zero_fee_fixed_fills',{'fee_rate':0}),('stop_min_0.5pct',{'min_stop':.005}),('stop_min_1pct',{'min_stop':.01}),('same_coin_pause_60m',{'spacing':60}),('first_per_coin_day',{'first_only':True}),('relative_volume_8x',{'min_score':8})]:
  variants[name]=replay(events,**kw)[0]
 return dict(baseline=base,groups=groups,variants=variants,trades=trades,notes=['Exit categories are inferred from stored execution prices, not exact reason flags.','Fee scenarios assume unchanged fills, not validated maker execution.','All variants use same available sample; not out-of-sample results.'])
