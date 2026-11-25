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
FAST_VIEW={}
EXPERTS=("stable","adaptive","nonlinear","baseline")

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
def ensemble_init(m):
    if "experts" not in m:
        m["experts"]={}
        for k in EXPERTS:
            dim=DIM*2-1 if k=="nonlinear" else (1 if k=="baseline" else DIM)
            w=np.zeros((2,dim))
            if k=="stable":w[:,:DIM]=np.asarray(m["w"])
            m["experts"][k]={"w":w.tolist(),"n":0,"loss":0.,"slow_loss":0.,"chosen":0,"net":0.}
        m.update(champion="stable",drift=False,drift_count=0,switches=0,stress_net=0.)
    return m["experts"]
def expanded(x,k):
    x=np.asarray(x,float)
    if k=="nonlinear":return np.r_[x,x[1:]*abs(x[1:])]
    if k=="baseline":return x[:1]
    return x
def forecasts(m,x):
    return {k:(np.asarray(e["w"])@expanded(x,k)).tolist() for k,e in ensemble_init(m).items()}
def evaluate_experts(m,p,y):
    experts=ensemble_init(m);y=np.asarray(y,float)
    for k,pred in p.get("forecasts",{}).items():
        if k not in experts:continue
        e=experts[k];z=expanded(p["x"],k);w=np.asarray(e["w"])
        loss=float(np.mean(abs(y-np.asarray(pred))))
        e["n"]+=1;n=e["n"];alpha=max(.06,1/n);slow=max(.008,1/n)
        e["loss"]+=alpha*(loss-e["loss"]);e["slow_loss"]+=slow*(loss-e["slow_loss"])
        # All experts learn the same causal targets; learning rates and basis differ.
        lr={"stable":.045,"adaptive":.28,"nonlinear":.10,"baseline":.08}[k]
        err=np.clip(y-w@z,-50,50)
        e["w"]=(w*.9997+lr*np.outer(err,z)/(1+z@z)).tolist()
        side=0 if p.get("kind")=="spot" else int(pred[1]>pred[0])
        if pred[side]>5:
            e["chosen"]+=1;e["net"]+=float(y[side]-5)/10000
    old=m["champion"];eligible=[k for k in EXPERTS if k!="baseline" and experts[k]["n"]>=30]
    if eligible:
        best=min(eligible,key=lambda k:experts[k]["loss"])
        if old not in eligible or experts[best]["loss"]<.95*experts[old]["loss"]:
            m["champion"]=best;m["switches"]+=int(best!=old)
        e=experts[m["champion"]]
        alert=e["n"]>=60 and e["loss"]>max(.1,e["slow_loss"])*1.5
        m["drift_count"]=min(30,m["drift_count"]+1) if alert else max(0,m["drift_count"]-1)
        m["drift"]=m["drift_count"]>=3
    if p.get("choice"):
        m["stress_net"]+=float(y[0 if p["choice"]==1 else 1]-5)/10000
def settle(m,q,now,fee,slip,horizon=HORIZON,grace=65):
    keep=[]
    for p in m["pending"]:
        age=now-p["time"]
        if age<horizon:keep.append(p);continue
        if age>horizon+grace:continue
        vals=[]
        for side,f in zip((1,-1),p["entries"]):
            exit=paper_exec.fill(q,-side,quantity=f["qty"],slip=slip)
            if not exit:break
            net=side*(exit["price"]/f["price"]-1)-fee*(1+exit["price"]/f["price"])
            vals.append(net*10000)
        if len(vals)==2:
            learn(m,p["x"],p["prediction"],vals,now,p["choice"])
            evaluate_experts(m,p,vals)
        elif age<horizon+max(5,grace-10):keep.append(p)
    m["pending"]=keep
