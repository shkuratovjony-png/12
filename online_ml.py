"""Minute-by-minute online supervised regression. Public data, paper only.
Targets: net return at 15 minutes using observed discounted order books.
Predictions are recorded BEFORE the labels arrive. No random candidate search.
Training targets exclude stop execution; actual paper positions use risk stops.
"""
import time,math,logging
import numpy as np
import paper_exec,league,store,risk
HORIZON=900
DIM=13
MIN_LABELS=30
VIEW={}
def blank():
    return {"w":np.zeros((2,DIM)).tolist(),"labels":0,"mae":0.,"baseline_mae":0.,
            "history":[],"pending":[],"minute":-1,"last_label":0,"predictions":0,
            "selected":0,"selected_net":0.}
def vector(history,q):
    mid=(q["bid"]+q["ask"])/2
    if len(history)<15 or history[-1][0]-history[-15][0]!=14:return None
    c=np.asarray([x[1] for x in history[-15:]],float)
    if np.any(c<=0):return None
    r=np.diff(np.log(c))*1000
    d=q["bid_depth"]+q["ask_depth"];top=q["bid_size"]+q["ask_size"]
    if d<=0 or top<=0:return None
    x=[1.,r[-1],sum(r[-3:]),sum(r[-5:]),sum(r[-14:]),np.std(r),np.mean(abs(r)),
       (q["bid_depth"]-q["ask_depth"])/d,(q["bid_size"]-q["ask_size"])/top,
       (q["ask"]-q["bid"])/mid*1000,(mid/np.mean(c)-1)*1000,
       (mid/max(c)-1)*1000,(mid/min(c)-1)*1000]
    return np.clip(x,-3,3).tolist()
def predict(m,x):
    return np.asarray(m["w"],float)@np.asarray(x,float)
def learn(m,x,pred,y,now,choice=0):
    # Normalized stochastic gradient with bounded gradients and L2 decay.
    x=np.asarray(x,float);y=np.asarray(y,float);p=np.asarray(pred,float)
    w=np.asarray(m["w"],float);err=y-w@x
    w=w*.9995+.12*np.outer(np.clip(err,-50,50),x)/(1+x@x)
    m["w"]=w.tolist();m["labels"]+=1;m["last_label"]=now
    # Prequential metrics: forecast saved at observation, never refitted forecast.
    e=float(np.mean(abs(y-p)));base=float(np.mean(abs(y)))
    alpha=.02 if m["labels"]>50 else 1/m["labels"]
    m["mae"]+=(e-m["mae"])*alpha;m["baseline_mae"]+=(base-m["baseline_mae"])*alpha
    if choice:
        m["selected"]+=1;m["selected_net"]+=float(y[0 if choice==1 else 1])/10000
def settle(m,q,now,fee,slip):
    keep=[]
    for p in m["pending"]:
        age=now-p["time"]
        if age<HORIZON:keep.append(p);continue
        if age>HORIZON+65:continue
        vals=[]
        for side,f in zip((1,-1),p["entries"]):
            exit=paper_exec.fill(q,-side,quantity=f["qty"],slip=slip)
            if not exit:break
            net=side*(exit["price"]/f["price"]-1)-fee*(1+exit["price"]/f["price"])
            vals.append(net*10000)
        if len(vals)==2:learn(m,p["x"],p["prediction"],vals,now,p["choice"])
        elif age<HORIZON+55:keep.append(p)
    m["pending"]=keep
