"""One-off BTC year replay of the video model. No orders, no tuning on test results."""
import time,logging
from datetime import date,datetime,timedelta
import numpy as np
import store,source_lab,video_smc as smc
KEY="video_smc_btc_year_v1"
START=date(2025,11,25)
END=date(2026,11,25)
VIEW={"status":"starting","from":str(START),"to_exclusive":str(END)}
CONFIGS=((3,True),(4,True),(3,False),(4,False))
def calendar():
    return [str(START+timedelta(days=i)) for i in range((END-START).days) if (START+timedelta(days=i)).weekday()<5]
def summarize(trades,fraction,cap):
    bal=peak=1000.;dd=0.;wins=0;net_r=0.;streak=longest=0;limited=0
    monthly={}
    for x in trades:
        actual=min(fraction,cap*x["stop_fraction"])
        limited+=actual<fraction-1e-12
        bal=max(0.,bal*(1+actual*x["r"]))
        peak=max(peak,bal);dd=max(dd,1-bal/peak);net_r+=x["r"]
        wins+=x["r"]>0
        streak=streak+1 if x["r"]<0 else 0;longest=max(streak,longest)
        monthly[x["day"][:7]]=round(bal,2)
    return {"risk":fraction,"max_notional_multiple":cap,"trades":len(trades),"win_rate":wins/len(trades) if trades else None,"net_r":net_r,"equity":bal,"pnl":bal-1000,"drawdown":dd,"max_loss_streak":longest,"size_limited":limited,"monthly":monthly}
def report(state,days):
    done=state["days"]
    out=[]
    for rr,long_only in CONFIGS:
        k=str(rr)+(":long" if long_only else ":both")
        trades=[dict(t,day=d) for d in sorted(done) for t in done[d].get("trades",{}).get(k,[])]
        for f in (.01,.02,.05):
            for cap in (1.,10.):
                out.append(dict(summarize(trades,f,cap),rr=rr,long_only=long_only))
    good=sum(bool(v.get("complete")) for v in done.values())
    return {"status":"complete" if good==len(days) else "incomplete" if len(done)==len(days) else "collecting","from":str(START),"to_exclusive":str(END),"symbol":"BTCUSDT","sessions":len(days),"processed":len(done),"complete_sessions":good,"missing_sessions":[d for d,v in done.items() if not v.get("complete")],"results":out,"time":time.time(),"assumptions":"NY weekdays 09:30-11:30; 1000 one-minute bars per session ending 13:45 NY; pivot=3; limit through buffer, stop first; fixed 3R/4R; costs modeled; no liquidation history; closed-equity drawdown only; 5% fixed fraction at $1000; short is extension"}
def worker():
    global VIEW
    days=calendar();state=store.get(KEY,{"days":{}}) or {"days":{}}
    while True:
        try:
            VIEW=report(state,days)
            remaining=[d for d in days if d not in state["days"]]
            if not remaining:
                logging.info("VIDEO BTC YEAR FINAL %s",VIEW);return
            d=remaining[0];day=date.fromisoformat(d)
            # 1000 closed minute bars: overnight context plus full entry and exit window.
            end=int(datetime(day.year,day.month,day.day,13,45,tzinfo=smc.NY).timestamp()*1000)-1
            rows=source_lab.bars("linear","BTCUSDT",end,1000)
            a=np.asarray(rows,float)
            if len(a)!=1000 or int(a[-1,0])!=end+1-smc.BAR or not np.all(np.diff(a[:,0])==smc.BAR):
                # Never replace missing sessions with invented zero-return trades.
                state["days"][d]={"complete":False,"rows":len(rows),"trades":{}}
            else:
                signals=smc.setups(a,smc.zones(a),3,"ny",smc.session_mask(a,"ny"))
                result={}
                for rr,lo in CONFIGS:
                    result[str(rr)+(":long" if lo else ":both")]=smc.simulate(a,signals,rr,0,len(a),lo)
                state["days"][d]={"complete":True,"rows":len(rows),"trades":result}
            store.put(KEY,state)
            VIEW=report(state,days)
            if len(state["days"])%10==0:
                logging.info("VIDEO BTC YEAR progress %s/%s valid=%s",VIEW["processed"],VIEW["sessions"],VIEW["complete_sessions"])
        except Exception as exc:
            VIEW=dict(VIEW,status="error",error=str(exc)[:160],time=time.time())
            logging.warning("VIDEO BTC YEAR error %s",str(exc)[:160])
            time.sleep(120)
        time.sleep(7)
