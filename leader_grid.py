"""Leader-based evolutionary demo trial scheduler."""
import time,logging
import numpy as np
import market,store,league,leader_replay,leader_evolution
VIEW={}
def worker():
    global VIEW
    reports=store.get("leader_evolution_v1",{}) or {}
    examples=leader_evolution.read_examples()
    last={};trained={};buffers={};last_attempt={};diagnostics={};cursor=0
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
            ready=[s for s,r in reports.items() if r.get("archive") and r.get("objective")=="net calendar daily return"]
            selected=ready[:]
            market.set_grid_symbols(selected)
            for sym in selected:
                r=reports[sym];wall=time.time();bar=leader_replay.BAR
                end=int((wall*1000-2000)//bar)*bar-1
                if last.get(sym)==end:continue
                cache=buffers.setdefault(sym,{})
                for row in market.ws_bars("linear",sym):
                    if row[0]+bar<=end+1:cache[int(row[0])]=row
                want=end+1-bar
                def contiguous():
                    return all(want-i*bar in cache for i in range(110))
                if not contiguous() and wall-last_attempt.get(sym,0)>=60:
                    last_attempt[sym]=wall
                    try:
                        raw=market.request("/v5/market/kline",category="linear",symbol=sym,interval="15",end=end,limit=160)["list"]
                        for row in raw:
                            if int(row[0])+bar<=end+1:
                                cache[int(row[0])]=[int(row[0])]+[float(z) for z in row[1:6]]
                    except Exception as exc:
                        diagnostics[sym]={"status":"history_gap","error":str(exc)[:100],"bar":want};continue
                if not contiguous():
                    diagnostics[sym]={"status":"history_gap","bar":want};continue
                for k in sorted(cache)[:-180]:del cache[k]
                a=np.asarray([cache[k] for k in sorted(cache) if k<=want],float)
                if not 0<=wall*1000-want-bar<180000:
                    diagnostics[sym]={"status":"bar_expired","bar":want};last[sym]=end;continue
                if not market.scalp_quote("linear",sym):
                    diagnostics[sym]={"status":"no_fresh_book","bar":want};continue
                p=leader_evolution.live(a,r)
                options=[e for e in r["archive"] if p is not None and p>=e["params"]["threshold"] and e["train"]["mean"]>0 and e["validation"].get("daily_mean",0)>0]
                diagnostics[sym]={"status":"signal" if options else "no_learned_entry","bar":want,"score":p,"candidates":len(options),"min_threshold":min((e["params"]["threshold"] for e in r["archive"] if e["train"]["mean"]>0 and e["validation"].get("daily_mean",0)>0),default=None)}
                # Do not mark a bar consumed before fresh inputs are available.
                last[sym]=end
                logging.info("LEADER ENTRY CHECK %s %s",sym,diagnostics[sym])
                def ranking(e):
                    f=feedback.get(e["key"],{});n=f.get("n",0)
                    return e["fitness"]+.075*f.get("net_return",0)/(n+5)+.00002/(n+1)**.5
                if options:
                    e=max(options,key=ranking);v=e["params"]
                    model={"demo_grid":True,"adds":v["adds"],"step":v["step"],"tp":v["tp"],"historical_approved":e["validation"]["mean"]>0}
                    t=time.time();league.publish(e["key"],"linear",sym,1,model,t,t+60,v["hold"]*900,v["stop"])
                    logging.info("LEADER EVOLUTION SIGNAL %s params=%s entry_score=%.4f",sym,v,p)
            VIEW={"time":time.time(),"reports":{s:{k:v for k,v in r.items() if k not in ("mu","sd","w")} for s,r in reports.items()},"ready":ready,"stream_priority":selected,"entry_diagnostics":diagnostics,"mode":"daily net return objective; empirical entry-score exploration and demo feedback"}
        except Exception as exc:
            if "cooldown" in str(exc).lower():time.sleep(120)
            else:logging.exception("LEADER EVOLUTION error");time.sleep(30)
        time.sleep(10)
