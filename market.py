"""Public-only Bybit linear USDT research. No keys and no order placement."""
import os,time,math,requests
from store import get,put
BASE=os.getenv("BYBIT_PUBLIC_URL","https://api.bybit.com").rstrip("/")
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT"]
BAR=900000
MIN_TURNOVER=max(1000000,float(os.getenv("MIN_TURNOVER_USDT","20000000")))
MAX_SYMBOLS=max(3,min(16,int(os.getenv("MAX_RESEARCH_SYMBOLS","12"))))
_NEXT_SCAN=0

_COOLDOWN_UNTIL=0.0
_RATE_FAILURES=0


# Shared process-wide market gateway. No credentials, no exchange orders.
import threading,json,logging,random
import tick_flow,scalp_lab
from collections import deque
_LOCK=threading.RLock()
_REST_LOCK=threading.Lock()
_STARTED=False
_NEXT_HTTP=0.
_CACHE={}
_TICK={}
_BOOK={}
_TRADES={}
_BARS={}
_WANTED={"linear":set(),"spot":set()}
_WS={"linear":{"connected":False},"spot":{"connected":False}}
_STATS={"rest_calls":0,"ws_hits":0,"cache_hits":0}
_MAX_STREAM={"linear":20,"spot":12}
_SPOT_ACTIVE={"BTCUSDT","ETHUSDT","SOLUSDT"}

def set_spot_symbols(symbols):
    with _LOCK:
        _SPOT_ACTIVE.clear();_SPOT_ACTIVE.update(symbols)

def _fresh(entry,age):
    return entry is not None and time.monotonic()-entry[0]<=age

def _want(category,symbol):
    if category not in _WANTED or not symbol:return
    with _LOCK:
        if len(_WANTED[category])<_MAX_STREAM[category]:_WANTED[category].add(symbol)

_PINNED={"linear":set(),"spot":set()}
_DEMO_PINNED=set()
_GRID_WANTED=set()
def pin_demo(symbols):
    with _LOCK:
        _DEMO_PINNED.clear();_DEMO_PINNED.update(symbols)
def set_grid_symbols(symbols):
    with _LOCK:
        _GRID_WANTED.clear();_GRID_WANTED.update(symbols)
def pin_positions(positions):
    with _LOCK:
        for cat in _PINNED:_PINNED[cat]={p["symbol"] for p in positions if p.get("market","linear")==cat}
def _topics(category):
    with _LOCK:
        primary=(set(SYMBOLS) if category=="linear" else set(_SPOT_ACTIVE))|set(scalp_lab.CORE)
        pinned=_PINNED[category]|(_DEMO_PINNED if category=="linear" else set())
        grid=_GRID_WANTED if category=="linear" else set()
        core=set(scalp_lab.CORE)
        symbols=(sorted(pinned)+sorted(core-pinned)+sorted(grid-pinned-core)+sorted(primary-pinned-core-grid)+sorted(_WANTED[category]-primary-pinned-core-grid))[:_MAX_STREAM[category]]
    topics=[]
    for sym in symbols:
        topics.extend(["tickers."+sym,"orderbook.50."+sym,"kline.15."+sym])
        topics.append("publicTrade."+sym)
    return set(topics)

def _invalidate(category):
    tick_flow.disconnect(category)
    scalp_lab.disconnect(category)
    with _LOCK:
        for mapping in (_TICK,_BOOK,_TRADES):
            for k in list(mapping):
                if k[0]==category:del mapping[k]

def _on_message(category,msg):
    topic=msg.get("topic","");data=msg.get("data")
    if not topic or data is None:return
    sym=topic.rsplit(".",1)[-1];key=(category,sym);now=time.monotonic()
    with _LOCK:
        if topic.startswith("tickers.") and isinstance(data,dict):
            old=_TICK.get(key,(0,{}))[1]
            if msg.get("type")=="snapshot":old={}
            if not old and msg.get("type")=="delta":return
            _TICK[key]=(now,{**old,**data,"symbol":sym})
        elif topic.startswith("orderbook.") and isinstance(data,dict):
            prev=_BOOK.get(key)
            if msg.get("type")=="snapshot" or data.get("u")==1:
                bids={};asks={}
            elif prev:
                _,bids,asks,seq=prev
                if int(data.get("u",0))<seq:return
            else:return
            for side,levels in ((bids,data.get("b",[])),(asks,data.get("a",[]))):
                for p,v in levels:
                    p=float(p);v=float(v)
                    if v==0:side.pop(p,None)
                    elif p>0 and v>0 and math.isfinite(p) and math.isfinite(v):side[p]=v
            _BOOK[key]=(now,bids,asks,int(data.get("u",0)))
        elif topic.startswith("publicTrade.") and isinstance(data,list):
            tick_flow.ingest(category,sym,data)
            scalp_lab.ingest(category,sym,data)
            q=_TRADES.setdefault(key,deque(maxlen=200))
            for t in data:
                if t.get("S") in ("Buy","Sell"):
                    q.append({"price":t["p"],"size":t["v"],"side":t["S"],"time":str(t["T"])})
        elif topic.startswith("kline.") and isinstance(data,list):
            q=_BARS.setdefault(key,{})
            for x in data:
                if x.get("confirm") is True:
                    row=[int(x["start"])]+[float(x[k]) for k in ("open","high","low","close","volume")]
                    if all(math.isfinite(v) and v>0 for v in row[1:5]) and math.isfinite(row[5]) and row[5]>=0:q[row[0]]=row
            for k in sorted(q)[:-16]:del q[k]
        else:return
        _WS[category]["last_message"]=time.time()
        _WS[category]["messages"]=_WS[category].get("messages",0)+1

