"""Video TDHfPgCLSck: causal FVG / CHoCH / Fibonacci historical laboratory.
No exchange orders. All unspoken settings are explicit research assumptions.
Fixed chronological train/validation/test; test does not select parameters.
"""
import time,logging,math
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import numpy as np
import market,store,source_lab

BAR=60000
DAYS=45
NY=ZoneInfo("America/New_York")
SOURCE="https://www.youtube.com/watch?v=TDHfPgCLSck&t=834s"
FALLBACK=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","AVAXUSDT")
KEY="video_smc_v1"
VIEW={"status":"starting","source":SOURCE}
# Approximate round-trip expenses: 6 bps per execution, 2 bps per exit
# adverse execution buffer and 2 bps funding reserve; not actual fee/funding history.
FEE=.0006
EXIT_BUFFER=.0002
FUNDING=.0002
RISKS=(.005,.01,.02,.05,.10)
def zones(a):
    """15m FVG known only after third full candle closes; latest ten active zones."""
    bars=[];out=np.zeros((len(a),2),bool);active=[]
    group=[];prev=None
    for i,row in enumerate(a):
        t=int(row[0]);g=t//(15*BAR)
        if prev is not None and g!=prev:group=[]
        prev=g;group.append(row)
        # Touch of a previously confirmed zone. Invalidate on close through far edge.
        for side,lo,hi in active:
            if row[3]<=hi and row[2]>=lo:out[i,0 if side==1 else 1]=True
        if t%(15*BAR)!=14*BAR:continue
        if len(group)!=15 or int(group[0][0])!=t-14*BAR:continue
        candle=(g,group[0][1],max(x[2] for x in group),min(x[3] for x in group),row[4])
        active=[z for z in active if (candle[4]>=z[1] if z[0]==1 else candle[4]<=z[2])]
        bars.append(candle);bars=bars[-3:]
        if len(bars)==3 and bars[-1][0]-bars[0][0]==2:
            x,y,z=bars
            if z[3]>x[2] and y[4]>x[2]:active.append((1,x[2],z[3]))
            if z[2]<x[3] and y[4]<x[3]:active.append((-1,z[2],x[3]))
            active=active[-10:]
    return out

def setups(a,touch,pivot,session,minutes):
    """Swing confirmation is delayed by pivot bars. No future candle used at entry.
    A long requires descending swing highs then a close above the latest confirmed high.
    Short is a mirrored research extension, not demonstrated in the source.
    """
    out=[];highs=[];lows=[];last_touch={1:-10000,-1:-10000}
    armed=None;blocked_high=None;blocked_low=None;last_session=False
    for i in range(2*pivot,len(a)):
        row=a[i];t=int(row[0]);o,h,l,c=row[1:5]
        if t-int(a[i-1,0])!=BAR:
            highs=[];lows=[];armed=None;last_touch={1:-10000,-1:-10000};blocked_high=blocked_low=None
        if touch[i,0]:last_touch[1]=i
        if touch[i,1]:last_touch[-1]=i
        j=i-pivot;win=a[j-pivot:i+1]
        if int(win[-1,0]-win[0,0])==2*pivot*BAR:
            if a[j,2]>max(np.max(win[:pivot,2]),np.max(win[pivot+1:,2])):highs=(highs+[(j,a[j,2])])[-3:]
            if a[j,3]<min(np.min(win[:pivot,3]),np.min(win[pivot+1:,3])):lows=(lows+[(j,a[j,3])])[-3:]
        in_session=bool(minutes[i])
        if not in_session:
            armed=None;last_session=False;continue
        if not last_session:armed=None
        last_session=True
        if len(highs)>=2 and highs[-1][1]<highs[-2][1] and highs[-1][0]!=blocked_high and a[i-1,4]<=highs[-1][1]<c and i-last_touch[1]<=60:
            start=max(highs[-1][0],i-60)
            anchor=float(np.min(a[start:i+1,3]))
            armed=(1,i,anchor,float(h));blocked_high=highs[-1][0]
        elif len(lows)>=2 and lows[-1][1]>lows[-2][1] and lows[-1][0]!=blocked_low and a[i-1,4]>=lows[-1][1]>c and i-last_touch[-1]<=60:
            start=max(lows[-1][0],i-60)
            anchor=float(np.max(a[start:i+1,2]))
            armed=(-1,i,anchor,float(l));blocked_low=lows[-1][0]
        if not armed:continue
        side,k,anchor,extreme=armed
        if i-k>15 or i-last_touch[side]>60 or (l<anchor if side==1 else h>anchor):
            armed=None;continue
        extreme=max(extreme,h) if side==1 else min(extreme,l)
        armed=(side,k,anchor,extreme)
        if i<2 or i-2<k-2 or t-int(a[i-2,0])!=2*BAR:continue
        if side==1 and l>a[i-2,2] and a[i-1,4]>a[i-2,2]:
            lo,hi=float(a[i-2,2]),float(l)
        elif side==-1 and h<a[i-2,3] and a[i-1,4]<a[i-2,3]:
            lo,hi=float(h),float(a[i-2,3])
        else:continue
        width=abs(extreme-anchor)
        if width<=0:continue
        f1,f2=sorted((extreme-side*.5*width,extreme-side*.618*width))
        # Whole gap inside the retracement band; entry shifted by 10% of gap width.
        if lo<f1 or hi>f2:continue
        entry=(lo+hi)/2+side*.1*(hi-lo)
        stop=float(np.min(a[i-2:i+1,3]))*(1-.0002) if side==1 else float(np.max(a[i-2:i+1,2]))*(1+.0002)
        if entry<=0 or side*(entry-stop)<=0:continue
        out.append((i,side,entry,stop));armed=None
    return out

