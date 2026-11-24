"""Public market data only. No credentials, no private or order endpoints."""
import os, time, requests, math
from store import get, put
BASE = os.getenv("BYBIT_PUBLIC_URL","https://api.bybit.com").rstrip("/")
SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT"]
BAR = 900000

def request(path, **params):
    r = requests.get(BASE+path,params=params,timeout=15)
    r.raise_for_status()
    j=r.json()
    if j.get("retCode")!=0: raise RuntimeError(str(j.get("retMsg","Bybit API error"))[:200])
    return j["result"]

def candles(symbol, pages=1):
    now=int(time.time()*1000)
    old={int(r[0]):r for r in get("candles:"+symbol,[])}
    end=now
    for _ in range(pages):
        rows=request("/v5/market/kline", category="linear",symbol=symbol,interval="15",limit=1000,end=end)["list"]
        if not rows: break
        for r in rows:
            row=[int(r[0])]+[float(x) for x in r[1:6]]
            if row[0]+BAR<=now-2000 and all(math.isfinite(x) and x>0 for x in row[1:5]) and row[5]>=0 and math.isfinite(row[5]):
                old[row[0]]=row
        end=min(int(r[0]) for r in rows)-1
    result=sorted(old.values(),key=lambda r:r[0])[-6000:]
    put("candles:"+symbol,result)
    return result

def quote(symbol):
    r=request("/v5/market/tickers",category="linear",symbol=symbol)["list"][0]
    bid,ask=float(r["bid1Price"]),float(r["ask1Price"])
    if not (0<bid<=ask and math.isfinite(ask)):raise RuntimeError("Invalid bid/ask")
    return bid,ask
