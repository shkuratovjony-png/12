"""Six rule-based hypotheses using only already completed 15-minute bars."""
import numpy as np
FAMILIES=("breakout","momentum","mean_reversion","trend_pullback","volatility_squeeze","volume_impulse")
def candidates():
    for family in FAMILIES:
        for lookback in (24,48):
            for level in (0,1):
                yield {"family":family,"lookback":lookback,"level":level}

def signals(rows,indexes,params,bar_ms=900000):
    a=np.asarray(rows,dtype=float)
    ix=np.asarray(indexes,dtype=int)
    result=np.zeros(len(ix),dtype=np.int8)
    if len(a)==0:return result
    t,opening,high,low,close,volume=a.T
    family=params["family"]
    if family not in FAMILIES:raise ValueError("Unknown family")
    n=int(params["lookback"]);level=int(params["level"])
    if n not in (24,48) or level not in (0,1):raise ValueError("Unknown parameters")
    threshold=(0.0005,0.0015)[level]
    for k,i in enumerate(ix):
        if i<n+25 or i>=len(a) or np.any(np.diff(t[i-n:i+1])!=bar_ms):continue
        previous=close[i-n:i]
        mean_vol=max(1.0,float(np.mean(volume[i-n:i])))
        p=close[i];side=0
        if family=="breakout":
            if volume[i]>=mean_vol*(1.2 if level==0 else 1.6):
                if p>np.max(high[i-n:i])*(1+threshold):side=1
                elif p<np.min(low[i-n:i])*(1-threshold):side=-1
        elif family=="momentum":
            move=p/close[i-8]-1;trend=p/close[i-n]-1
            if abs(move)>=(0.002 if level==0 else 0.004) and volume[i]>=mean_vol*1.1:
                if move>0 and trend>0:side=1
                elif move<0 and trend<0:side=-1
        elif family=="mean_reversion":
            avg=float(np.mean(previous));std=float(np.std(previous))
            if std>0 and abs(p/close[i-n]-1)<(0.05 if level==0 else 0.03):
                z=(p-avg)/std
                if z<-(1.5 if level==0 else 2):side=1
                elif z>(1.5 if level==0 else 2):side=-1
        elif family=="trend_pullback":
            short=float(np.mean(close[i-7:i+1]));long=float(np.mean(previous))
            trend=p/close[i-n]-1
            if trend>(0.006 if level==0 else 0.01) and short<long*(1+threshold) and p>long:side=1
            elif trend<-(0.006 if level==0 else 0.01) and short>long*(1-threshold) and p<long:side=-1
        elif family=="volatility_squeeze":
            tiny=float(np.std(np.diff(np.log(close[i-8:i]))))
            wide=float(np.std(np.diff(np.log(previous))))
            if wide>0 and tiny<wide*(0.8 if level==0 else 0.6):
                if p>np.max(high[i-8:i])*(1+threshold):side=1
                elif p<np.min(low[i-8:i])*(1-threshold):side=-1
        elif family=="volume_impulse":
            move=p/opening[i]-1
            if volume[i]>mean_vol*(1.8 if level==0 else 2.5) and abs(move)>threshold:
                side=1 if move>0 else -1
        result[k]=side
    return result
