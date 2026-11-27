"""Range Sweep focused October research. No orders; frozen September risk.
All variants are subsets of the existing causal sweep signal, or change only exit rules.
"""
import json,time
import pandas as pd
import store,impulse_adaptive as a,impulse_holdout as h,impulse_research as old,impulse_daily_risk as dr,impulse_forensics as f
KEY="research:range_sweep_refine:october:v1"
MODELS=("control","hold60","no_breakeven","target125","midpoint","wick_confirm","cost_filter")
def variants(sym,m,ss,rates):
    def exits(signals,hold=6,target=2,trail=1):
        return a.exits(sym,m,signals,rates,hold,target,trail,"switch",end=h.END)
    out={"control":exits(ss),"hold60":exits(ss,12),"no_breakeven":exits(ss,6,2,None),"target125":exits(ss,6,1.25,1),"midpoint":[],"wick_confirm":[],"cost_filter":[]}
    wick=[];cheap=[];diagnosis=[]
    for sig,event in zip(ss,out["control"]):
        i,s,e,stop,d,*_=sig
        # The signal is the preceding closed candle, range excludes that candle.
        b=m.iloc[i-1];prior=m.iloc[i-13:i-1]
        if len(prior)==12:
            mid=(float(prior.high.max())+float(prior.low.min()))/2
            target=s*(mid-e)/d
            if 1<=target<=4:
                out["midpoint"].extend(exits([sig],12,target,None))
        span=float(b.high-b.low)
        if span>0:
            tail=(min(b.open,b.close)-b.low) if s==1 else (b.high-max(b.open,b.close))
            close_loc=(b.close-b.low)/span if s==1 else (b.high-b.close)/span
            if tail/span>=.35 and close_loc>=.65:wick.append(sig)
        # Ex ante friction relative to technical stop, not realized future costs.
        if 2*(a.F+a.SLIP)*e/d<=.08:cheap.append(sig)
        diagnosis.append([event[6]/event[5],*f.excursion(m,sig),s,d/e])
    out["wick_confirm"]=exits(wick)
    out["cost_filter"]=exits(cheap)
    return out,diagnosis
def publish(state):
    results={}
    for k,events in state["events"].items():
        r=dr.replay(events,"profit_lock")
        for t in pd.date_range(h.START,h.END-pd.Timedelta(days=1),freq="D"):
            r["daily"].setdefault(t.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0,"entries":0})
        r["daily"]=dict(sorted(r["daily"].items()))
        r["flat_days"]=sum(v["pnl"]==0 for v in r["daily"].values())
        r["raw"]=f.stats(events)
        results[k]=r
    state["result"]=results;state["diagnosis"]=f.excursion_summary(state["excursions"]);state["updated"]=time.time()
    old.db_put(KEY,state)
    compact={k:{n:v[n] for n in ("balance","roi","dd","trades","wins","positive_days","negative_days","flat_days","fees","funding","raw")} for k,v in results.items()}
    print("RANGE_REFINE_RESULT",json.dumps({"scanned":len(state["scanned"]),"universe":len(state["universe"]),"reused_empty":state["reused_empty"],"complete":state["complete"],"excluded_count":len(state["excluded"]),"diagnosis":state["diagnosis"],"result":compact},default=old.json_number),flush=True)
def run():
    if not store.URL:return
    state=store.get(KEY)
    if not state:
        prev=store.get(f.KEY)
        if not prev:raise RuntimeError("Missing range archive")
        known=prev["events"]["range_sweep"]
        priority=list(dict.fromkeys(e[2] for e in known))
        # All new models are subsets of old sweep candidates, so previously
        # processed symbols with no valid sweep events cannot contribute.
        empty=[sym for sym in prev["scanned"] if sym not in priority]
        archive=f.forensic(known)
        print("RANGE_REFINE_ARCHIVE",json.dumps({"scanned":len(prev["scanned"]),"reused_empty":len(empty),"diagnosis":archive},default=old.json_number),flush=True)
        state={"universe":prev["universe"],"order":list(dict.fromkeys(priority+prev["universe"])),"scanned":empty,"reused_empty":len(empty),"excluded":[x for x in prev["excluded"] if x.split(":")[0] in empty],"events":{k:[] for k in MODELS},"excursions":[],"archive":archive,"archive_scanned":len(prev["scanned"]),"complete":False}
    publish(state)
    if state["complete"]:return
    for sym in state["order"]:
        if sym in state["scanned"]:continue
        hourly=a.window(sym,60,h.START-pd.Timedelta(days=32),h.END)
        if hourly is None:state["excluded"].append(sym+":H1")
        else:
            allowed=a.eligible(hourly,h.START,h.END)
            if allowed:
                m=a.window(sym,5,h.START-pd.Timedelta(minutes=120),h.END+pd.Timedelta(minutes=65))
                if m is None:state["excluded"].append(sym+":M5")
                else:
                    ss=f.signals(hourly,m,allowed,[])["range_sweep"]
                    if ss:
                        rates=h.funding(sym)
                        if not rates:state["excluded"].append(sym+":funding")
                        else:
                            out,diag=variants(sym,m,ss,rates)
                            for k,events in out.items():state["events"][k].extend(events)
                            state["excursions"].extend(diag)
        state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(state["universe"])
        publish(state)
