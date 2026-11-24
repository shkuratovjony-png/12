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

def _cooldown(reason):
    """Back off rather than repeatedly querying a blocked public endpoint."""
    global _COOLDOWN_UNTIL, _RATE_FAILURES
    _RATE_FAILURES=min(6,_RATE_FAILURES+1)
    wait=min(3600,60*(2**_RATE_FAILURES))
    _COOLDOWN_UNTIL=time.time()+wait
    raise RuntimeError("Bybit public API cooldown (%ds): %s" % (wait,str(reason)[:130]))

def request(path,**params):
    global _RATE_FAILURES
    if time.time()<_COOLDOWN_UNTIL:
        raise RuntimeError("Bybit API cooldown, retry after %ds" % max(1,int(_COOLDOWN_UNTIL-time.time())))
    r=requests.get(BASE+path,params=params,timeout=15)
    if r.status_code in (403,429):
        _cooldown("HTTP "+str(r.status_code))
    r.raise_for_status()
    data=r.json()
    if data.get("retCode")!=0:
        reason=str(data.get("retMsg","Bybit API error"))[:200]
        if data.get("retCode") in (10006,10018) or "Too many visits" in reason or "Rate Limit" in reason:
            _cooldown(reason)
        raise RuntimeError(reason)
    _RATE_FAILURES=0
    return data["result"]

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
    latest_closed=(now//BAR-1)*BAR
    if old and len(old)>=800 and max(old)>=latest_closed:
        return sorted(old.values(),key=lambda r:r[0])
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
