"""Live/paper translation of the frozen SHORT_1042.py rules.
Calendar trend windows remain hourly; signal and turnover windows follow signal TF.
Public data only. No exchange order methods here.
"""
import math,time,threading
from collections import deque
import paper_feed
NAME="SHORT 1042"
SLOTS=3
TOP=3
MIN_TURN=5000000.
MIN_STOP=.008
MAX_STOP=.08
MAX_FALL=.12
LOCK=threading.RLock()
HIST={}
MACRO={}
def history(sym,i,n,end):
    step=i*60000; key=(sym,i)
    with LOCK:
        old=HIST.get(key,[])
        if old and old[-1][0]==end-step and len(old)>=n:return old[-n:]
        rows={r[0]:r for r in old if r[0]<end}
        if old and old[-1][0]<end-step and end-old[-1][0]<=100*step:
            count=(end-old[-1][0])//step-1
            raw=paper_feed.request("kline",symbol=sym,interval=str(i),limit=max(1,count),end=end-1)["list"]
            for r in raw:
                if int(r[0])<end:rows[int(r[0])]=(int(r[0]),*map(float,r[1:7]))
        a=sorted(rows.values())[-n:]
        def valid(a):
            return len(a)==n and a[-1][0]==end-step and all(y[0]-x[0]==step for x,y in zip(a,a[1:])) and all(math.isfinite(x) and x>0 for r in a for x in r[1:5]) and all(math.isfinite(r[6]) and r[6]>=0 for r in a)
        if not valid(a):
            rows={};until=end
            while len(rows)<n:
                raw=paper_feed.request("kline",symbol=sym,interval=str(i),limit=min(1000,n-len(rows)),end=until-1)["list"]
                if not raw:break
                for r in raw:
                    if int(r[0])<until:rows[int(r[0])]=(int(r[0]),*map(float,r[1:7]))
                prev=min(int(r[0]) for r in raw)
                if prev>=until:break
                until=prev
            a=sorted(rows.values())[-n:]
        if not valid(a):return None
        HIST[key]=a
        while len(HIST)>100:del HIST[next(iter(HIST))]
        return a
def ema_series(xs,span):
    a=2/(span+1);v=xs[0];out=[v]
    for p in xs[1:]:
        v+=a*(p-v);out.append(v)
    return out
def regime_from_rows(rows):
    c=[r[4] for r in rows]
    f=ema_series(c,360);s=ema_series(c,720)
    b=[p<a<z for p,a,z in zip(c,f,s)]
    d24=sum(b[-24:])/24;d168=sum(b[-168:])/168
    return {"stable":bool(b[-1] and d24>=.8 and d168>=.5),"bear":bool(b[-1]),"up6":c[-1]>c[-7],"btc":c[-1],"ema15":f[-1],"ema30":s[-1],"bear24":d24,"bear168":d168}
def macro(now):
    end=int(now//3600)*3600000
    with LOCK:
        if end not in MACRO:
            rows=history("BTCUSDT",60,2000,end)
            if not rows:raise RuntimeError("SHORT1042 BTC history incomplete")
            MACRO.clear();MACRO[end]=regime_from_rows(rows)
        return MACRO[end]
def coin_trend(sym,now):
    end=int(now//3600)*3600000;rows=history(sym,60,2000,end)
    if not rows:return None
    c=[r[4] for r in rows]
    return c[-1]<ema_series(c,120)[-1]<ema_series(c,480)[-1]
def rank(ticks,meta):
    eligible=[]
    for t in ticks:
        try:
            m=meta.get(t["symbol"])
            if not m or m.get("contractType")!="LinearPerpetual":continue
            if float(t["turnover24h"])<MIN_TURN or float(t["price24hPcnt"])>=0:continue
            if not all(float(t[k])>0 for k in ("lastPrice","bid1Price","ask1Price")):continue
            eligible.append(t)
        except (KeyError,ValueError,TypeError):continue
    eligible.sort(key=lambda x:float(x["price24hPcnt"]))
    return eligible[:TOP],len(eligible)
def pattern(rows):
    if not rows or len(rows)<25:return None
    h=[-r[3] for r in rows];l=[-r[2] for r in rows];c=[r[4] for r in rows];t=len(rows)-1
    if c[t]>=c[t-24]:return None
    lows=[min(l[t-12:t-8]),min(l[t-8:t-4]),min(l[t-4:t])]
    lev=max(h[t-6:t]);touch=[i for i in range(t-12,t) if h[i]>=lev-.0025*c[t]]
    low2=[min(l[t-6:t-4]),min(l[t-4:t-2]),min(l[t-2:t])]
    if lows[-1]>lows[0] and low2[0]<low2[1]<low2[2] and -c[t]>lev and len(touch)>=2 and touch[-1]-touch[0]>=2:return max(r[2] for r in rows[t-3:t+1])
    return None
def signal(sym,i,end):
    w=1440//i;rows=history(sym,i,max(30,w+1),end)
    if not rows:return None,"warming_history"
    st=pattern(rows)
    if st is None:return None,"no_pattern"
    ret=rows[-1][4]/rows[-w-1][4]-1
    if not -MAX_FALL<=ret<0:return None,"maxfall"
    if sum(r[6] for r in rows[-w:])<MIN_TURN:return None,"turnover"
    avg=sum(r[6] for r in rows[-w-1:-1])/w
    if avg<=0 or rows[-1][6]<avg:return None,"volume"
    trend=coin_trend(sym,end/1000)
    if trend is None:return None,"warming_history"
    if not trend:return None,"coin_trend"
    return st,"breakout"
def risk(eq,monthbase,up6):
    r=.025 if eq<monthbase else .05
    if up6:r*=.5
    if eq<monthbase*.97:r*=.5
    return r
def stop_ok(entry,stop):
    return entry>0 and MIN_STOP<=(stop-entry)/entry<MAX_STOP
def selftest():
    r=[(i*3600000,0,0,0,float(3000-i),0,0) for i in range(2000)]
    assert regime_from_rows(r)["stable"] and not regime_from_rows(r)["up6"]
    assert not regime_from_rows(list(reversed(r)))["stable"]
    assert risk(1000,1000,False)==.05 and risk(990,1000,True)==.0125 and risk(950,1000,True)==.00625
    assert stop_ok(100,101) and not stop_ok(100,100.5) and not stop_ok(100,108)
    assert pattern([]) is None