def observe(m,q,now,kind,fee,slip):
    settle(m,q,now,fee,slip)
    minute=int(now//60)
    if minute<=m["minute"]:return None
    m["minute"]=minute;m["history"]=(m["history"]+[[minute,(q["bid"]+q["ask"])/2]])[-30:]
    x=vector(m["history"],q)
    if x is None:return None
    entries=[paper_exec.fill(q,s,notional=30,slip=slip) for s in (1,-1)]
    if not all(entries):return None
    pred=predict(m,x).tolist()
    side=1 if kind=="spot" or pred[0]>=pred[1] else -1
    # Predictions are net bps, with a modest extra buffer. No claim of certainty.
    choice=side if m["labels"]>=MIN_LABELS and pred[0 if side==1 else 1]>5 and m["mae"]<m["baseline_mae"] else 0
    m["pending"].append({"time":now,"x":x,"prediction":pred,"entries":entries,"choice":choice})
    m["predictions"]+=1;m["last_prediction"]=pred;m["choice"]=choice
    return choice
def worker(market,make_position,valuation,costs,model_key,lab_account,spot_universe):
    global VIEW
    saved=store.get("online_learning_v1",{}) or {};models=saved.get("models",{});accounts=saved.get("accounts",{})
    intents={};last_save=0.;last_log=0.;spots=[]
    while True:
        now=time.time();errors={}
        try:
            if now-last_save>=60 or not spots:spots=spot_universe()
            active={(k,s) for k,syms in (("linear",list(market.SYMBOLS)),("spot",spots)) for s in syms}
            active.update((a["kind"],a["symbol"]) for a in accounts.values() if a.get("position"))
            rows=[]
            for kind,sym in sorted(active):
                key=kind+":"+sym
                try:
                    model={"strategy":{"online":"minute_v1"},"version":"online:minute_v1"} if kind=="linear" else {"model":{"kind":"online","version":1},"version":"online:minute_v1"}
                    kid=model_key(kind,sym,model);a=accounts.setdefault(kid,lab_account(kind,sym,model,now))
                    m=models.setdefault(key,blank());q=market.scalp_quote(kind,sym)
                    if not q:continue
                    fee,slip=costs(kind)
                    p=a.get("position")
                    if p:
                        price,net,exit_fee,fillable=valuation(p,q)
                        a["equity"]=a["balance"]+net;a["peak"]=max(a["peak"],a["equity"])
                        a["drawdown"]=max(a["drawdown"],1-a["equity"]/a["peak"])
                        if fillable and (p["side"]*(price/p["entry"]-1)<=-risk.STOP or now-p["opened"]>=HORIZON):
                            pnl=net-p["entry_fee"];a["balance"]+=net;a["equity"]=a["balance"];a["position"]=None
                            a["closed"]+=1;a["wins"]+=int(pnl>0);a["net_sum"]+=pnl/(p["qty"]*p["entry"])
                            league.record(a,pnl/(p["qty"]*p["entry"]),now)
                    pending=intents.get(kid)
                    if pending and now-pending[1]>=paper_exec.LATENCY:
                        intents.pop(kid,None)
                        if now-pending[1]<=30 and not a.get("position") and a["drawdown"]<.08:
                            p=make_position(kind,sym,pending[0],model,q,a["balance"]*.10,now)
                            if p:
                                p["signal_time"]=pending[1];p["latency_seconds"]=now-pending[1]
                                a["position"]=p;a["balance"]-=p["entry_fee"];a["equity"]=a["balance"]
                    choice=observe(m,q,now,kind,fee,slip)
                    if choice and not a.get("position") and a["drawdown"]<.08:
                        league.publish(kid,kind,sym,choice,model,now,now+30,HORIZON,risk.STOP)
                        intents[kid]=(choice,now)
                    rows.append(dict(league.assess(a,now,30),key=kid,market=kind,symbol=sym,family="online_ml"))
                except Exception as e:errors[key]=str(e)[:180]
            league.update("online_ml",rows)
            report={}
            for k,m in models.items():
                if tuple(k.split(":",1)) not in active:continue
                report[k]={x:m.get(x) for x in ("labels","predictions","mae","baseline_mae","last_label","last_prediction","choice","selected","selected_net")}
                report[k]["pending"]=len(m["pending"]);report[k]["features"]=DIM
            VIEW={"time":now,"markets":report,"labels":sum(m["labels"] for m in models.values()),
                  "predictions":sum(m["predictions"] for m in models.values()),"closed":sum(a["closed"] for a in accounts.values()),
                  "open":sum(bool(a["position"]) for a in accounts.values()),"errors":errors}
            if now-last_save>=60:
                # Bound inactive histories, retain model state for current and recently observed markets.
                keep=sorted(models,key=lambda k:models[k]["minute"],reverse=True)[:48]
                models={k:models[k] for k in keep}
                accounts={k:a for k,a in accounts.items() if a.get("position") or a["kind"]+":"+a["symbol"] in models}
                store.put("online_learning_v1",{"models":models,"accounts":accounts});last_save=now
            if now-last_log>=60:
                logging.info("ONLINE ML markets=%s labels=%s predictions=%s paper_open=%s paper_closed=%s errors=%s",len(report),VIEW["labels"],VIEW["predictions"],VIEW["open"],VIEW["closed"],errors)
                last_log=now
        except Exception:logging.exception("Online ML worker error")
        time.sleep(5)
def selftest():
    m=blank();x=[1.]+[0.]*(DIM-1)
    assert predict(m,x).tolist()==[0.,0.]
    for i in range(80):learn(m,x,predict(m,x).tolist(),[10.,-15.],i)
    assert predict(m,x)[0]>5 and predict(m,x)[1]<-5 and m["labels"]==80