def session_mask(a,name):
    if name=="all":return np.ones(len(a),dtype=bool)
    out=[]
    for t in a[:,0]:
        d=datetime.fromtimestamp((int(t)+BAR)/1000,timezone.utc).astimezone(NY)
        m=d.hour*60+d.minute
        out.append(d.weekday()<5 and 570<=m<690)
    return np.array(out,dtype=bool)

def simulate(a,signals,rr,start,end,long_only=False):
    trades=[];busy=start-1
    for i,side,entry,stop in signals:
        if i<start or i<=busy or i+1>=end or (long_only and side<0):continue
        risk=abs(entry-stop)
        # True stop-dollar budget includes execution fees and conservative carry reserve.
        cost_stop=FEE*(entry+stop)+EXIT_BUFFER*entry+FUNDING*entry
        denom=risk+cost_stop
        if denom<=0:continue
        target=entry+side*rr*risk
        if target<=0:continue
        fill=None
        for j in range(i+1,min(i+16,end)):
            if int(a[j,0]-a[j-1,0])!=BAR:break
            # Limit must trade through by a buffer; touch alone is not a fill.
            if (a[j,3]<entry*(1-.0001) if side==1 else a[j,2]>entry*(1+.0001)):
                fill=j;break
            # If the move reaches the target before entry, cancel the stale order.
            if (a[j,2]>=target if side==1 else a[j,3]<=target):break
        if fill is None:continue
        if fill+120>=end:continue
        exit_price=None;reason="time";close=fill
        for j in range(fill,fill+121):
            close=j;o,h,l,c=map(float,a[j,1:5])
            if j>fill and int(a[j,0]-a[j-1,0])!=BAR:
                exit_price=o;reason="data_gap";break
            if (l<=stop if side==1 else h>=stop):
                exit_price=min(o,stop) if side==1 else max(o,stop);reason="stop";break
            # No same-bar profit after a limit fill: OHLC cannot establish order.
            if j>fill and (h>=target if side==1 else l<=target):
                exit_price=target;reason="target";break
            if j==fill+120:exit_price=c
        if exit_price is None:continue
        net=side*(exit_price-entry)-FEE*(entry+exit_price)-(EXIT_BUFFER+FUNDING)*entry
        r=net/denom
        trades.append({"time":int(a[close,0]+BAR)//1000,"r":float(r),"stop_fraction":float(denom/entry),"side":side,"reason":reason})
        busy=close
    return trades

def metrics(trades):
    r=np.array([x["r"] for x in trades],float);n=len(r)
    if not n:return {"trades":0,"mean_r":0.,"net_r":0.,"win_rate":None,"score":-100.,"risk":{}}
    out={"trades":n,"mean_r":float(r.mean()),"net_r":float(r.sum()),"win_rate":float(np.mean(r>0)),"score":float(r.mean()-r.std()/math.sqrt(n)),"longs":sum(x["side"]==1 for x in trades),"shorts":sum(x["side"]==-1 for x in trades),"max_loss_r":float(min(r))}
    for f in RISKS:
        # Cap gross notional at 1x equity; no 100x leverage assumptions.
        fractions=np.minimum(f,np.array([x["stop_fraction"] for x in trades]))
        curve=np.cumprod(np.r_[1.,np.maximum(0.,1+fractions*r)])
        out["risk"][str(f)]={"return":float(curve[-1]-1),"dd":float(np.max(1-curve/np.maximum.accumulate(curve)))}
    return out

def train(rows):
    a=np.asarray(rows,float);n=len(a)
    if n<10000:raise ValueError("insufficient bars")
    touch=zones(a);c1=int(n*.6);c2=int(n*.8)
    families={};count=0
    for name in ("ny","all"):
        mask=session_mask(a,name)
        for pivot in (2,3,5):
            signals=setups(a,touch,pivot,name,mask)
            for rr in (3,4):
                for long_only in (True,False):
                    params={"session":name,"pivot":pivot,"rr":rr,"long_only":long_only}
                    tr=metrics(simulate(a,signals,rr,0,c1,long_only))
                    count+=1
                    key=name+(":long" if long_only else ":both")
                    if tr["trades"]>=10 and (key not in families or tr["score"]>families[key][0]["score"]):
                        families[key]=(tr,params,signals)
    results=[]
    for tr,p,signals in families.values():
        val=metrics(simulate(a,signals,p["rr"],c1,c2,p["long_only"]))
        test=metrics(simulate(a,signals,p["rr"],c2,n,p["long_only"]))
        ok=all(m["trades"]>=10 and m["score"]>0 and m["risk"]["0.01"]["dd"]<=.08 for m in (tr,val,test))
        results.append({"params":p,"train":tr,"validation":val,"test":test,"approved":ok})
    return {"time":time.time(),"bars":n,"first":int(a[0,0]),"last":int(a[-1,0]),"coverage":float(n/(1+(a[-1,0]-a[0,0])/BAR)),"tested":count,"results":results}

def selftest():
    a=np.array([[0,100,101,99,100,1],[BAR,100,101,98,99,1],[2*BAR,100,104,99,103,1]]+[[i*BAR,103,104,102,103,1] for i in range(3,130)],float)
    x=simulate(a,[(0,1,100.,98.5)],2,0,len(a))
    assert len(x)==1 and x[0]["r"]<0 and x[0]["reason"]=="stop"
    assert metrics(x)["trades"]==1

def worker():
    global VIEW
    state=store.get(KEY,{}) or {}
    if not state:
        universe=list(dict.fromkeys(list(market.SYMBOLS)+list(FALLBACK)))[:10]
        end=int(time.time()*1000//BAR)*BAR-1
        state={"symbols":universe,"end":end,"start":end-DAYS*86400000+1,"progress":{},"reports":{}}
        store.put(KEY,state)
    while True:
        try:
            pending=[s for s in state["symbols"] if s not in state["reports"]]
            VIEW={"status":"collecting" if pending else "complete","source":SOURCE,"days":DAYS,"symbols":state["symbols"],"progress":state["progress"].copy(),"reports":state["reports"].copy(),"approved":sum(m["approved"] for r in state["reports"].values() for m in r.get("results",[])),"time":time.time(),"mode":"historical only; no direct exchange orders"}
            if not pending:time.sleep(120);continue
            sym=pending[0];p=state["progress"].setdefault(sym,{"next":state["end"],"pages":0,"rows":0})
            if p["next"]>=state["start"] and p["pages"]<70:
                rr=source_lab.bars("linear",sym,p["next"],1000)
                if rr:
                    store.put(KEY+":"+sym+":"+str(p["pages"]),rr)
                    p["pages"]+=1;p["rows"]+=len(rr);p["next"]=rr[0][0]-1
                else:p["next"]=state["start"]-1
                store.put(KEY,state)
                if p["pages"]%10==0:logging.info("VIDEO SMC history %s pages=%s rows=%s",sym,p["pages"],p["rows"])
                time.sleep(3);continue
            VIEW=dict(VIEW,status="testing",symbol=sym)
            data=store.get_many([KEY+":"+sym+":"+str(i) for i in range(p["pages"])])
            unique={int(row[0]):row for page in data.values() for row in page if row[0]>=state["start"]}
            rows=[unique[t] for t in sorted(unique)]
            if len(rows)>=10000:
                report=train(rows)
            else:report={"bars":len(rows),"tested":0,"results":[],"reason":"insufficient history"}
            state["reports"][sym]=report;store.put(KEY,state)
            logging.info("VIDEO SMC result %s %s",sym,report)
        except Exception as exc:
            VIEW=dict(VIEW,status="error",error=str(exc)[:160],time=time.time())
            logging.exception("VIDEO SMC error")
            time.sleep(120)
        time.sleep(3)
