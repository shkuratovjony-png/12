"""Bounded public-market research. No account access or order placement."""
import math,time,os,json,threading,logging
import market,store
BAR=market.BAR
EXTRA=("funding","basis","oi_change","spread","book_imbalance","book_depth","taker_delta","trade_pressure","liq_long","liq_short","spot_basis","price_change24h")
TECH=("macd","macd_hist","sma20_gap","sma50_gap","ema100_gap","stoch","cci","williams","mfi","obv_slope","vwap_gap","adx","di_gap","roc1","roc48","roc96","boll_width","donchian","keltner","realized_vol","body_ratio","wick_bias","ichimoku_gap","fib_position","cmf","vol_change","trend_efficiency","aroon_gap","trix","tsi")

# Causal, explicitly defined features. Proxy names are intentional, not claims
# of complete discretionary SMC, Elliott, Wyckoff or trade-level volume profile.
ADVANCED=("ema9_gap","ema21_gap","ema200_gap","ema_cross_9_21","dema_gap","tema_gap","hull_gap","kama_gap","supertrend_gap","psar_gap","rsi_fast","rsi_slow","stoch_rsi","awesome_oscillator","ultimate_oscillator","ppo","dpo","fisher_transform","choppiness","ulcer_index","natr","chaikin_volatility","volume_z","force_index","ease_of_movement","pvt_slope","adl_slope","chaikin_oscillator","anchored_day_vwap_gap","prior_day_high_gap","prior_day_low_gap","prior_day_pivot_gap","prior_day_r1_gap","prior_day_s1_gap","support_gap","resistance_gap","swing_high_gap","swing_low_gap","bos_up","bos_down","choch_proxy","sweep_high","sweep_low","fvg_bull","fvg_bear","order_block_proxy","engulfing","hammer","shooting_star","doji","inside_bar","outside_bar","morning_evening_star","three_bar_impulse","double_top_proxy","double_bottom_proxy","contraction_proxy","flag_proxy","triangle_proxy","wyckoff_spring_proxy","wyckoff_upthrust_proxy","fib_236_gap","fib_382_gap","fib_500_gap","fib_618_gap","fib_786_gap","fib_1272_gap","elliott_swing_proxy","profile_poc_proxy","profile_vah_proxy","profile_val_proxy","h1_trend","h1_rsi","h1_atr","h4_trend","h4_rsi","h4_atr","d1_trend","d1_rsi","d1_atr","w1_trend")
TECH=TECH+ADVANCED

