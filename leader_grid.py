"""Bounded leader-inspired multi-entry DEMO trials.
The historical fit chooses grid parameters on training only. Validation and
holdout are reported, not rewritten. An experimental strategy may enter DEMO
with positive training evidence even when the holdout is not profitable.
No mainnet, no leverage changes. Single exchange position per symbol.
"""
import time,logging,math
import numpy as np
import market,store,league,leader_replay
VIEW={}
def worker():
    global VIEW
    reports=store.get("leader_grid_results_v1",{}) or {}
    last={};cursor=0
    while True:
        try:
            progress=store.get("leader_replay_progress_v1",{}) or {}
            # One heavy training pass per cycle.
            for sym in leader_replay.SYMS:
                if sym in reports or not progress.get(sym,{}).get("done"):continue
                a=leader_replay.data(sym,progress[sym])
                report=leader_replay.train(a,grid_only=True) if len(a)>=1000 else {"rows":len(a),"approved":False}
                reports[sym]=report;store.put("leader_grid_results_v1",reports)
                logging.info("GRID RESEARCH %s %s",sym,report)
                break
            ready=[s for s,r in reports.items() if r.get("adds",0)>0 and r.get("train",{}).get("mean",0)>0 and r.get("train",{}).get("n",0)>=20]
            # Rotate at most two extra instruments at a time; open positions
            # have separate priority in the public feed.
            selected=[ready[(cursor+i)%len(ready)] for i in range(min(2,len(ready)))] if ready else []
            market.set_grid_symbols(selected)
            if selected:
                sym=selected[0];r=reports[sym]
                end=int(time.time()*1000//leader_replay.BAR)*leader_replay.BAR-1
                if last.get(sym)!=end:
                    raw=market.request("/v5/market/kline",category="linear",symbol=sym,interval="15",end=end,limit=100)["list"]
                    a=np.asarray(sorted([[int(x[0])]+[float(z) for z in x[1:6]] for x in raw if int(x[0])+leader_replay.BAR<=end+1]),float)
                    if len(a)>=65 and 0<=time.time()*1000-a[-1,0]-leader_replay.BAR<120000 and market.scalp_quote("linear",sym):
                        last[sym]=end
                        ret4,ret16,_,valid=leader_replay.features(a)
                        signal=valid[-1] and ret4[-1]<=-r["dip"] and ret16[-1]>-.10 and (not r["recovery"] or a[-1,4]>a[-1,1])
                        if signal:
                            key="leader-grid:"+sym+":"+str(r["adds"])+":"+str(r["grid_step"])+":"+str(r["tp"])+":"+str(r["stop"])+":"+str(r["hold_minutes"])+":"+str(r["dip"])+":"+str(r["recovery"])
                            model={"demo_grid":True,"adds":r["adds"],"step":r["grid_step"],"tp":r["tp"],"historical_approved":r["approved"]}
                            now=time.time();league.publish(key,"linear",sym,1,model,now,now+30,r["hold_minutes"]*60,r["stop"])
                            logging.info("GRID SIGNAL %s model=%s",sym,model)
                cursor+=1
            VIEW={"time":time.time(),"reports":reports,"ready":ready,"stream_priority":selected,"mode":"demo multi-entry trials; historical results reported separately"}
        except Exception as exc:
            if "cooldown" in str(exc).lower():time.sleep(120)
            else:logging.exception("GRID RESEARCH error");time.sleep(30)
        time.sleep(10)
