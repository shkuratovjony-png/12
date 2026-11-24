"""Walk-forward starter laboratory: rule search, boosting, chronological gates.
Training uses only closed bars; the final test segment is not used for Optuna.
Daily re-use of rolling data is NOT independent prospective validation.
"""
import os
for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
    os.environ[key]="1"
import sys, time, json, math, base64, pickle, warnings
warnings.filterwarnings("ignore")
import numpy as np
import playbook
from store import get,put,init
from market import BAR,SYMBOLS
from risk import ROUND_TRIP,NOTIONAL_FRACTION,STOP
FEATURES=8

def features(rows):
    a=np.asarray(rows,dtype=float)
    if len(a)<40:return np.empty((0,FEATURES)),np.empty(0),np.empty(0,dtype=int)
    t,o,h,l,c,v=a.T
    X=[];y=[];idx=[]
    for i in range(30,len(a)):
        if np.any(np.diff(t[i-30:i+1])!=BAR):continue
        f=[c[i]/c[i-1]-1,c[i]/c[i-4]-1,c[i]/c[i-12]-1,c[i]/c[i-24]-1,
           c[i]/np.mean(c[i-11:i+1])-1,(h[i]-l[i])/c[i],
           np.std(np.diff(np.log(c[i-12:i+1]))),v[i]/max(1e-9,np.mean(v[i-23:i+1]))-1]
        if not np.all(np.isfinite(f)):continue
        X.append(f);idx.append(i)
        y.append(c[i+1]/o[i+1]-1 if i+1<len(a) and t[i+1]-t[i]==BAR else np.nan)
    return np.array(X),np.array(y),np.array(idx)

def positions(X,p):
    f=X[:,p["feature"]]*p["direction"]
    return np.where(f>p["threshold"],1,np.where(f < -p["threshold"],-1,0))

def model_positions(prob,threshold):
    return np.where(prob>=threshold,1,np.where(prob<=1-threshold,-1,0))

def evaluate(side,ret,stop_touched=None):
    # Conservative worst case when the next bar reaches the stop. Not a tick-level fill model.
    active=side!=0
    gross=side*ret
    if stop_touched is not None:
        gross=np.where(active & stop_touched,-STOP,gross)
    r=np.where(active,(gross-ROUND_TRIP)*NOTIONAL_FRACTION,0)
    curve=np.cumprod(np.r_[1,1+r]); peak=np.maximum.accumulate(curve)
    return {"return":float(curve[-1]-1),"drawdown":float(np.max(1-curve/peak)),
            "trades":int(active.sum()),"win_rate":float((r[active]>0).mean()) if active.any() else 0.0}

def score(m):
    return m["return"]-2*m["drawdown"] if m["trades"]>=20 else -10

def metrics(side, y, rows, idx):
    a=np.asarray(rows,dtype=float)
    n=a[idx+1]
    touched=np.where(side==1,n[:,3]<=n[:,1]*(1-STOP),n[:,2]>=n[:,1]*(1+STOP))
    return evaluate(side,y,touched)