def _stream(category):
    import websocket
    pause=5
    while True:
        ws=None
        try:
            _invalidate(category)
            root=os.getenv("BYBIT_WS_ROOT","wss://stream.bybit.com/v5/public").rstrip("/")
            ws=websocket.create_connection(root+"/"+category,timeout=5)
            subscribed=set();ping=0.;last= time.monotonic();check=0.
            with _LOCK:_WS[category].update(connected=True,error=None,subscribed=0)
            while True:
                now=time.monotonic()
                if now-check>=5:
                    desired=_topics(category)
                    for op,topics in (("unsubscribe",subscribed-desired),("subscribe",desired-subscribed)):
                        topics=sorted(topics)
                        for i in range(0,len(topics),10):ws.send(json.dumps({"op":op,"args":topics[i:i+10]}))
                    for topic in desired-subscribed:
                        if topic.startswith("publicTrade."):
                            tick_flow.subscription(category,topic.split(".",1)[1]);scalp_lab.subscription(category,topic.split(".",1)[1])
                    subscribed=desired;check=now
                    with _LOCK:_WS[category]["subscribed"]=len(subscribed)
                if now-ping>=18:ws.send(json.dumps({"op":"ping"}));ping=now
                if now-last>45:raise RuntimeError("No websocket messages for 45 seconds")
                try:raw=ws.recv()
                except websocket.WebSocketTimeoutException:continue
                if not raw:raise RuntimeError("WebSocket closed")
                last=time.monotonic();msg=json.loads(raw)
                if msg.get("op") in ("subscribe","unsubscribe") and msg.get("success") is False:
                    raise RuntimeError("Subscription rejected: "+str(msg.get("ret_msg",""))[:120])
                _on_message(category,msg)
                if msg.get("topic"):pause=5
        except Exception as e:
            with _LOCK:_WS[category].update(connected=False,error=str(e)[:180],subscribed=0)
            logging.warning("FEED %s reconnect: %s",category,str(e)[:150])
        finally:
            _invalidate(category)
            if ws:
                try:ws.close()
                except Exception:pass
        time.sleep(pause+random.random()*2);pause=min(120,pause*2)

def feed_selftest():
    k=("linear","TESTUSDT")
    _on_message("linear",{"topic":"tickers.TESTUSDT","type":"snapshot","data":{"lastPrice":"100","fundingRate":"0.01"}})
    _on_message("linear",{"topic":"tickers.TESTUSDT","type":"delta","data":{"lastPrice":"101"}})
    _on_message("linear",{"topic":"orderbook.50.TESTUSDT","type":"snapshot","data":{"b":[["99","2"],["98","3"]],"a":[["101","4"]],"u":2}})
    _on_message("linear",{"topic":"orderbook.50.TESTUSDT","type":"delta","data":{"b":[["99","0"],["100","1"]],"a":[],"u":3}})
    t=_ws_ticker(*k)
    assert t["fundingRate"]=="0.01" and float(t["bid1Price"])==100 and float(t["ask1Price"])==101
    _on_message("linear",{"topic":"kline.15.TESTUSDT","data":[{"start":0,"open":"100","high":"102","low":"99","close":"101","volume":"10","confirm":False}]})
    assert not ws_bars(*k)
    _on_message("linear",{"topic":"kline.15.TESTUSDT","data":[{"start":0,"open":"100","high":"102","low":"99","close":"101","volume":"10","confirm":True}]})
    assert len(ws_bars(*k))==1
    with _LOCK:
        for mapping in (_TICK,_BOOK,_BARS):mapping.pop(k,None)
        _WS["linear"]={"connected":False}

def start_feeds():
    global _STARTED
    with _LOCK:
        if _STARTED:return
        _STARTED=True
        for category in ("linear","spot"):
            threading.Thread(target=_stream,args=(category,),daemon=True,name="market-"+category).start()