def observe(m,q,now,kind,fee,slip,interval=60,horizon=HORIZON):
    ensemble_init(m)
    settle(m,q,now,fee,slip,horizon,max(15,interval+5))
    minute=int(now//interval)
    if minute<=m["minute"]:return None
    m["minute"]=minute;m["history"]=(m["history"]+[[minute,(q["bid"]+q["ask"])/2]])[-30:]
    x=vector(m["history"],q)
    if x is None:return None
    entries=[paper_exec.fill(q,s,notional=30,slip=slip) for s in (1,-1)]
    if not all(entries):return None
    pred=predict(m,x).tolist()
    fs=forecasts(m,x);experts=m["experts"];champ=m["champion"];cp=fs[champ]
    side=1 if kind=="spot" or cp[0]>=cp[1] else -1
    i=0 if side==1 else 1
    # Model must beat learned cost-only baseline; agreement and stressed edge.
    agrees=sum(fs[k][i]>5 for k in EXPERTS if k!="baseline")
    good=experts[champ]["n"]>=MIN_LABELS and experts[champ]["loss"]<experts["baseline"]["loss"]
    choice=side if good and agrees>=2 and cp[i]>5 and not m["drift"] else 0
    m["pending"].append({"time":now,"x":x,"prediction":pred,"entries":entries,"choice":choice,"forecasts":fs,"kind":kind})
    m["ensemble_prediction"]=cp;m["agreement"]=agrees
    m["predictions"]+=1;m["last_prediction"]=pred;m["choice"]=choice
    return choice
def worker(market,make_position,valuation,costs,model_key,lab_account,spot_universe,fast=False):
    global VIEW,FAST_VIEW
    interval,horizon=(5,60) if fast else (60,HORIZON)
    group="online_fast" if fast else "online_ml"
    dbkey="online_learning_fast_v1" if fast else "online_learning_v1"
    version="fast_v1" if fast else "minute_v1"
    saved=store.get(dbkey,{}) or {};models=saved.get("models",{});accounts=saved.get("accounts",{})
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
                    model={"strategy":{"online":version},"version":"online:"+version} if kind=="linear" else {"model":{"kind":"online","version":2 if fast else 1},"version":"online:"+version}
                    kid=model_key(kind,sym,model);a=accounts.setdefault(kid,lab_account(kind,sym,model,now))
                    m=models.setdefault(key,blank());q=market.scalp_quote(kind,sym)
                    if not q:continue
                    fee,slip=costs(kind)
                    p=a.get("position")
                    if p:
                        price,net,exit_fee,fillable=valuation(p,q)
                        a["equity"]=a["balance"]+net;a["peak"]=max(a["peak"],a["equity"])
                        a["drawdown"]=max(a["drawdown"],1-a["equity"]/a["peak"])
                        if fillable and (p["side"]*(price/p["entry"]-1)<=-risk.STOP or now-p["opened"]>=horizon):
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
                    choice=observe(m,q,now,kind,fee,slip,interval,horizon)
                    if choice and not a.get("position") and a["drawdown"]<.08:
                        league.publish(kid,kind,sym,choice,model,now,now+(8 if fast else 30),horizon,risk.STOP)
                        intents[kid]=(choice,now)
                    rows.append(dict(league.assess(a,now,30),key=kid,market=kind,symbol=sym,family=group))
                except Exception as e:errors[key]=str(e)[:180]
            league.update(group,rows)
            report={}
            for k,m in models.items():
                if tuple(k.split(":",1)) not in active:continue
                report[k]={x:m.get(x) for x in ("labels","predictions","mae","baseline_mae","last_label","last_prediction","choice","selected","selected_net")}
                report[k]["pending"]=len(m["pending"]);report[k]["features"]=DIM
                report[k].update(champion=m.get("champion"),drift=m.get("drift",False),switches=m.get("switches",0),stress_net=m.get("stress_net",0.),ensemble_prediction=m.get("ensemble_prediction"),experts={name:{kk:ee[kk] for kk in ("n","loss","chosen","net")} for name,ee in m.get("experts",{}).items()})
            view={"time":now,"markets":report,"labels":sum(m["labels"] for m in models.values()),
                  "predictions":sum(m["predictions"] for m in models.values()),"closed":sum(a["closed"] for a in accounts.values()),
                  "open":sum(bool(a["position"]) for a in accounts.values()),"errors":errors}
            if fast:FAST_VIEW=view
            else:VIEW=view
            if now-last_save>=60:
                # Bound inactive histories, retain model state for current and recently observed markets.
                keep=sorted(models,key=lambda k:models[k]["minute"],reverse=True)[:48]
                models={k:models[k] for k in keep}
                accounts={k:a for k,a in accounts.items() if a.get("position") or a["kind"]+":"+a["symbol"] in models}
                store.put(dbkey,{"models":models,"accounts":accounts});last_save=now
            if now-last_log>=60:
                logging.info("ONLINE ML mode=%s markets=%s labels=%s predictions=%s paper_open=%s paper_closed=%s switches=%s drift=%s errors=%s",group,len(report),view["labels"],view["predictions"],view["open"],view["closed"],sum(m.get("switches",0) for m in models.values()),sum(bool(m.get("drift")) for m in models.values()),errors)
                last_log=now
        except Exception:logging.exception("Online ML worker error")
        time.sleep(2 if fast else 5)
def selftest():
    m=blank();x=[1.]+[0.]*(DIM-1)
    assert predict(m,x).tolist()==[0.,0.]
    for i in range(80):learn(m,x,predict(m,x).tolist(),[10.,-15.],i)
    assert predict(m,x)[0]>5 and predict(m,x)[1]<-5 and m["labels"]==80
    for i in range(80):
        fs=forecasts(m,x)
        evaluate_experts(m,{"x":x,"forecasts":fs,"kind":"linear","choice":1},[10.,-15.])
    assert forecasts(m,x)["adaptive"][0]>5
    assert m["experts"]["baseline"]["n"]==80