def train(symbol):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rows=get("candles:"+symbol,[])
    X,y,idx=features(rows)
    valid=np.isfinite(y);X,y,idx=X[valid],y[valid],idx[valid]
    if len(y)<800:raise ValueError("Need at least 800 contiguous labeled candles")
    a,b=int(len(y)*.60),int(len(y)*.80)
    trainX,trainY=X[:a-1],y[:a-1]
    valX,valY,vi=X[a:b-1],y[a:b-1],idx[a:b-1]
    testX,testY,ti=X[b:],y[b:],idx[b:]
    def objective(trial):
        p={"feature":trial.suggest_int("feature",0,4),"direction":trial.suggest_categorical("direction",[-1,1]),
           "threshold":trial.suggest_float("threshold",0.0003,0.015,log=True)}
        return score(metrics(positions(valX,p),valY,rows,vi))
    study=optuna.create_study(direction="maximize",sampler=optuna.samplers.TPESampler(seed=17))
    study.optimize(objective,n_trials=24)
    p=study.best_params
    candidates=[(score(metrics(positions(valX,p),valY,rows,vi)),"rule",p,None)]
    reports=[{"name":"rule","validation":metrics(positions(valX,p),valY,rows,vi)}]
    technical=[]
    for hypothesis in playbook.candidates():
        signal=playbook.signals(rows,vi,hypothesis)
        result=metrics(signal,valY,rows,vi)
        candidates.append((score(result),"playbook",hypothesis,None))
        technical.append({"params":hypothesis,"validation":result,"score":score(result)})
    reports.append({"name":"playbook","validation":max(technical,key=lambda x:x["score"])["validation"]})
    from lightgbm import LGBMClassifier
    from catboost import CatBoostClassifier
    for name,model in [("lightgbm",LGBMClassifier(n_estimators=75,max_depth=4,num_leaves=15,n_jobs=1,verbosity=-1,random_state=17)),
                       ("catboost",CatBoostClassifier(iterations=75,depth=4,verbose=False,thread_count=1,random_seed=17,allow_writing_files=False))]:
        try:
            model.fit(trainX,(trainY>0).astype(int))
            prob=model.predict_proba(valX)[:,1]
            best=max([(.53,metrics(model_positions(prob,.53),valY,rows,vi)),
                      (.58,metrics(model_positions(prob,.58),valY,rows,vi)),
                      (.63,metrics(model_positions(prob,.63),valY,rows,vi))],key=lambda v:score(v[1]))
            candidates.append((score(best[1]),name,{"threshold":best[0]},model))
            reports.append({"name":name,"validation":best[1]})
        except Exception as e: reports.append({"name":name,"error":str(e)[:160]})
    _,name,params,model=max(candidates,key=lambda r:r[0])
    v=next(r["validation"] for r in reports if r["name"]==name)
    if name=="playbook":
        side=playbook.signals(rows,ti,params)
    elif model is None:
        side=positions(testX,params)
    else:
        side=model_positions(model.predict_proba(testX)[:,1],params["threshold"])
    test=metrics(side,testY,rows,ti)
    approved=v["return"]>0 and test["return"]>0 and v["trades"]>=20 and test["trades"]>=20 and test["drawdown"]<=.08
    report={"time":time.time(),"symbol":symbol,"rows":len(y),"trial_count":24,"candidates":reports,
            "selected":name,"holdout":test,"approved":bool(approved),"test_from":int(rows[ti[0]][0]),
            "test_to":int(rows[ti[-1]+1][0]),"target_daily":.10,
            "limitations":"15m bar simulation; stop approximated; fees/slippage modeled; not a proof of live profits"}
    report["technical_variants"]=len(technical)
    report["technical_top"]=sorted(technical,key=lambda x:x["score"],reverse=True)[:6]
    report["selected_params"]=params
    put("report:"+symbol,report)
    hist=get("research_history",[])
    put("research_history",(hist+[report])[-90:])
    if approved:
        put("champion:"+symbol,{"name":name,"params":params,"version":str(int(time.time())),
              "model":base64.b64encode(pickle.dumps(model)).decode() if model is not None else None})
    else:
        # Fail closed if most recent review rejects the candidate.
        put("champion:"+symbol,None)
    return report

def signal(symbol):
    ch=get("champion:"+symbol)
    if not ch:return 0
    rows=get("candles:"+symbol,[])
    X,_,idx=features(rows)
    if not len(idx) or idx[-1]!=len(rows)-1:return 0
    x=X[-1:]
    if ch["name"]=="autolab":
        from autolab import prospective_signal
        return prospective_signal(symbol)
    if ch["name"]=="rule":return int(positions(x,ch["params"])[0])
    if ch["name"]=="playbook":return int(playbook.signals(rows,idx[-1:],ch["params"])[0])
    # Only artifacts produced by this private server-side training path are loaded.
    m=pickle.loads(base64.b64decode(ch["model"]))
    return int(model_positions(m.predict_proba(x)[:,1],ch["params"]["threshold"])[0])

if __name__=="__main__":
    init()
    if sys.argv[1]=="train": print(json.dumps(train(sys.argv[2]),allow_nan=False))
    else: print(signal(sys.argv[2]))
