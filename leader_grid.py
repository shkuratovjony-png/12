"""Leader-based evolutionary demo trial scheduler."""
import time,logging
import numpy as np
import market,store,league,leader_replay,leader_evolution
VIEW={}
def worker():
    global VIEW
    reports=store.get("leader_evolution_v1",{}) or {}
    examples=leader_evolution.read_examples()
    last={};trained={};cursor=0
    while True:
        try:
            now=time.time();progress=store.get("leader_replay_progress_v1",{}) or {}
            feedback={}
            state=store.get("bybit_demo_v1",{}) or {}
            for c in state.get("closed",[]):
                key=c.get("strategy_id") or ""
                if not key.startswith("leader-evo:") or c.get("exchange_pnl") is None:continue
                f=feedback.setdefault(key,{"n":0,"net_return":0.,"pnl":0.})
                f["n"]+=1;f["net_return"]+=float(c["exchange_pnl"])/max(1.,float(c["notional"]));f["pnl"]+=float(c["exchange_pnl"])
            for sym in leader_replay.SYMS:
                if not progress.get(sym,{}).get("done") or now-trained.get(sym,0)<900:continue
                trained[sym]=now
                a=leader_replay.data(sym,progress[sym])
                if len(a)>=1000:
                    reports[sym]=leader_evolution.advance(a,sym,examples,reports.get(sym,{}),feedback)
                    store.put("leader_evolution_v1",reports)
                    r=reports[sym]
                    logging.info("LEADER EVOLUTION symbol=%s generation=%s tested=%s prior=%s best=%s",sym,r.get("generation"),r.get("tested_total"),r.get("prior"),(r.get("archive") or [None])[0])
                break
            ready=[s for s,r in reports.items() if r.get("archive")]
            selected=[ready[(cursor+i)%len(ready)] for i in range(min(2,len(ready)))] if ready else []
            market.set_grid_symbols(selected)
            if selected:
                sym=selected[0];r=reports[sym]
                end=int(time.time()*1000//leader_replay.BAR)*leader_replay.BAR-1
                if last.get(sym)!=end:
                    raw=market.request("/v5/market/kline",category="linear",symbol=sym,interval="15",end=end,limit=160)["list"]
                    a=np.asarray(sorted([[int(x[0])]+[float(z) for z in x[1:6]] for x in raw if int(x[0])+leader_replay.BAR<=end+1]),float)
                    if len(a)>=110 and 0<=time.time()*1000-a[-1,0]-leader_replay.BAR<120000 and market.scalp_quote("linear",sym):
                        last[sym]=end;p=leader_evolution.live(a,r)
                        options=[e for e in r["archive"] if p is not None and p>=e["params"]["threshold"] and e["train"]["mean"]>0]
                        # Explore multiple learned variants; actual demo results inform priority.
                        def ranking(e):
                            f=feedback.get(e["key"],{});n=f.get("n",0)
                            return e["fitness"]+f.get("net_return",0)/(n+5)+.001/(n+1)**.5
                        if options:
                            e=max(options,key=ranking);v=e["params"]
                            model={"demo_grid":True,"adds":v["adds"],"step":v["step"],"tp":v["tp"],"historical_approved":e["validation"]["mean"]>0}
                            t=time.time();league.publish(e["key"],"linear",sym,1,model,t,t+30,v["hold"]*900,v["stop"])
                            logging.info("LEADER EVOLUTION SIGNAL %s params=%s entry_score=%.4f",sym,v,p)
                cursor+=1
            VIEW={"time":time.time(),"reports":{s:{k:v for k,v in r.items() if k not in ("mu","sd","w")} for s,r in reports.items()},"ready":ready,"stream_priority":selected,"mode":"learn entries and seed exits from leader examples; mutation and demo feedback"}
        except Exception as exc:
            if "cooldown" in str(exc).lower():time.sleep(120)
            else:logging.exception("LEADER EVOLUTION error");time.sleep(30)
        time.sleep(10)
