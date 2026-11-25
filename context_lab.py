"""Source-guided, causal market hypotheses. Paper-only; no LLM or external code execution.
Source descriptions are curated hypotheses, not replicated academic results."""
import numpy as np
import pandas as pd
import math,time
import risk
BAR=900000
SOURCES={
 "regime":{"url":"https://doi.org/10.1016/j.frl.2025.108356","title":"State transitions and momentum effect in cryptocurrency market","idea":"Momentum depends on persistence of market state."},
 "micro":{"url":"https://arxiv.org/abs/2602.00776","title":"Explainable Patterns in Cryptocurrency Microstructure","idea":"Order flow, spread and adverse selection may explain short-term returns."},
 "funding":{"url":"https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6872638","title":"Funding Rates and the Conditional Informativeness of Order Flow","idea":"Positioning and reversal channel in commodity-linked perpetuals; transfer to Bybit unverified."},
 "maker":{"url":"https://github.com/hummingbot/hummingbot-site/blob/main/docs/strategies/v1-strategies/avellaneda-market-making.md","title":"Avellaneda market making","idea":"Inventory-sensitive quotes; execution not implemented in this module."},
 "carry":{"url":"https://www.mdpi.com/2227-7390/14/2/346","title":"The Two-Tiered Structure of Cryptocurrency Funding Rate Markets","idea":"Funding spreads may persist due to costs and reversal risks; hedged settlement not implemented here."}
}
IDEAS={
 "trend_pullback":{"source":"regime","why":"Persistent trend with a temporary pullback and renewed buying/selling.","invalid":"Sideways or opposite trend, weak follow-through."},
 "breakout_acceptance":{"source":"regime","why":"Break of prior 24-bar range in established trend with rising volume.","invalid":"Low-volume or countertrend break."},
 "range_rejection":{"source":"micro","why":"Liquidity sweep and close back inside range in a nontrending regime.","invalid":"Strong trend or absence of rejection."},
 "flow_confirmation":{"source":"micro","why":"Price impulse and aggressive order flow agree with established trend.","invalid":"Missing flow observations or opposite flow."},
 "crowded_reversal":{"source":"funding","why":"Crowded directional funding with rejection and opposite short-term impulse.","invalid":"Missing funding or persistent strong trend."}
}
def models(kind):
    return [{"context_id":k,"side":side,"version":1} for k in IDEAS for side in ((1,) if kind=="spot" else (-1,1)) if kind=="linear" or k not in ("crowded_reversal","flow_confirmation")]
def features(a,f,valid):
    n=len(a);c=a[:,4];o=a[:,1];h=a[:,2];l=a[:,3]
    atr=f["atr_ratio"];mom=f["mom24"];ema=f["ema_gap"]
    median=pd.Series(atr).rolling(96,min_periods=48).median().shift(1).to_numpy()
    vol=np.where(atr>median,1,0)
    trend=np.where((mom>2*atr)&(ema>0),1,np.where((mom<-2*atr)&(ema<0),-1,0))
    regime=(trend+1)*2+vol
    hi=pd.Series(h).shift(1).rolling(24,min_periods=24).max().to_numpy()
    lo=pd.Series(l).shift(1).rolling(24,min_periods=24).min().to_numpy()
    ok=valid & np.isfinite(median) & np.isfinite(hi) & np.isfinite(lo)
    return c,o,h,l,atr,trend,regime,hi,lo,ok
