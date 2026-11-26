"""Shared public Bybit candle feed for virtual strategies. No private endpoints."""
import time, threading, json, logging
from collections import deque
import requests, websocket
BASE="https://api.bybit.com/v5/market/"
LOCK=threading.RLock()
HTTP=threading.Lock()
LOCAL=threading.local()
NEXT=0.
PAUSE=0.
CACHE={}
META={}
META_AT=0.
DATA={}
SEEN=set()
STREAMS={}
STARTED=False
INTERVALS=(1,5,15)
def request(path,**params):
    global NEXT,PAUSE
    key=(path,tuple(sorted(params.items())))
    ttl=3 if path=="tickers" else 300 if path=="instruments-info" else 60 if path=="funding/history" else 0
    with HTTP:
        now=time.monotonic()
        item=CACHE.get(key)
        if ttl and item and now-item[0]<=ttl:return item[1]
        if now<PAUSE:raise RuntimeError("Shared public API cooldown %.0fs"%(PAUSE-now))
        if NEXT>now:time.sleep(NEXT-now)
        NEXT=time.monotonic()+1.2
        if not hasattr(LOCAL,"session"):LOCAL.session=requests.Session()
        r=LOCAL.session.get(BASE+path,params={"category":"linear",**params},timeout=8)
        if r.status_code in (403,429):
            PAUSE=time.monotonic()+120
            raise RuntimeError("Shared public API HTTP "+str(r.status_code))
        r.raise_for_status();d=r.json()
        if d.get("retCode") in (10006,10018):
            PAUSE=time.monotonic()+60
            raise RuntimeError("Shared public API rate limit "+str(d.get("retCode")))
        if d.get("retCode")!=0:raise RuntimeError("Shared public API "+str(d.get("retCode")))
        result=d["result"]
        if ttl:
            CACHE[key]=(time.monotonic(),result)
            for k in list(CACHE):
                if time.monotonic()-CACHE[k][0]>600:del CACHE[k]
        return result
def instruments():
    global META,META_AT
    if META and time.time()-META_AT<300:return META
    page="";out={}
    while True:
        d=request("instruments-info",limit=1000,**({"cursor":page} if page else {}))
        for m in d["list"]:
            if m.get("status")=="Trading" and m.get("contractType")=="LinearPerpetual" and m.get("quoteCoin")=="USDT" and m.get("settleCoin")=="USDT":out[m["symbol"]]=m
        page=d.get("nextPageCursor")
        if not page:break
    if not out:raise RuntimeError("Empty USDT universe")
    with LOCK:
        META=out;META_AT=time.time()
        for sym in list(DATA):
            if sym not in META:del DATA[sym]
    return META
def valid_rows(rows,n,end,interval):
    step=interval*60000
    return len(rows)>=n and rows[-1][0]==end-step and all(b[0]-a[0]==step for a,b in zip(rows[-n:],rows[-n+1:]))
def get_rows(sym,i,end,n=30):
    with LOCK:
        rows=list(DATA.get(sym,{}).get(i,()))
    rows=[r for r in rows if r[0]<end][-n:]
    return rows if valid_rows(rows,n,end,i) else None