def feed_status():
    with _LOCK:
        return {"time":time.time(),"streams":{k:dict(v) for k,v in _WS.items()},
                "fresh_books":sum(_fresh(x,5) for x in _BOOK.values()),"fresh_tickers":sum(_fresh(x,10) for x in _TICK.values()),
                "rest_cooldown_seconds":max(0,int(_COOLDOWN_UNTIL-time.time())),**_STATS}

def _ws_ticker(category,symbol):
    key=(category,symbol)
    with _LOCK:
        t=_TICK.get(key);b=_BOOK.get(key)
        if not _fresh(t,10) or not _fresh(b,5) or not b[1] or not b[2]:return None
        bp=max(b[1]);ap=min(b[2])
        if not 0<bp<=ap:return None
        return {**t[1],"bid1Price":str(bp),"ask1Price":str(ap),"bid1Size":str(b[1][bp]),"ask1Size":str(b[2][ap])}

def scalp_quote(category,symbol):
    with _LOCK:
        b=_BOOK.get((category,symbol))
        if not _fresh(b,2) or not b[1] or not b[2]:return None
        bids=sorted(b[1],reverse=True)[:50];asks=sorted(b[2])[:50]
        bp=bids[0];ap=asks[0]
        if not 0<bp<=ap:return None
        return {"bid":bp,"ask":ap,"bid_size":b[1][bp],"ask_size":b[2][ap],
                "bid_depth":sum(p*b[1][p] for p in bids[:10]),"ask_depth":sum(p*b[2][p] for p in asks[:10]),
                "bids":[[p,b[1][p]] for p in bids],"asks":[[p,b[2][p]] for p in asks],
                "age":time.monotonic()-b[0],"time":time.time()}

def ws_bars(category,symbol):
    with _LOCK:return [list(x) for x in _BARS.get((category,symbol),{}).values()]

def _ws_result(path,params):
    category=params.get("category");symbol=params.get("symbol")
    if not symbol or category not in _WANTED:return None
    key=(category,symbol)
    if path=="/v5/market/tickers":
        t=_ws_ticker(category,symbol)
        if t:return {"list":[t]}
    elif path=="/v5/market/orderbook":
        with _LOCK:
            b=_BOOK.get(key)
            if _fresh(b,5) and b[1] and b[2] and category=="linear":
                limit=int(params.get("limit",50))
                return {"b":[[str(p),str(b[1][p])] for p in sorted(b[1],reverse=True)[:limit]],
                        "a":[[str(p),str(b[2][p])] for p in sorted(b[2])[:limit]]}
    elif path=="/v5/market/recent-trade":
        with _LOCK:
            q=_TRADES.get(key)
            if q and time.time()*1000-int(q[-1]["time"])<=30000:
                return {"list":list(q)[-int(params.get("limit",200)):]}
    return None

def _ttl(path,params):
    if path=="/v5/market/tickers":return 0 if params.get("symbol") else 60
    if path in ("/v5/market/orderbook","/v5/market/recent-trade"):return 2
    if path=="/v5/market/kline":return 30
    return 0

def _overlay(result,category):
    return {"list":[_ws_ticker(category,t.get("symbol")) or t for t in result["list"]]}

def _cooldown(reason):
    """Back off rather than repeatedly querying a blocked public endpoint."""
    global _COOLDOWN_UNTIL, _RATE_FAILURES
    _RATE_FAILURES=min(6,_RATE_FAILURES+1)
    wait=max(600 if "HTTP 403" in str(reason) else 120,min(3600,60*(2**_RATE_FAILURES)))
    _COOLDOWN_UNTIL=time.time()+wait
    raise RuntimeError("Bybit public API cooldown (%ds): %s" % (wait,str(reason)[:130]))