def evaluate(model,a,f,valid,kind,ctx=None):
    k=model["context_id"];side=model["side"]
    c,o,h,l,atr,trend,regime,hi,lo,ok=ctx if ctx is not None else features(a,f,valid)
    mom=f["mom4"];body=f["bar_body"];volume=f["vol_ratio"];cost=.0034 if kind=="spot" else .0016
    if k=="trend_pullback":
        raw=(trend==side)&(mom*side<0)&(body*side>0)&(atr>cost)
    elif k=="breakout_acceptance":
        raw=(trend==side)&((c>hi) if side==1 else (c<lo))&(volume>.3)&(atr>cost)
    elif k=="range_rejection":
        raw=(trend==0)&(((l<lo)&(c>lo)) if side==1 else ((h>hi)&(c<hi)))&(body*side>0)&(atr>cost)
    elif k=="flow_confirmation":
        flow=f["taker_delta"];raw=(trend==side)&(flow*side>.15)&(body*side>0)&(atr>cost)
    elif k=="crowded_reversal":
        funding=f["funding"];raw=(trend!= -side)&(funding*side<-.0003)&(body*side>0)&(mom*side<0)&(atr>cost)
    else:raise ValueError("unknown context")
    raw &= ok
    # At decision i, outcome for j=i-1 is known only after i closed. Use
    # j<=i-2 to enforce a full bar lag; no next-bar information in entry.
    # A single historical trade uses next open and close, conservative stop/cost.
    outcome=np.full(len(a),np.nan)
    nxt=a[1:];move=side*(nxt[:,4]/nxt[:,1]-1)
    hit=nxt[:,3]<=nxt[:,1]*(1-risk.STOP) if side==1 else nxt[:,2]>=nxt[:,1]*(1+risk.STOP)
    # Gap at entry and intrabar stops are only approximations, not actual fills.
    move=np.where(hit,-risk.STOP,move)-cost
    outcome[:-1]=np.where(raw[:-1] & (a[1:,0]-a[:-1,0]==BAR),move,np.nan)
    from collections import deque
    memory=[deque() for _ in range(6)];signals=np.zeros(len(a),dtype=np.int8)
    last={"samples":0,"mean_net":0.,"lower_diagnostic":0.,"regime":int(regime[-1]),"raw_signal":bool(raw[-1])}
    for i in range(len(a)):
        j=i-2
        if j>=0 and np.isfinite(outcome[j]):memory[int(regime[j])].append((j,float(outcome[j])))
        q=memory[int(regime[i])]
        while q and q[0][0]<i-960:q.popleft()
        if not raw[i] and i!=len(a)-1:continue
        vals=[x[1] for x in q];n=len(vals);mean=sum(vals)/max(1,n)
        sd=math.sqrt(sum((x-mean)**2 for x in vals)/max(1,n))
        lower=mean-sd/math.sqrt(max(1,n))
        if raw[i] and n>=8 and lower>0:signals[i]=side
        if i==len(a)-1:last={"samples":n,"mean_net":mean,"lower_diagnostic":lower,"regime":int(regime[i]),"raw_signal":bool(raw[i])}
    def stats(ix):
        vals=outcome[ix];vals=vals[np.isfinite(vals)]
        curve=np.cumprod(np.r_[1.,1.+.1*vals])
        return {"trades":len(vals),"net_return":float(curve[-1]-1),"drawdown":float(np.max(1-curve/np.maximum.accumulate(curve))),"mean_net":float(np.mean(vals)) if len(vals) else 0.}
    # Chronological descriptive evaluation, not independently sealed holdout.
    ix=np.flatnonzero(signals[:-1]);cut=int(len(a)*.75)
    last.update(hypothesis=k,side=side,signal=int(signals[-1]),raw_events=int(raw.sum()),validation=stats(ix[ix<cut]),recent_test=stats(ix[ix>=cut]),source=IDEAS[k]["source"])
    return signals,last
def selftest():
    n=120;a=np.column_stack([np.arange(n)*BAR,np.ones(n)*100,np.ones(n)*101,np.ones(n)*99,np.ones(n)*100,np.ones(n)])
    f={k:np.zeros(n) for k in ("mom24","mom4","ema_gap","bar_body","vol_ratio","taker_delta","funding")}
    f["atr_ratio"]=np.full(n,.02)
    s,r=evaluate({"context_id":"trend_pullback","side":1},a,f,np.ones(n,dtype=bool),"linear")
    assert not s.any() and r["samples"]==0