def advanced(a):
    import numpy as np
    import pandas as pd
    t,o,h,l,c,v=map(pd.Series,a.T)
    def div(x,y):return x/y.replace(0,np.nan)
    def ema(x,n):return x.ewm(span=n,adjust=False,min_periods=n).mean()
    def wma(x,n):
        weights=np.arange(1,n+1,dtype=float)
        return x.rolling(n).apply(lambda y:np.dot(y,weights)/weights.sum(),raw=True)
    def rsi(x,n):
        d=x.diff()
        p=d.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
        m=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
        return div(p,p+m)*2-1
    def gap(x):return div(c-x,c)
    pc=c.shift();d=c.diff();typ=(h+l+c)/3
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    e9=ema(c,9);e21=ema(c,21);e20=ema(c,20);e2=ema(e20,20);e3=ema(e2,20)
    # Kaufman adaptive moving average, causal recursion.
    er=div((c-c.shift(10)).abs(),d.abs().rolling(10).sum())
    sc=(er*(2/3-2/31)+2/31)**2
    ka=np.full(len(c),np.nan)
    for i in range(10,len(c)):
        if np.isfinite(sc.iloc[i]):
            ka[i]=c.iloc[i] if not np.isfinite(ka[i-1]) else ka[i-1]+sc.iloc[i]*(c.iloc[i]-ka[i-1])
    # Supertrend bands and Wilder-style parabolic SAR; no future pivot access.
    st=np.full(len(c),np.nan);sar=np.full(len(c),np.nan)
    upper=lower=0.;up=True;ep=0.;af=.02;sup=True
    for i in range(1,len(c)):
        if np.isfinite(atr.iloc[i]):
            u=(h.iloc[i]+l.iloc[i])/2+3*atr.iloc[i];lo=(h.iloc[i]+l.iloc[i])/2-3*atr.iloc[i]
            if not np.isfinite(st[i-1]):upper=u;lower=lo;up=c.iloc[i]>=pc.iloc[i]
            else:
                upper=u if u<upper or pc.iloc[i]>upper else upper
                lower=lo if lo>lower or pc.iloc[i]<lower else lower
                if up and c.iloc[i]<lower:up=False
                elif not up and c.iloc[i]>upper:up=True
            st[i]=lower if up else upper
        if i==1:
            sup=c.iloc[i]>=c.iloc[0];sar[i]=l.iloc[0] if sup else h.iloc[0];ep=h.iloc[i] if sup else l.iloc[i];continue
        x=sar[i-1]+af*(ep-sar[i-1])
        if sup:
            x=min(x,l.iloc[i-1],l.iloc[i-2])
            if l.iloc[i]<x:sup=False;x=ep;ep=l.iloc[i];af=.02
            elif h.iloc[i]>ep:ep=h.iloc[i];af=min(.2,af+.02)
        else:
            x=max(x,h.iloc[i-1],h.iloc[i-2])
            if h.iloc[i]>x:sup=True;x=ep;ep=h.iloc[i];af=.02
            elif l.iloc[i]<ep:ep=l.iloc[i];af=min(.2,af+.02)
        sar[i]=x
    r=rsi(c,14);rsmin=r.rolling(14).min();rsmax=r.rolling(14).max()
    bp=c-pd.concat([l,pc],axis=1).min(axis=1)
    ur=pd.concat([h,pc],axis=1).max(axis=1)-pd.concat([l,pc],axis=1).min(axis=1)
    uo=sum(w*div(bp.rolling(n).sum(),ur.rolling(n).sum()) for w,n in ((4,7),(2,14),(1,28)))/7*2-1
    x=div(c-l.rolling(10).min(),h.rolling(10).max()-l.rolling(10).min())*2-1
    fish=np.arctanh(x.clip(-.999,.999))
    hl=h.rolling(14).max()-l.rolling(14).min()
    chop=np.log10(div(tr.rolling(14).sum(),hl).clip(lower=1e-9))/np.log10(14)
    money=div(2*c-h-l,h-l)*v;adl=money.fillna(0).cumsum()
    pvt=(c.pct_change().fillna(0)*v).cumsum()
    day=(t//86400000).astype("int64")
    dv=div((typ*v).groupby(day).cumsum(),v.groupby(day).cumsum())
    # Prior fully closed UTC day only; discard partial sessions.
    frame=pd.DataFrame({"day":day,"h":h,"l":l,"c":c,"t":t})
    daily=frame.groupby("day").agg(h=("h","max"),l=("l","min"),c=("c","last"),n=("t","size"),first=("t","min"),last=("t","max"))
    good=(daily.n==96)&(daily["first"]==daily.index*86400000)&(daily["last"]==daily.index*86400000+95*BAR)
    daily.loc[~good,["h","l","c"]]=np.nan
    dh=day.map((daily.h).rename(index=lambda k:k+1));dl=day.map(daily.l.rename(index=lambda k:k+1));dc=day.map(daily.c.rename(index=lambda k:k+1));pivot=(dh+dl+dc)/3
    resistance=h.shift().rolling(24).max();support=l.shift().rolling(24).min()
    # 5-bar pivots become observable two bars AFTER the pivot.
    ph=h.shift(2).where(h.shift(2)==h.rolling(5).max()).ffill()
    pl=l.shift(2).where(l.shift(2)==l.rolling(5).min()).ffill()
    oldph=ph.shift();oldpl=pl.shift()
    bosup=(c>oldph)&(pc<=oldph);bosdn=(c<oldpl)&(pc>=oldpl)
    lastbreak=pd.Series(np.where(bosup,1,np.where(bosdn,-1,np.nan))).ffill().shift()
    sweepH=(h>resistance)&(c<resistance);sweepL=(l<support)&(c>support)
    body=c-o;span=(h-l).replace(0,np.nan);upperwick=h-pd.concat([o,c],axis=1).max(axis=1);lowerwick=pd.concat([o,c],axis=1).min(axis=1)-l
    engulf=np.where((body>0)&(body.shift()<0)&(o<=pc)&(c>=o.shift()),1,np.where((body<0)&(body.shift()>0)&(o>=pc)&(c<=o.shift()),-1,0))
    bullgap=div((l-h.shift(2)).clip(lower=0),c);beargap=div((l.shift(2)-h).clip(lower=0),c)
    ob=gap(o.shift().where((body.shift()<0)&bosup | (body.shift()>0)&bosdn).ffill())
    hh=h.shift().rolling(52).max();ll=l.shift().rolling(52).min();width=hh-ll
    # Approximate volume-at-price, assigns each candle volume to its close bin.
    poc=np.full(len(c),np.nan);vah=poc.copy();val=poc.copy()
    cv=c.to_numpy();vv=v.to_numpy()
    for i in range(63,len(c)):
        prices=cv[i-63:i+1];weights=vv[i-63:i+1]
        if prices.max()<=prices.min() or weights.sum()<=0:continue
        bins,edges=np.histogram(prices,bins=16,weights=weights)
        j=int(np.argmax(bins));left=right=j;mass=bins[j]
        while mass<.7*bins.sum() and (left>0 or right<15):
            if right<15 and (left==0 or bins[right+1]>bins[left-1]):right+=1;mass+=bins[right]
            else:left-=1;mass+=bins[left]
        poc[i]=(edges[j]+edges[j+1])/2;vah[i]=edges[right+1];val[i]=edges[left]
    # Multi-timeframe features from only complete, contiguous UTC buckets.
    def mtf(minutes):
        ms=minutes*60000;count=minutes//15;bucket=(t//ms).astype("int64")
        z=pd.DataFrame({"k":bucket,"c":c,"h":h,"l":l,"t":t}).groupby("k").agg(c=("c","last"),h=("h","max"),l=("l","min"),n=("t","size"),first=("t","min"),last=("t","max"))
        good=(z.n==count)&(z["first"]==z.index*ms)&(z["last"]==z.index*ms+(count-1)*BAR)
        z.loc[~good,["c","h","l"]]=np.nan
        zz=z.c;prev=zz.shift();tr2=pd.concat([z.h-z.l,(z.h-prev).abs(),(z.l-prev).abs()],axis=1).max(axis=1)
        # The last 15m candle in a bucket may use that bucket, but not earlier candles.
        available=((t+BAR)//ms-1).astype("int64")
        return available.map((ema(zz,5)-ema(zz,13))/zz),available.map(rsi(zz,14)),available.map(tr2.rolling(14).mean()/zz)
    a1,b1,c1=mtf(60);a4,b4,c4=mtf(240);ad,bd,cd=mtf(1440);aw,_,_=mtf(10080)
    out=dict(ema9_gap=gap(e9),ema21_gap=gap(e21),ema200_gap=gap(ema(c,200)),ema_cross_9_21=div(e9-e21,c),
        dema_gap=gap(2*e20-e2),tema_gap=gap(3*e20-3*e2+e3),hull_gap=gap(wma(2*wma(c,8)-wma(c,16),4)),kama_gap=gap(pd.Series(ka)),supertrend_gap=gap(pd.Series(st)),psar_gap=gap(pd.Series(sar)),
        rsi_fast=rsi(c,7),rsi_slow=rsi(c,28),stoch_rsi=div(r-rsmin,rsmax-rsmin)*2-1,awesome_oscillator=div(((h+l)/2).rolling(5).mean()-((h+l)/2).rolling(34).mean(),c),
        ultimate_oscillator=uo,ppo=div(ema(c,12)-ema(c,26),ema(c,26)),dpo=div(c.shift(11)-c.rolling(20).mean(),c),fisher_transform=fish,choppiness=chop,
        ulcer_index=np.sqrt((c/c.rolling(14).max()-1).pow(2).rolling(14).mean()),natr=div(atr,c),chaikin_volatility=ema(h-l,10).pct_change(10),
        volume_z=div(v-v.rolling(32).mean(),v.rolling(32).std()),force_index=div(ema(d*v,13),c*v.rolling(32).mean()),ease_of_movement=div(((h+l)/2).diff()*(h-l),v).rolling(14).mean(),
        pvt_slope=div(pvt.diff(20),v.rolling(20).sum()),adl_slope=div(adl.diff(20),v.rolling(20).sum()),chaikin_oscillator=div(ema(adl,3)-ema(adl,10),v.rolling(20).sum()),
        anchored_day_vwap_gap=gap(dv),prior_day_high_gap=gap(dh),prior_day_low_gap=gap(dl),prior_day_pivot_gap=gap(pivot),prior_day_r1_gap=gap(2*pivot-dl),prior_day_s1_gap=gap(2*pivot-dh),
        support_gap=gap(support),resistance_gap=gap(resistance),swing_high_gap=gap(oldph),swing_low_gap=gap(oldpl),bos_up=bosup.astype(float),bos_down=bosdn.astype(float),choch_proxy=pd.Series(np.where(bosup&(lastbreak==-1),1,np.where(bosdn&(lastbreak==1),-1,0))),
        sweep_high=sweepH.astype(float),sweep_low=sweepL.astype(float),fvg_bull=bullgap,fvg_bear=beargap,order_block_proxy=ob,engulfing=pd.Series(engulf),
        hammer=((lowerwick>2*body.abs())&(upperwick<body.abs())).astype(float),shooting_star=((upperwick>2*body.abs())&(lowerwick<body.abs())).astype(float),
        doji=(div(body.abs(),span)<.1).astype(float),inside_bar=((h<h.shift())&(l>l.shift())).astype(float),outside_bar=((h>h.shift())&(l<l.shift())).astype(float),
        morning_evening_star=pd.Series(np.where((body.shift(2)<0)&(body.shift().abs()<body.shift(2).abs()*.3)&(c>(o.shift(2)+c.shift(2))/2)&(body>0),1,np.where((body.shift(2)>0)&(body.shift().abs()<body.shift(2).abs()*.3)&(c<(o.shift(2)+c.shift(2))/2)&(body<0),-1,0))),
        three_bar_impulse=pd.Series(np.where((body>0)&(body.shift()>0)&(body.shift(2)>0),1,np.where((body<0)&(body.shift()<0)&(body.shift(2)<0),-1,0))),
        double_top_proxy=((h-oldph).abs()<atr*.3).astype(float)*(c<oldph).astype(float),double_bottom_proxy=((l-oldpl).abs()<atr*.3).astype(float)*(c>oldpl).astype(float),
        contraction_proxy=div(h.rolling(8).max()-l.rolling(8).min(),h.rolling(32).max()-l.rolling(32).min()),
        flag_proxy=div(c.shift(8)-c.shift(24),c)*div(h.rolling(32).max()-l.rolling(32).min(),h.rolling(8).max()-l.rolling(8).min()),
        triangle_proxy=div((h.rolling(8).max()-l.rolling(8).min()),(h.shift(8).rolling(8).max()-l.shift(8).rolling(8).min())),
        wyckoff_spring_proxy=sweepL.astype(float)*div(v,v.shift().rolling(24).mean()),wyckoff_upthrust_proxy=sweepH.astype(float)*div(v,v.shift().rolling(24).mean()),
        fib_236_gap=gap(ll+.236*width),fib_382_gap=gap(ll+.382*width),fib_500_gap=gap(ll+.5*width),fib_618_gap=gap(ll+.618*width),fib_786_gap=gap(ll+.786*width),fib_1272_gap=gap(ll+1.272*width),
        elliott_swing_proxy=div(c-oldpl,oldph-oldpl),profile_poc_proxy=gap(pd.Series(poc)),profile_vah_proxy=gap(pd.Series(vah)),profile_val_proxy=gap(pd.Series(val)),
        h1_trend=a1,h1_rsi=b1,h1_atr=c1,h4_trend=a4,h4_rsi=b4,h4_atr=c4,d1_trend=ad,d1_rsi=bd,d1_atr=cd,w1_trend=aw)
    assert set(out)==set(ADVANCED)
    result={}
    for k,x in out.items():
        y=np.asarray(x,dtype=float).copy();y[~np.isfinite(y)]=np.nan;result[k]=y
    return result

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
    result={k:np.asarray(x,dtype=float) for k,x in out.items()}
    result.update(advanced(a))
    return result
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
