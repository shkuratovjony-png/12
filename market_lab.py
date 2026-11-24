"""Bounded public-market research. No account access or order placement."""
import math,time,os,json,threading,logging
import market,store
BAR=market.BAR
EXTRA=("funding","basis","oi_change","spread","book_imbalance","book_depth","taker_delta","trade_pressure","liq_long","liq_short","spot_basis","price_change24h")
TECH=("macd","macd_hist","sma20_gap","sma50_gap","ema100_gap","stoch","cci","williams","mfi","obv_slope","vwap_gap","adx","di_gap","roc1","roc48","roc96","boll_width","donchian","keltner","realized_vol","body_ratio","wick_bias","ichimoku_gap","fib_position","cmf","vol_change","trend_efficiency","aroon_gap","trix","tsi")
def number(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None
def ratio(a,b):
    a,b=number(a),number(b)
    return a/b if a is not None and b is not None and b>0 else None
def technical(a):
    import pandas as pd
    import numpy as np
    _,o,h,l,c,v=map(pd.Series,a.T)
    def div(a,b):return a/b.replace(0,np.nan)
    def ema(s,n):return s.ewm(span=n,adjust=False).mean()
    def smooth(s,n):return s.ewm(alpha=1/n,adjust=False).mean()
    d=c.diff(); typical=(h+l+c)/3
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=smooth(tr,14); up=h.diff(); down=-l.diff()
    plus=div(smooth(up.where((up>down)&(up>0),0),14),atr)
    minus=div(smooth(down.where((down>up)&(down>0),0),14),atr)
    dx=div((plus-minus).abs(),plus+minus)
    m=ema(c,12)-ema(c,26); low=l.rolling(14).min(); high=h.rolling(14).max()
    money=typical*v; pos=money.where(typical.diff()>0,0).rolling(14).sum(); neg=money.where(typical.diff()<0,0).rolling(14).sum()
    avg=typical.rolling(20).mean(); mad=typical.rolling(20).apply(lambda x:np.mean(np.abs(x-x.mean())),raw=True)
    obv=(np.sign(d).fillna(0)*v).cumsum()
    hh=h.rolling(52).max(); ll=l.rolling(52).min()
    t=ema(ema(ema(c,15),15),15)
    out=dict(macd=div(m,c),macd_hist=div(m-ema(m,9),c),sma20_gap=div(c,c.rolling(20).mean())-1,
      sma50_gap=div(c,c.rolling(50).mean())-1,ema100_gap=div(c,ema(c,100))-1,
      stoch=div(c-low,high-low)*2-1,cci=div(typical-avg,.015*mad)/100,
      williams=div(c-high,high-low)+.5,mfi=div(pos,pos+neg)*2-1,
      obv_slope=div(obv.diff(20),v.rolling(20).sum()),vwap_gap=div(c,div(money.rolling(32).sum(),v.rolling(32).sum()))-1,
      adx=smooth(dx,14),di_gap=plus-minus,roc1=c.pct_change(),roc48=c.pct_change(48),roc96=c.pct_change(96),
      boll_width=div(4*c.rolling(20).std(),c),donchian=div(c-l.rolling(20).min(),h.rolling(20).max()-l.rolling(20).min())*2-1,
      keltner=div(c-ema(c,20),2*atr),realized_vol=np.log(c).diff().rolling(32).std(),
      body_ratio=div(c-o,h-l),wick_bias=div(np.minimum(c,o)-l-(h-np.maximum(c,o)),h-l),
      ichimoku_gap=div(c-(hh+ll)/2,c),fib_position=div(c-ll,hh-ll)-.618,
      cmf=div((div(2*c-h-l,h-l)*v).rolling(20).sum(),v.rolling(20).sum()),
      vol_change=div(v,v.rolling(48).mean())-1,trend_efficiency=div(c.diff(24),d.abs().rolling(24).sum()),
      aroon_gap=(h.rolling(25).apply(np.argmax,raw=True)-l.rolling(25).apply(np.argmin,raw=True))/24,
      trix=t.pct_change(),tsi=div(ema(ema(d,25),13),ema(ema(d.abs(),25),13)))
    return {k:np.asarray(x,dtype=float) for k,x in out.items()}
def aligned(rows,history):
    import numpy as np
    bybar={int(x["bar"]):x for x in history if int(x["bar"])<=int(x["observed"])<int(x["bar"])+BAR}
    return {k:np.array([bybar.get(int(r[0]),{}).get(k,np.nan) if bybar.get(int(r[0]),{}).get(k) is not None else np.nan for r in rows],dtype=float) for k in EXTRA}

_lock=threading.Lock()
_liq={}
_stream={"connected":False,"error":None}
def stream_worker():
    import websocket
    while True:
        syms=tuple(market.SYMBOLS)
        ws=None
        try:
            ws=websocket.create_connection(os.getenv("BYBIT_PUBLIC_WS","wss://stream.bybit.com/v5/public/linear"),timeout=10)
            ws.send(json.dumps({"op":"subscribe","args":["allLiquidation."+s for s in syms]}))
            ack=False; last_ping=time.monotonic()
            while tuple(market.SYMBOLS)==syms:
                if time.monotonic()-last_ping>18:
                    ws.send(json.dumps({"op":"ping"}));last_ping=time.monotonic()
                try: msg=json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:continue
                if msg.get("op")=="subscribe":
                    if not msg.get("success"):raise RuntimeError("liquidation subscription rejected")
                    ack=True
                    with _lock:_stream.update(connected=True,error=None)
                if ack and msg.get("topic","").startswith("allLiquidation."):
                    now=int(time.time()*1000); bar=now//BAR*BAR
                    with _lock:
                        for item in msg.get("data",[]):
                            s=item.get("s"); p=number(item.get("p"));v=number(item.get("v"))
                            if s not in syms or not p or not v or p<0 or v<0 or item.get("S") not in ("Buy","Sell"):continue
                            if int(item.get("T",0))//BAR*BAR!=bar:continue
                            q=_liq.get(s,[bar,0.,0.])
                            if q[0]!=bar:q=[bar,0.,0.]
                            q[1 if item["S"]=="Buy" else 2]+=p*v
                            _liq[s]=q
        except Exception as e:
            with _lock:_stream.update(connected=False,error=str(e)[:140])
        finally:
            with _lock:_stream["connected"]=False
            if ws:ws.close()
        time.sleep(30)
def triangle(tickers, fee=.0015, amount=100.):
    # Explicit limited currency universe; quote-side conversion at displayed bid/ask.
    assets=("USDT","USDC","BTC","ETH","SOL","XRP","BNB","DOGE","ADA","AVAX","LINK","TON")
    edges={}
    for a in assets:
        for b in assets:
            if a==b:continue
            q=tickers.get(a+b,{})
            bid,ask,bs,az=map(number,(q.get("bid1Price"),q.get("ask1Price"),q.get("bid1Size"),q.get("ask1Size")))
            if not all(x is not None and x>0 for x in (bid,ask,bs,az)) or bid>ask:continue
            edges[a,b]=(bid*(1-fee),bs)
            edges[b,a]=((1-fee)/ask,az*ask)
    out=[]
    for a in assets[1:]:
        for b in assets[1:]:
            if a==b:continue
            path=("USDT",a,b,"USDT"); val=amount
            for pair in zip(path,path[1:]):
                edge=edges.get(pair)
                if not edge or val>edge[1]:break
                val*=edge[0]
            else:out.append({"path":list(path),"net_estimate":val/amount-1,"initial_usdt":amount})
    return sorted(out,key=lambda x:x["net_estimate"],reverse=True)[:10]
def snapshot(sym,ticker,spot):
    book=market.request("/v5/market/orderbook",category="linear",symbol=sym,limit=50)
    trades=market.request("/v5/market/recent-trade",category="linear",symbol=sym,limit=200)["list"]
    now=int(time.time()*1000);bar=now//BAR*BAR
    bid,ask=number(ticker.get("bid1Price")),number(ticker.get("ask1Price"))
    mark,index=number(ticker.get("markPrice")),number(ticker.get("indexPrice"))
    oi=number(ticker.get("openInterestValue"))
    history=store.get("micro:"+sym,[])
    prev=next((x.get("oi") for x in reversed(history) if x["bar"]<bar and bar-x["bar"]<=2*BAR and x.get("oi")),None)
    b=sum(float(p)*float(v) for p,v in book["b"]);a=sum(float(p)*float(v) for p,v in book["a"])
    buy=sum(float(x["price"])*float(x["size"]) for x in trades if x["side"]=="Buy")
    sell=sum(float(x["price"])*float(x["size"]) for x in trades if x["side"]=="Sell")
    sp=number(spot.get("lastPrice")); basis=ratio(mark,index); spotbasis=ratio(mark,sp); oic=ratio(oi,prev)
    with _lock:
        liq=_liq.get(sym); connected=_stream["connected"]
    row={"bar":bar,"observed":now,"funding":number(ticker.get("fundingRate")),"oi":oi,
         "oi_change":oic-1 if oic is not None else None,"basis":basis-1 if basis is not None else None,
         "spread":ratio(ask-bid,ask) if ask and bid else None,"book_imbalance":ratio(b-a,b+a),
         "book_depth":math.log1p(b+a),"taker_delta":ratio(buy-sell,buy+sell),
         "trade_pressure":math.log1p(buy+sell),"liq_long":math.log1p(liq[1]) if connected and liq and liq[0]==bar else None,
         "liq_short":math.log1p(liq[2]) if connected and liq and liq[0]==bar else None,
         "spot_basis":spotbasis-1 if spotbasis is not None else None,"price_change24h":number(ticker.get("price24hPcnt")),
         "mark":mark,"index":index,"spot":sp,"trade_sample_count":len(trades)}
    store.put("micro:"+sym,([x for x in history if x["bar"]!=bar]+[row])[-3000:])
    return row
def collector():
    offset=0
    while True:
        errors={}; latest={}
        try:
            syms=list(market.SYMBOLS)
            linear={x["symbol"]:x for x in market.request("/v5/market/tickers",category="linear")["list"]}
            spot={x["symbol"]:x for x in market.request("/v5/market/tickers",category="spot")["list"]}
            arbs=triangle(spot)
            store.put("arb_scan",{"time":time.time(),"routes":arbs,"fee_per_leg_including_buffer":.0015,
                "note":"Indicative snapshot only; no orders or guaranteed execution. Limited currency universe."})
            for i in range(min(4,len(syms))):
                sym=syms[(offset+i)%len(syms)]
                try:latest[sym]=snapshot(sym,linear[sym],spot.get(sym,{}))
                except Exception as e:errors[sym]=str(e)[:150]
                time.sleep(1)
            offset=(offset+4)%len(syms)
        except Exception as e:errors["collector"]=str(e)[:150]
        with _lock: ws=dict(_stream)
        try:store.put("micro_status",{"time":time.time(),"updated":list(latest),"errors":errors,"liquidation_stream":ws})
        except Exception:logging.exception("micro status storage")
        time.sleep(90)