def aggregate(rows,i):
    step=i*60000
    groups={}
    for r in rows:groups.setdefault(r[0]//step*step,[]).append(r)
    out=[]
    for start,a in sorted(groups.items()):
        if len(a)==i and a[0][0]==start and all(y[0]-x[0]==60000 for x,y in zip(a,a[1:])):
            out.append((start,a[0][1],max(r[2] for r in a),min(r[3] for r in a),a[-1][4]))
    return out
def append(sym,row):
    with LOCK:
        d=DATA.setdefault(sym,{i:deque(maxlen=45 if i==1 else 32) for i in INTERVALS})
        a=d[1]
        if a and row[0]<=a[-1][0]:return
        a.append(row)
        for i in (5,15):
            step=i*60000
            if (row[0]+60000)%step:continue
            recent=list(a)[-i:]
            if len(recent)!=i or recent[0][0]!=row[0]+60000-step or any(y[0]-x[0]!=60000 for x,y in zip(recent,recent[1:])):continue
            out=(recent[0][0],recent[0][1],max(r[2] for r in recent),min(r[3] for r in recent),recent[-1][4])
            if not d[i] or out[0]>d[i][-1][0]:d[i].append(out)
def seed(sym):
    end=int(time.time()//60)*60000
    raw=request("kline",symbol=sym,interval="1",end=end-1,limit=480)["list"]
    rows=sorted([(int(r[0]),*map(float,r[1:5])) for r in raw if int(r[0])<end])
    if not rows:return
    with LOCK:
        # Merge websocket candles received while fetching. No look-ahead.
        live=list(DATA.get(sym,{}).get(1,()))
        merged={r[0]:r for r in rows};merged.update({r[0]:r for r in live})
        rows=sorted(merged.values())
        DATA[sym]={1:deque(rows[-45:],maxlen=45),5:deque(aggregate(rows,5)[-32:],maxlen=32),15:deque(aggregate(rows,15)[-32:],maxlen=32)}
        SEEN.add(sym)
def stream(idx):
    pause=2
    while True:
        ws=None
        try:
            ws=websocket.create_connection("wss://stream.bybit.com/v5/public/linear",timeout=10);ws.settimeout(2)
            subscribed=set();last_check=0.;ping=0.;last=time.monotonic()
            STREAMS[idx]=True
            while True:
                now=time.monotonic()
                if now-last_check>10:
                    with LOCK:syms=sorted(META)
                    wanted={"kline.1."+s for s in syms if sum(s.encode())%SHARDS==idx}
                    for op,topics in (("unsubscribe",subscribed-wanted),("subscribe",wanted-subscribed)):
                        topics=sorted(topics)
                        for k in range(0,len(topics),40):ws.send(json.dumps({"op":op,"args":topics[k:k+40]}))
                    subscribed=wanted;last_check=now
                if now-ping>18:ws.send(json.dumps({"op":"ping"}));ping=now
                if now-last>60:raise RuntimeError("No candle stream messages")
                try:raw=ws.recv()
                except websocket.WebSocketTimeoutException:continue
                if not raw:raise RuntimeError("Stream closed")
                last=time.monotonic();msg=json.loads(raw)
                if msg.get("op")=="subscribe" and msg.get("success") is False:raise RuntimeError("Subscribe rejected "+str(msg.get("ret_msg")))
                if not msg.get("topic","").startswith("kline.1."):continue
                sym=msg["topic"].rsplit(".",1)[-1]
                for x in msg.get("data",[]):
                    if x.get("confirm") is True:
                        append(sym,(int(x["start"]),*(float(x[k]) for k in ("open","high","low","close"))))
                pause=2
        except Exception as e:
            logging.warning("PAPER SHARED stream %s: %s",idx,str(e)[:120])
        finally:
            STREAMS[idx]=False
            if ws:
                try:ws.close()
                except Exception:pass
        time.sleep(pause);pause=min(60,pause*2)
SHARDS=6
def seed_worker():
    cursor=0;last_log=0.
    while True:
        try:
            meta=instruments();symbols=sorted(meta)
            end=int((time.time()-5)//60)*60000
            if not symbols:time.sleep(5);continue
            # Prioritize unseeded instruments, then repair missing history in rotation.
            ordered=symbols[cursor:]+symbols[:cursor]
            sym=next((s for s in ordered if s not in SEEN),None)
            if sym is None:
                sym=next((s for s in ordered if get_rows(s,15,end//900000*900000) is None or get_rows(s,5,end//300000*300000) is None or get_rows(s,1,end) is None),None)
            if sym is not None:
                cursor=(symbols.index(sym)+1)%len(symbols)
                seed(sym)
                # Newly listed instruments can have fewer than 30 completed M15 bars.
                # Avoid monopolizing bootstrap: rotate after each attempt.
                SEEN.add(sym)
            else:time.sleep(5)
            if time.time()-last_log>30:
                logging.info("PAPER SHARED universe=%s seeded=%s streams=%s/%s",len(symbols),len(SEEN),sum(STREAMS.values()),SHARDS);last_log=time.time()
            time.sleep(.3)
        except Exception as e:
            logging.warning("PAPER SHARED seed: %s",str(e)[:120]);time.sleep(10)
def start():
    global STARTED
    with LOCK:
        if STARTED:return
        STARTED=True
        threading.Thread(target=seed_worker,daemon=True,name="paper-seed").start()
        for idx in range(SHARDS):threading.Thread(target=stream,args=(idx,),daemon=True,name="paper-kline-"+str(idx)).start()
def status():
    with LOCK:
        return {"universe":len(META),"seeded":len(SEEN),"streams":sum(STREAMS.values()),"stream_total":SHARDS,"cooldown":max(0,int(PAUSE-time.monotonic()))}
def selftest():
    rows=[(i*60000,100.,101.,99.,100.) for i in range(480)]
    a=aggregate(rows,15)
    assert len(a)==32 and valid_rows(a,30,480*60000,15)
    assert len(aggregate(rows[1:],15))==31
    assert not valid_rows(a[:-1],30,480*60000,15)