def request(path,**params):
    global _RATE_FAILURES,_NEXT_HTTP
    start_feeds()
    category=params.get("category");symbol=params.get("symbol")
    _want(category,symbol)
    result=_ws_result(path,params)
    if result is not None:
        with _LOCK:_STATS["ws_hits"]+=1
        return result
    ttl=_ttl(path,params)
    # Equivalent historical calls within the same 30-second window are coalesced.
    normalized=dict(params)
    if path=="/v5/market/kline" and "end" in normalized:normalized["end"]=int(normalized["end"])//30000
    key=(path,tuple(sorted(normalized.items())))
    with _REST_LOCK:
        result=_ws_result(path,params)
        if result is not None:
            with _LOCK:_STATS["ws_hits"]+=1
            return result
        item=_CACHE.get(key)
        if ttl and _fresh(item,ttl):
            with _LOCK:_STATS["cache_hits"]+=1
            return _overlay(item[1],category) if path=="/v5/market/tickers" and not symbol else item[1]
        if time.time()<_COOLDOWN_UNTIL:
            raise RuntimeError("Bybit REST cooldown, retry after %ds"%max(1,int(_COOLDOWN_UNTIL-time.time())))
        delay=_NEXT_HTTP-time.monotonic()
        if delay>0:time.sleep(delay)
        _NEXT_HTTP=time.monotonic()+1.5
        with _LOCK:_STATS["rest_calls"]+=1
        r=requests.get(BASE+path,params=params,timeout=10)
        if r.status_code in (403,429):_cooldown("HTTP "+str(r.status_code))
        r.raise_for_status();data=r.json()
        if data.get("retCode")!=0:
            reason=str(data.get("retMsg","Bybit API error"))[:200]
            if data.get("retCode") in (10006,10018) or "Too many visits" in reason or "Rate Limit" in reason:_cooldown(reason)
            raise RuntimeError(reason)
        _RATE_FAILURES=0;result=data["result"]
        if ttl:
            _CACHE[key]=(time.monotonic(),result)
            for k in list(_CACHE):
                if not _fresh(_CACHE[k],120):del _CACHE[k]
            while len(_CACHE)>128:del _CACHE[next(iter(_CACHE))]
        return _overlay(result,category) if path=="/v5/market/tickers" and not symbol else result

def rank_tickers(tickers,minimum=MIN_TURNOVER,limit=MAX_SYMBOLS):
    ranked=[]
    for item in tickers:
        try:
            symbol=item["symbol"]
            volume=float(item["turnover24h"])
            bid=float(item["bid1Price"]);ask=float(item["ask1Price"])
            if not(symbol.endswith("USDT") and symbol.isalnum() and volume>=minimum):continue
            if not(0<bid<=ask and (ask-bid)/ask<=0.002):continue
            ranked.append((symbol,volume))
        except (ValueError,TypeError,KeyError,OverflowError):
            continue
    ranked.sort(key=lambda z:z[1],reverse=True)
    return ranked[:limit],len(ranked)

def load_universe(force=False):
    global _NEXT_SCAN
    now=time.time()
    if not force and now<_NEXT_SCAN:return list(SYMBOLS)
    saved=get("research_universe",{})
    if not force and saved.get("updated_at",0)>now-21600 and saved.get("symbols"):
        SYMBOLS[:]=saved["symbols"][:MAX_SYMBOLS]
        _NEXT_SCAN=saved["updated_at"]+21600
        return list(SYMBOLS)
    try:
        all_tickers=request("/v5/market/tickers",category="linear")["list"]
        pairs,eligible=rank_tickers(all_tickers)
        if len(pairs)<3:raise RuntimeError("Not enough liquid pairs")
        SYMBOLS[:]=[symbol for symbol,_ in pairs]
        put("research_universe",{"updated_at":now,"eligible":eligible,
            "symbols":list(SYMBOLS),"turnover24h":dict(pairs),
            "selection":"24h turnover >=20M USDT, spread <=0.2%, capped at 12-16"})
        _NEXT_SCAN=now+21600
    except Exception:
        if saved.get("symbols"):SYMBOLS[:]=saved["symbols"][:MAX_SYMBOLS]
        _NEXT_SCAN=now+900
    return list(SYMBOLS)

def candles(symbol,pages=1):
    now=int(time.time()*1000)
    old={int(r[0]):r for r in get("candles:"+symbol,[])}
    latest_closed=((now-2000)//BAR-1)*BAR
    changed=False
    for row in ws_bars("linear",symbol):
        if row[0]+BAR<=now-2000 and row[0] not in old:old[row[0]]=row;changed=True
    if old and len(old)>=800 and max(old)>=latest_closed:
        rows=sorted(old.values(),key=lambda r:r[0])[-3000:]
        if changed:put("candles:"+symbol,rows)
        return rows
    end=now
    for _ in range(pages):
        raw=request("/v5/market/kline",category="linear",symbol=symbol,
                    interval="15",limit=1000 if len(old)<800 else 10,end=end)["list"]
        if not raw:break
        for r in raw:
            row=[int(r[0])]+[float(x) for x in r[1:6]]
            if row[0]+BAR<=now-2000 and all(math.isfinite(x) and x>0 for x in row[1:5]) and math.isfinite(row[5]) and row[5]>=0:
                old[row[0]]=row
        end=min(int(r[0]) for r in raw)-1
        if len(old)>=3000:break
    result=sorted(old.values(),key=lambda r:r[0])[-3000:]
    if result:put("candles:"+symbol,result)
    return result

def quote(symbol):
    item=request("/v5/market/tickers",category="linear",symbol=symbol)["list"][0]
    bid=float(item["bid1Price"]);ask=float(item["ask1Price"])
    if not(0<bid<=ask and math.isfinite(ask)):raise RuntimeError("Invalid bid/ask")
    return bid,ask
