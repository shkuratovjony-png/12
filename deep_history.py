"""Bounded persistent history backfill and chronological research, separate from live bars."""
import time,logging,requests,math
import store,replay_lab
BAR=900000
DAYS=90
SYMS=("BTCUSDT","ETHUSDT","SOLUSDT")
VIEW={}
MODELS={}
def worker():
    global VIEW,MODELS
    state=store.get("deep_history_v1",{}) or {}
    MODELS=store.get("deep_replay_v1",{}) or {}
    session=requests.Session()
    while True:
        try:
            for kind in ("linear","spot"):
                for sym in SYMS:
                    key=kind+":"+sym
                    m=state.setdefault(key,{"end":int(time.time()*1000//BAR)*BAR-1,"pages":0,"bars":0,"done":False})
                    if m["done"]:continue
                    if "anchor" not in m:m["anchor"]=m["end"];store.put("deep_history_v1",state)
                    cutoff=m["anchor"]-DAYS*86400000
                    if m["end"]<cutoff:
                        m["done"]=True;store.put("deep_history_v1",state);continue
                    response=session.get("https://api.bybit.com/v5/market/kline",params={"category":kind,"symbol":sym,"interval":"15","end":m["end"],"limit":1000},timeout=15)
                    response.raise_for_status();data=response.json()
                    if data.get("retCode")!=0:raise RuntimeError("history API "+str(data.get("retCode")))
                    raw=data["result"]["list"]
                    rows=[]
                    for x in raw:
                        t=int(x[0]);v=[t]+[float(z) for z in x[1:6]]
                        if cutoff<=t<=m["end"] and all(math.isfinite(z) for z in v) and min(v[1:5])>0:rows.append(v)
                    rows.sort(key=lambda x:x[0])
                    if rows:
                        store.put("deep_candles:"+key+":"+str(m["pages"]),rows)
                        m["pages"]+=1;m["bars"]+=len(rows)
                    if not raw or min(int(x[0]) for x in raw)<=cutoff:m["done"]=True
                    else:
                        nxt=min(int(x[0]) for x in raw)-1
                        if nxt>=m["end"]:raise RuntimeError("history cursor did not advance")
                        m["end"]=nxt
                    store.put("deep_history_v1",state)
                    logging.info("DEEP HISTORY %s bars=%s pages=%s done=%s",key,m["bars"],m["pages"],m["done"])
                    time.sleep(3)
                entries=[state.get(kind+":"+sym,{}) for sym in SYMS]
                if all(x.get("done") for x in entries) and kind not in MODELS:
                    data={}
                    for sym,m in zip(SYMS,entries):
                        keys=["deep_candles:"+kind+":"+sym+":"+str(i) for i in range(m["pages"])]
                        chunks=store.get_many(keys)
                        unique={int(row[0]):row for rows in chunks.values() for row in rows}
                        data[sym]=[unique[t] for t in sorted(unique)]
                    model=replay_lab.train(kind,data)
                    if model:
                        MODELS={**MODELS,kind:model};store.put("deep_replay_v1",MODELS)
                        logging.info("DEEP REPLAY kind=%s rows=%s approved=%s val=%s test=%s",kind,model["rows"],model["approved"],model["validation"]["1"]["mean_net"],model["test"]["1"]["mean_net"])
            VIEW={"history":{k:dict(v) for k,v in state.items()},"models":{k:{a:b for a,b in m.items() if a not in ("w","scale")} for k,m in MODELS.items()},"time":time.time()}
        except Exception:
            logging.exception("DEEP HISTORY error")
        time.sleep(60 if all(state.get(k+":"+s,{}).get("done") for k in ("linear","spot") for s in SYMS) else 5)
