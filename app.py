"""Always-on bounded autonomous research, paper only; never submits exchange orders."""
import os,time,threading,subprocess,sys,json,logging
from flask import Flask,jsonify,render_template_string
from datetime import datetime,timezone
from waitress import serve
import store,market,risk,market_lab,tick_flow,scalp_lab,paper_exec,league,context_lab,online_ml,replay_lab,bybit_demo,deep_history
app=Flask(__name__)
logging.basicConfig(level=logging.INFO)
STATE={"status":"starting","error":None,"last_poll":None,"training":None,"version":"autonomous-research-v0.21","symbol_errors":{}}
store.init()
if store.get("paper") is None:store.put("paper",risk.initial())

def run_job(mode,symbol):
    script="autolab.py" if mode=="evolve" else "research.py"
    p=subprocess.run([sys.executable,script,mode,symbol],capture_output=True,text=True,timeout=240)
    if p.returncode:raise RuntimeError((p.stderr or p.stdout or "research failed")[-500:])
    return p.stdout.strip().splitlines()[-1]

def record_equity(s):
    # Persist real observations, never invent history. One sample per 5 minutes.
    now=time.time()
    points=store.get("equity_history",[])
    if not points or now-points[-1]["time"]>=300:
        points.append({"time":now,"equity":s["equity"],"balance":s["balance"],
                       "day":s["day"],"day_start":s["day_start"]})
        store.put("equity_history",points[-8640:])


# v0.5: separate spot research, conservative shared account, auditable coordination.
import math
SPOT_FEE=0.0015
SPOT_SLIP=0.0002
TEAM={}
TEAM_LOCK=threading.Lock()
PENDING={}
LEARNING={}
def event(role, task, status="running", **metrics):
    now=time.time()
    with TEAM_LOCK:
        TEAM[role]={"task":task,"status":status,"time":now,**metrics}
        key=(risk.day(),role)
        v=PENDING.setdefault(key,{"events":0,"errors":0,"completed":0,"last":0})
        v["events"]+=1;v["errors"]+=status in ("error","degraded");v["completed"]+=status=="ok";v["last"]=now

def performance(trades):
    returns=[]
    for t in trades:
        try:
            size=float(t["qty"])*float(t["entry"])
            x=float(t["pnl"])/size
            if size>0 and math.isfinite(x):returns.append(x)
        except (KeyError,TypeError,ValueError,ZeroDivisionError):continue
    streak=0
    for x in reversed(returns):
        if x>=0:break
        streak+=1
    n=len(returns)
    return {"trades":n,"avg_net":sum(returns)/max(1,n),"wins":sum(x>0 for x in returns),
            "loss_streak":streak,"weight":n/(n+20)}

def adaptive_profile(s, now):
    trades=[t for t in s.get("trades",[]) if now-30*86400<=t.get("closed",0)<=now]
    by={}
    for kind in ("linear","spot"):
        subset=[t for t in trades if t.get("market","linear")==kind]
        by[kind]=performance(subset)
        for sym in set(t["symbol"] for t in subset if "symbol" in t):
            by[kind+":"+sym]=performance([t for t in subset if t.get("symbol")==sym])
    p=performance(trades)
    scale=1.
    if p["trades"]>=5 and p["avg_net"]<0:scale=.75
    if p["loss_streak"]>=3:scale=min(scale,.5)
    reasons={}
    for t in trades:
        k=t.get("reason","unknown");v=reasons.setdefault(k,{"count":0,"pnl":0.})
        v["count"]+=1;v["pnl"]+=float(t.get("pnl",0))
    return {"time":now,"overall":p,"markets":by,"size_scale":scale,"exit_reasons":reasons,
            "sample_note":"Recent retained closed paper trades only; not live exchange fills."}

def learn_rank(candidate):
    score,kind,sym,side,model=candidate
    groups=LEARNING.get("profile",{}).get("markets",{})
    p=groups.get(kind+":"+sym,{})
    if p.get("trades",0)<5:p=groups.get(kind,{})
    v=model.get("validation",{})
    h=float(score)/max(1,int(v.get("trades",1)))/risk.NOTIONAL_FRACTION
    w=min(.65,p.get("weight",0.)) if p.get("trades",0)>=5 else 0.
    return (1-w)*h+w*p.get("avg_net",0.)

def size_scale():
    return max(.5,min(1.,float(LEARNING.get("profile",{}).get("size_scale",1.))))

def candidate_count(value):
    if isinstance(value,(list,dict)):return len(value)
    if isinstance(value,(int,float)) and math.isfinite(value):return max(0,int(value))
    return 0

def research_history():
    return [dict(x,candidates=candidate_count(x.get("candidates"))) for x in (store.get("research_history",[]) or []) if isinstance(x,dict)]

def learning_worker():
    global LEARNING
    while True:
        pending={}
        try:
            s=store.get("paper",risk.initial())
            now=time.time();profile=adaptive_profile(s,now)
            saved=store.get("team_learning",{}) or {}
            daily=saved.get("daily",{})
            with TEAM_LOCK:
                pending=dict(PENDING);PENDING.clear()
            for (day,role),v in pending.items():
                row=daily.setdefault(day,{}).setdefault(role,{"events":0,"errors":0,"completed":0,"last":0})
                for k in ("events","errors","completed"):row[k]+=v[k]
                row["last"]=max(row["last"],v["last"])
            day=risk.day()
            reports=research_history()
            recent=[x for x in reports if x.get("time",0)>now-86400]
            scout=store.get("team_scout",{}) or {}
            spot=[store.get("spot_report:"+k,{}) or {} for k in spot_universe()]
            history=saved.get("history",{})
            history[day]={"time":now,"equity":s.get("equity"),"profile":profile["overall"],
                "size_scale":profile["size_scale"],"futures_tests_24h":sum(candidate_count(x.get("candidates")) for x in recent),
                "approved_24h":sum(bool(x.get("approved")) for x in recent),
                "spot_tests_24h":sum(candidate_count(x.get("candidates")) for x in spot if x.get("time",0)>now-86400),
                "scout_routes":scout.get("routes_checked"),"scout_time":scout.get("time"),
                "day_return":s.get("equity",risk.START)/max(1e-9,s.get("day_start",risk.START))-1}
            snapshot={"time":now,"profile":profile,"daily":{k:daily[k] for k in sorted(daily)[-90:]},
                      "history":{k:history[k] for k in sorted(history)[-90:]}}
            store.put("team_learning",snapshot)
            LEARNING=snapshot
            logging.info("LEARNING cycle: retained_trades=%s futures_tests_24h=%s spot_tests_24h=%s",profile["overall"]["trades"],history[day]["futures_tests_24h"],history[day]["spot_tests_24h"])
        except Exception:
            with TEAM_LOCK:
                for key,v in pending.items():
                    row=PENDING.setdefault(key,{"events":0,"errors":0,"completed":0,"last":0})
                    for k in ("events","errors","completed"):row[k]+=v[k]
                    row["last"]=max(row["last"],v["last"])
            logging.exception("Team learning cycle failed")
        time.sleep(300)

def training_priority(sym,kind):
    p=LEARNING.get("profile",{}).get("markets",{}).get(kind+":"+sym,{})
    return p.get("avg_net",0.) if p.get("trades",0)>=5 else 0.


def spot_rows(sym, pages=1):
    old={r[0]:r for r in store.get("spot_candles:"+sym,[])}
    now=int(time.time()*1000)
    changed=False
    for row in market.ws_bars("spot",sym):
        if row[0]+market.BAR<=now-2000 and row[0] not in old:old[row[0]]=row;changed=True
    if len(old)>=800 and max(old)>=((now-2000)//market.BAR-1)*market.BAR:
        rows=sorted(old.values(),key=lambda r:r[0])[-3000:]
        if changed:store.put("spot_candles:"+sym,rows)
        return rows
    end=now
    for _ in range(pages):
        raw=market.request("/v5/market/kline",category="spot",symbol=sym,interval="15",
                           limit=1000 if len(old)<800 else 10,end=end)["list"]
        if not raw:break
        for x in raw:
            row=[int(x[0])]+[float(v) for v in x[1:6]]
            if row[0]+market.BAR<=now-2000 and all(math.isfinite(v) and v>0 for v in row[1:5]) and math.isfinite(row[5]) and row[5]>=0:
                old[row[0]]=row
        end=min(int(x[0]) for x in raw)-1
    rows=sorted(old.values(),key=lambda r:r[0])[-3000:]
    if rows:store.put("spot_candles:"+sym,rows)
    return rows

def spot_signal(rows, i, model, features=None):
    if model["kind"]=="technical":
        import autolab
        if features is None:
            if len(rows)<95:return False
            _,f,valid=autolab.indicators(rows)
        else:f,valid=features
        return bool(autolab.signals(model["strategy"],f,valid)[i]==1)
    n=model["lookback"]
    if i<n or rows[i][0]-rows[i-n][0]!=n*market.BAR:return False
    price=rows[i][4]
    if model["kind"]=="momentum":
        move=price/rows[i-n][4]-1
    else:
        mean=sum(r[4] for r in rows[i-n:i])/n
        move=1-price/mean
    return move>model["threshold"]

def spot_signal_live(rows,sym,model):
    if model["kind"]!="technical":return spot_signal(rows,len(rows)-1,model)
    import autolab
    _,f,valid=autolab.indicators(rows,flow=store.get("flow:spot:"+sym,[]))
    return spot_signal(rows,len(rows)-1,model,(f,valid))

def spot_eval(rows, model, start, end, features=None):
    curve=peak=1.; dd=0.; count=wins=0
    signals=None
    if model["kind"]=="technical":
        import autolab
        if features is None:
            _,f,valid=autolab.indicators(rows);features=(f,valid)
        signals=autolab.signals(model["strategy"],*features)
    for i in range(max(start,model.get("lookback",65)),min(end,len(rows)-1)):
        if rows[i+1][0]-rows[i][0]!=market.BAR or not (signals[i]==1 if signals is not None else spot_signal(rows,i,model)):continue
        nxt=rows[i+1]
        entry=nxt[1]*(1+SPOT_SLIP)
        exit_price=min(nxt[4],nxt[1]*(1-risk.STOP)) if nxt[3]<=nxt[1]*(1-risk.STOP) else nxt[4]
        exit_price*=1-SPOT_SLIP
        move=exit_price/entry-1-SPOT_FEE*(1+exit_price/entry)
        curve*=1+move*risk.NOTIONAL_FRACTION
        peak=max(peak,curve); dd=max(dd,1-curve/peak);count+=1;wins+=move>0
    return {"return":curve-1,"drawdown":dd,"trades":count,"win_rate":wins/max(1,count),
            "score":curve-1-2*dd if count>=12 else -100.}

def spot_research(sym):
    rows=spot_rows(sym,3)
    if len(rows)<800:return None
    n=len(rows);a=int(n*.5);b=int(n*.75)
    models=[{"kind":k,"lookback":w,"threshold":t} for k in ("momentum","reversion") for w in (4,12,24,48) for t in (.002,.004,.008,.015)]
    # Preserve the last model and explore bounded mutations as new hypotheses.
    prior=store.get("spot_report:"+sym,{}) or {}
    parent=prior.get("model")
    if isinstance(parent,dict) and parent.get("kind") in ("momentum","reversion"):
        for w in (max(2,parent["lookback"]-2),parent["lookback"],min(96,parent["lookback"]+2)):
            for t in (.8,1.,1.2):
                child={"kind":parent["kind"],"lookback":w,"threshold":round(max(.0005,min(.05,parent["threshold"]*t)),8)}
                if child not in models:models.append(child)
    import autolab
    _,f,valid=autolab.indicators(rows,flow=store.get("flow:spot:"+sym,[]));features=(f,valid)
    train=autolab.np.arange(65,a-2)
    rng=autolab.np.random.default_rng(int(time.time()//86400)+sum(map(ord,sym))*103)
    old=prior.get("technical_archive",[])[:8]
    technical=[]
    for m in old:
        if autolab.validate(m.get("strategy")):
            technical.append(m)
            child=autolab.mutate(m["strategy"],rng,f,train);child["side"]=1
            technical.append({"kind":"technical","strategy":child})
    while len(technical)<48:
        child=autolab.new_candidate(rng,f,train);child["side"]=1
        technical.append({"kind":"technical","strategy":child})
    technical=list({autolab.fingerprint(m["strategy"]):m for m in technical}.values())
    models+=technical
    # Training screen; validation selects exactly one; holdout is not used for selection.
    trained=sorted(models,key=lambda m:spot_eval(rows,m,0,a-2,features)["score"],reverse=True)[:12]
    selected=max(trained,key=lambda m:spot_eval(rows,m,a+2,b-2,features)["score"])
    v=spot_eval(rows,selected,a+2,b-2,features);h=spot_eval(rows,selected,b+2,n-1,features)
    ok=all(x["trades"]>=12 and x["return"]>0 and x["drawdown"]<=.08 for x in (v,h))
    report={"time":time.time(),"symbol":sym,"model":selected,"validation":v,"holdout":h,"approved":ok,"candidates":len(models),
            "note":"Rolling historical test; not independent forward proof."}
    report["technical_archive"]=sorted(technical,key=lambda m:spot_eval(rows,m,a+2,b-2,features)["score"],reverse=True)[:8]
    store.put("spot_report:"+sym,report)
    return report

def spot_quote(sym):
    q=market.request("/v5/market/tickers",category="spot",symbol=sym)["list"][0]
    b,a,bs,az=[float(q[k]) for k in ("bid1Price","ask1Price","bid1Size","ask1Size")]
    if not all(math.isfinite(x) and x>0 for x in (b,a,bs,az)) or b>a:raise ValueError("Invalid spot quote")
    return b,a,bs,az

def spot_entry(s,sym,report):
    if not risk.entry_allowed(s):return False
    b,a,bs,az=spot_quote(sym)
    price=a*(1+SPOT_SLIP);notional=s["balance"]*risk.NOTIONAL_FRACTION*size_scale()
    if notional>az*a or notional>bs*b or (a-b)/a>.002:return False
    fee=notional*SPOT_FEE;s["balance"]-=fee;s["equity"]=s["balance"]
    s["position"]={"symbol":sym,"side":1,"entry":price,"qty":notional/price,"opened":time.time(),
                   "entry_fee":fee,"model":"spot:"+report["model"]["kind"],"market":"spot","spot_model":report["model"]}
    return True

def spot_mark(s):
    p=s["position"];b,a,bs,az=spot_quote(p["symbol"])
    exit_price=b*(1-SPOT_SLIP);gross=p["qty"]*(exit_price-p["entry"]);fee=p["qty"]*exit_price*SPOT_FEE
    equity=s["balance"]+gross-fee;s["equity"]=equity;s["peak"]=max(s["peak"],equity)
    reason=None
    if equity<=s["peak"]*(1-risk.MAX_DRAWDOWN):s["halted"]=True;reason="drawdown"
    elif equity<=s["day_start"]*(1-risk.MAX_DAY_LOSS):reason="daily_loss"
    elif exit_price/p["entry"]-1<=-p.get("stop",risk.STOP):reason="stop_observed"
    elif time.time()-p["opened"]>=risk.HOLD_SECONDS:reason="time_exit"
    if reason:
        if p["qty"]>bs:return # cannot model full liquidation at displayed bid
        s["balance"]=equity
        s["trades"]=(s["trades"]+[dict(p,exit=exit_price,closed=time.time(),pnl=gross-fee-p["entry_fee"],exit_fee=fee,reason=reason,balance=equity)])[-1000:]
        s["position"]=None

SPOT_UNIVERSE=["BTCUSDT","ETHUSDT","SOLUSDT"]
def spot_universe():
    return list(SPOT_UNIVERSE)

def scout_worker():
    while True:
        try:
            event("scout","Поиск рынков, базиса, фандинга и арбитражных цепочек")
            spot={q["symbol"]:q for q in market.request("/v5/market/tickers",category="spot")["list"]}
            ranked,_=market.rank_tickers(list(spot.values()),limit=4)
            if ranked:
                SPOT_UNIVERSE[:]=[s for s,_ in ranked]
                market.set_spot_symbols(SPOT_UNIVERSE)
            linear={q["symbol"]:q for q in market.request("/v5/market/tickers",category="linear")["list"]}
            edges={};assets=("USDT","USDC","BTC","ETH","SOL","XRP","BNB","DOGE","ADA","AVAX","LINK","TON")
            for a in assets:
                for b in assets:
                    if a==b:continue
                    q=spot.get(a+b,{})
                    try:
                        bid,ask,bs,az=[float(q[k]) for k in ("bid1Price","ask1Price","bid1Size","ask1Size")]
                        if not all(math.isfinite(v) and v>0 for v in (bid,ask,bs,az)) or bid>ask:continue
                        edges[a,b]=(bid*(1-SPOT_FEE-SPOT_SLIP),bs)
                        edges[b,a]=((1-SPOT_FEE-SPOT_SLIP)/ask,az*ask)
                    except (ValueError,TypeError,KeyError):continue
            routes=[];checked=0
            def walk(path,amount):
                nonlocal checked
                if len(path)>=3 and (path[-1],"USDT") in edges:
                    rate,cap=edges[path[-1],"USDT"]
                    if amount<=cap:
                        checked+=1
                        routes.append({"path":path+["USDT"],"net_estimate":amount*rate/100-1})
                if len(path)>=5:return
                for nxt in assets:
                    if nxt in path or (path[-1],nxt) not in edges:continue
                    rate,cap=edges[path[-1],nxt]
                    if amount<=cap:walk(path+[nxt],amount*rate)
            walk(["USDT"],100.)
            hedge=[]
            for sym,q in linear.items():
                if sym not in spot:continue
                try:
                    a=float(spot[sym]["ask1Price"]);b=float(q["bid1Price"]);f=float(q["fundingRate"])
                    if not all(math.isfinite(v) for v in (a,b,f)) or min(a,b)<=0:continue
                    hedge.append({"symbol":sym,"basis":b/a-1,"funding_rate":f,
                                  "next_funding":q.get("nextFundingTime"),"entry_cost_estimate":SPOT_FEE+risk.FEE+SPOT_SLIP+risk.SLIPPAGE})
                except (ValueError,TypeError,KeyError):continue
            previous=store.get("scout_memory",{}) or {}
            observations={}
            for route in routes:
                key=">".join(route["path"]);old=previous.get(key,{})
                n=min(100,int(old.get("n",0))+1);weight=1/n
                avg=(1-weight)*old.get("mean",0.)+weight*route["net_estimate"]
                positive=(1-weight)*old.get("positive",0.)+weight*(route["net_estimate"]>0)
                observations[key]={"n":n,"mean":avg,"positive":positive}
                route.update(observations=n,mean_estimate=avg,positive_share=positive)
            store.put("scout_memory",observations)
            result={"time":time.time(),"spot_pairs":len(spot),"linear_pairs":len(linear),"routes_checked":checked,
                    "routes":sorted(routes,key=lambda q:.5*q["net_estimate"]+.5*q["mean_estimate"],reverse=True)[:10],
                    "funding":sorted(hedge,key=lambda q:q["funding_rate"],reverse=True)[:10],
                    "basis":sorted(hedge,key=lambda q:q["basis"],reverse=True)[:10],
                    "note":"Snapshot estimates only; no multi-leg fills, funding settlement or realized P&L."}
            store.put("team_scout",result)
            logging.info("SCOUT cycle: spot_pairs=%s linear_pairs=%s routes=%s",len(spot),len(linear),checked)
            event("scout","Снимок рынков сохранён","ok",routes=checked,spot=len(spot),linear=len(linear))
        except Exception as exc:
            event("scout","Сбой получения котировок","error",error=str(exc)[:180])
        time.sleep(300)

def team_selftest():
    rows=[[i*market.BAR,100.,101.,99.,100.,10.] for i in range(80)]
    assert not spot_signal(rows,50,{"kind":"momentum","lookback":4,"threshold":.002})
    assert spot_eval(rows,{"kind":"reversion","lookback":4,"threshold":.002},0,80)["trades"]==0
    rows[50][4]=101.
    assert spot_signal(rows,50,{"kind":"momentum","lookback":4,"threshold":.002})
    now=time.time()
    losing=[{"qty":1,"entry":100,"pnl":-1,"closed":now,"symbol":"BTCUSDT"} for _ in range(5)]
    assert adaptive_profile({"trades":losing},now)["size_scale"]==.5
    assert adaptive_profile({"trades":[]},now)["size_scale"]==1.
    assert performance(losing)["trades"]==5


# Parallel forward experiments; only observed quotes, never historical fills.
import hashlib
LAB={}
CONTEXT={}
MAX_PORTFOLIO_POSITIONS=6
MAX_EXPOSURE=.75
MAX_POSITION=.125

def model_key(kind,sym,model):
    genome=model.get("strategy") if kind=="linear" else model.get("model")
    raw=json.dumps(genome,sort_keys=True,separators=(",",":"))
    return kind+":"+sym+":"+hashlib.sha256(raw.encode()).hexdigest()[:16]

def book_quote(kind,sym):
    q=market.scalp_quote(kind,sym)
    if not q:raise ValueError("No fresh streaming order book")
    return q

def costs(kind):
    return (SPOT_FEE,SPOT_SLIP) if kind=="spot" else (risk.FEE,risk.SLIPPAGE)

def make_position(kind,sym,side,model,quote,notional,now):
    fee,slip=costs(kind)
    if not quote or (quote["ask"]-quote["bid"])/quote["ask"]>.002 or notional<=0:return None
    f=paper_exec.fill(quote,side,notional=notional,slip=slip)
    if not f:return None
    return {"market":kind,"symbol":sym,"side":side,"entry":f["price"],"qty":f["qty"],"opened":now,
            "entry_fee":f["notional"]*fee,"model":model.get("version",model.get("model",{}).get("kind","spot")),
            "strategy":model.get("strategy"),"spot_model":model.get("model"),
            "strategy_id":model_key(kind,sym,model),"entry_execution":f}

def valuation(p,quote):
    fee,slip=costs(p.get("market","linear"));side=p["side"]
    if p.get("scalp"):slip=paper_exec.BUFFER
    f=paper_exec.fill(quote,-side,quantity=p["qty"],slip=slip)
    price=f["price"] if f else (quote["bid"] if side==1 else quote["ask"])*(1-side*slip)
    gross=side*p["qty"]*(price-p["entry"]);exit_fee=p["qty"]*price*fee
    return price,gross-exit_fee,exit_fee,f is not None

def normalize_portfolio(s):
    if "positions" not in s:
        s["positions"]=[s["position"]] if s.get("position") else []
    s["position"]=s["positions"][0] if s["positions"] else None
    return s

def exposure(s):
    return sum(p["qty"]*p["entry"] for p in s["positions"])

def portfolio_allowed(s):
    risk.roll(s)
    e=s["equity"]
    if e<=s["peak"]*(1-risk.MAX_DRAWDOWN):s["halted"]=True
    return (not s["halted"] and e>s["day_start"]*(1-risk.MAX_DAY_LOSS)
            and len(s["positions"])<MAX_PORTFOLIO_POSITIONS and exposure(s)<max(0,e)*MAX_EXPOSURE)

def portfolio_mark(s,failures):
    normalize_portfolio(s);now=time.time();marks=[];total=0.
    for p in s["positions"]:
        try:
            quote=book_quote(p.get("market","linear"),p["symbol"])
            price,net,fee,fillable=valuation(p,quote)
            p["last_net"]=net;p["mark_time"]=now
            marks.append((p,price,net,fee,fillable));total+=net
        except Exception as exc:
            failures["position:"+p["symbol"]]=str(exc)[:150]
            total+=p.get("last_net",0.)
            marks.append((p,None,0.,0.,False))
    # Do not admit new trades or claim fresh marks when a quote is missing.
    s["equity"]=s["balance"]+total
    complete=all(m[1] is not None and m[4] for m in marks)
    if complete:s["peak"]=max(s["peak"],s["equity"])
    emergency=None
    if s["equity"]<=s["peak"]*(1-risk.MAX_DRAWDOWN):s["halted"]=True;emergency="drawdown"
    elif s["equity"]<=s["day_start"]*(1-risk.MAX_DAY_LOSS):emergency="daily_loss"
    keep=[]
    for p,price,net,fee,fillable in marks:
        reason=emergency or p.get("exit_requested")
        if price is not None:
            if not reason and p["side"]*(price/p["entry"]-1)<=-p.get("stop",risk.STOP):reason="stop_observed"
            if not reason and now-p["opened"]>=p.get("hold",risk.HOLD_SECONDS):reason="time_exit"
        if reason:p["exit_requested"]=reason
        if reason and fillable:
            s["balance"]+=net
            logging.info("PORTFOLIO CLOSE tier=%s symbol=%s pnl=%.6f reason=%s",p.get("admission_tier","legacy"),p["symbol"],net-p["entry_fee"],reason)
            s["trades"]=(s["trades"]+[dict(p,exit=price,closed=now,pnl=net-p["entry_fee"],
                        exit_fee=fee,reason=reason,balance=s["balance"])])[-1000:]
        else:keep.append(p)
    s["positions"]=keep;s["position"]=keep[0] if keep else None
    return complete

def portfolio_entry(s,intent):
    kind,sym,side,model=(intent[k] for k in ("kind","symbol","side","model"))
    if not portfolio_allowed(s) or any(p["symbol"]==sym for p in s["positions"]):return False
    cap=min(s["balance"],s["equity"])
    practice=intent.get("tier")=="practice"
    if practice:
        if model.get("scalp") or sum(p.get("admission_tier")=="practice" for p in s["positions"])>=3:return False
        if any(t.get("strategy_id")==intent["key"] and t.get("pnl",0)<0 and time.time()-t.get("closed",0)<3600 for t in s["trades"]):return False
    # Scale new notional with current capital, including retained realized profits.
    amount=min(cap*min(MAX_POSITION,intent.get("allocation",.025))*size_scale(),cap*MAX_EXPOSURE-exposure(s))
    if model.get("scalp"):amount=min(amount,cap*.10)
    if amount<10:return False
    now=time.time()
    if now>intent["expires"] or now-intent["time"]<paper_exec.LATENCY:return False
    quote=book_quote(kind,sym)
    if model.get("scalp"):
        if (quote["ask"]-quote["bid"])/quote["ask"]>.002:return False
        f=paper_exec.fill(quote,side,notional=amount)
        if not f:return False
        p={"market":kind,"symbol":sym,"side":side,"entry":f["price"],"qty":f["qty"],"opened":now,
           "entry_fee":f["notional"]*scalp_lab.fee(kind),"model":"scalp:"+model["config"][0],"scalp":True,"config":model["config"],"entry_execution":f}
    else:p=make_position(kind,sym,side,model,quote,amount,now)
    if not p:return False
    p.update(research_evidence=bool(intent.get("research_evidence") or intent.get("tier")!="practice"),admission_tier=intent.get("tier","trial"),strategy_id=intent["key"],hold=intent["hold"],stop=intent["stop"],signal_time=intent["time"],latency_seconds=now-intent["time"])
    s["balance"]-=p["entry_fee"];s["equity"]-=p["entry_fee"]
    s["positions"].append(p);s["position"]=s["positions"][0]
    logging.info("PORTFOLIO OPEN tier=%s symbol=%s side=%s notional=%.4f strategy=%s",p["admission_tier"],sym,side,p["qty"]*p["entry"],intent["key"])
    return True

def lab_tick(account,kind,sym,model,side,bar,quote,now,submitted=None):
    p=account.get("position")
    if p:
        price,net,fee,fillable=valuation(p,quote)
        account["equity"]=account["balance"]+net
        account["peak"]=max(account["peak"],account["equity"])
        account["drawdown"]=max(account["drawdown"],1-account["equity"]/account["peak"])
        stop=p["side"]*(price/p["entry"]-1)<=-risk.STOP
        if fillable and (stop or now-p["opened"]>=risk.HOLD_SECONDS):
            pnl=net-p["entry_fee"];account["balance"]+=net
            account["equity"]=account["balance"];account["position"]=None
            account["closed"]+=1;account["wins"]+=pnl>0
            account["net_sum"]+=pnl/(p["qty"]*p["entry"])
            if p.get("entry_execution"):league.record(account,pnl/(p["qty"]*p["entry"]),now)
            account["last_trade"]={"time":now,"pnl":pnl,"entry":p["entry"],"exit":price}
    if bar and bar>account.get("last_bar",0):
        account["last_bar"]=bar
        if side and not account.get("position") and account["balance"]>10 and account["drawdown"]<.15 and 0<=now*1000-(bar+market.BAR)<=120000:
            p=make_position(kind,sym,side,model,quote,account["balance"]*.25,now)
            if p:
                p["signal_time"]=submitted;p["latency_seconds"]=now-submitted if submitted else None
                account["balance"]-=p["entry_fee"];account["equity"]=account["balance"];account["position"]=p
    return account

def lab_account(kind,sym,model,now):
    return {"kind":kind,"symbol":sym,"model":model,"created":now,"balance":1000.,"equity":1000.,
            "peak":1000.,"drawdown":0.,"position":None,"closed":0,"wins":0,"net_sum":0.,"last_bar":0}

def lab_worker():
    global LAB
    import autolab
    while True:
        try:
            saved=store.get("forward_lab",{}) or {}
            accounts=saved.get("accounts",{})
            now=time.time();active=set();errors={};historical={}
            for kind,symbols in (("linear",list(market.SYMBOLS)),("spot",spot_universe())):
                # Continue marking retired models with open positions even if removed from the universe.
                symbols=list(dict.fromkeys(symbols+[a["symbol"] for a in accounts.values() if a["kind"]==kind and a.get("position")]))
                for sym in symbols:
                    try:
                        if kind=="linear":
                            archive=store.get("autolab:"+sym,{}).get("archive",[])[:10]
                            models=[{"strategy":x["strategy"],"version":x.get("id","archive")} for x in archive if autolab.validate(x.get("strategy"))]
                            champion=store.get("champion:"+sym)
                            if champion:
                                models.append(champion)
                                v=champion.get("validation",{});h=champion.get("holdout",{})
                                if all(x.get("trades",0)>=8 and x.get("return",0)>0 and x.get("drawdown",1)<=.08 for x in (v,h)):
                                    historical[model_key(kind,sym,champion)]=min(v["return"]/v["trades"],h["return"]/h["trades"])
                            models.extend({"strategy":x["strategy"],"version":x.get("id","explore")} for x in (store.get("explore:"+sym,{}) or {}).get("top",[]) if autolab.validate(x.get("strategy")))
                            rows=store.get("candles:"+sym,[])
                        else:
                            models=[{"model":{"kind":k,"lookback":w,"threshold":t}} for k in ("momentum","reversion") for w in (4,12,24,48) for t in (.002,.004,.008,.015)]
                            report=store.get("spot_report:"+sym)
                            if report:
                                models.append(report)
                                models.extend({"model":m} for m in report.get("technical_archive",[])[:8])
                            rows=spot_rows(sym) if sym in spot_universe() else store.get("spot_candles:"+sym,[])
                        # Source-guided hypotheses stay in the experiment even when random archives rotate.
                        if kind=="linear":models.extend({"strategy":m,"version":"knowledge:"+m["context_id"]} for m in context_lab.models(kind))
                        else:models.extend({"model":{"kind":"context",**m},"version":"knowledge:"+m["context_id"]} for m in context_lab.models(kind))
                        if kind=="linear":models.append({"strategy":{"pooled_replay":1},"version":"pooled_replay_v1"})
                        else:models.append({"model":{"kind":"pooled_replay","version":1},"version":"pooled_replay_v1"})
                        # Retain strongest qualified prior versions even when research archive rotates.
                        veterans=[a for a in accounts.values() if a["kind"]==kind and a["symbol"]==sym and league.assess(a,now,30)["eligible"]]
                        veterans.sort(key=lambda a:league.assess(a,now,30)["score"],reverse=True)
                        models.extend(a["model"] for a in veterans[:2])
                        models={model_key(kind,sym,m):m for m in models}
                        active.update(models)
                        missing=[key for key in models if key not in accounts]
                        archived=store.get_many(["forward_archive:"+key for key in missing])
                        for key in missing:accounts[key]=archived.get("forward_archive:"+key) or lab_account(kind,sym,models[key],now)
                        keys=[k for k,a in accounts.items() if a["kind"]==kind and a["symbol"]==sym and (k in models or a.get("position"))]
                        if not keys:continue
                        bar=rows[-1][0] if rows else 0
                        fresh=0<=time.time()*1000-(bar+market.BAR)<=120000
                        needs=[k for k in keys if k in models and fresh and bar>accounts[k].get("last_bar",0)]
                        signals={}
                        if needs and kind=="linear" and len(rows)>=100:
                            a,f,valid=autolab.indicators(rows,store.get("micro:"+sym,[]),store.get("flow:linear:"+sym,[]))
                            ctx=context_lab.features(a,f,valid)
                            reports=[]
                            for k in needs:
                                genome=models[k]["strategy"]
                                if genome.get("pooled_replay"):signals[k]=replay_lab.signal(rows,kind,sym)
                                elif genome.get("context_id"):
                                    sig,report=context_lab.evaluate(genome,a,f,valid,kind,ctx);signals[k]=int(sig[-1]);reports.append(report)
                                else:signals[k]=int(autolab.signals(genome,f,valid)[-1])
                            if reports:CONTEXT[kind+":"+sym]={"time":time.time(),"reports":reports}
                        elif needs and kind=="spot":
                            features=None
                            if len(rows)>=95 and any(models[k]["model"].get("kind") in ("technical","context") for k in needs):
                                a,f,valid=autolab.indicators(rows,flow=store.get("flow:spot:"+sym,[]));features=(f,valid);ctx=context_lab.features(a,f,valid)
                            reports=[]
                            for k in needs:
                                genome=models[k]["model"]
                                if genome.get("kind")=="pooled_replay":signals[k]=replay_lab.signal(rows,kind,sym)
                                elif genome.get("kind")=="context":
                                    if features is not None:
                                        sig,report=context_lab.evaluate(genome,a,f,valid,kind,ctx);signals[k]=int(sig[-1]);reports.append(report)
                                else:signals[k]=int(spot_signal(rows,len(rows)-1,genome,features))
                            if reports:CONTEXT[kind+":"+sym]={"time":time.time(),"reports":reports}
                        if not signals and not any(accounts[k].get("position") for k in keys):continue
                        submitted=time.time()
                        for k,side in signals.items():
                            if side in (-1,1):league.publish(k,kind,sym,side,models[k],submitted,(bar+market.BAR)/1000+120,risk.HOLD_SECONDS,risk.STOP)
                        if any(signals.values()):time.sleep(paper_exec.LATENCY)
                        quote=book_quote(kind,sym);observed=time.time()
                        for k in keys:
                            acc=accounts[k]
                            lab_tick(acc,kind,sym,acc["model"],signals.get(k,0),bar if k in signals else 0,quote,observed,submitted)
                    except Exception as exc:errors[kind+":"+sym]=str(exc)[:180]
            # Keep active and open accounts; bound the number of retired closed accounts.
            retired=[k for k,a in accounts.items() if k not in active and not a.get("position")]
            retired.sort(key=lambda k:accounts[k]["created"],reverse=True)
            archive={k:accounts.pop(k) for k in retired[256:]}
            snapshot={"time":time.time(),"accounts":accounts,"active":sorted(active),"errors":errors}
            store.save_forward(snapshot,archive);LAB=snapshot
            if CONTEXT:store.put("context_research",dict(CONTEXT))
            logging.info("KNOWLEDGE cycle: markets=%s hypotheses=%s signals=%s",len(CONTEXT),sum(len(v["reports"]) for v in CONTEXT.values()),sum(r["signal"]!=0 for v in CONTEXT.values() for r in v["reports"]))
            ranked=[]
            for k in active:
                if k not in accounts:continue
                a=accounts[k];e=league.assess(a,snapshot["time"],30)
                hist=historical.get(k,0.)
                # The pooled model has explicit chronological tests, and its signal is separately gated.
                pooled=a["model"].get("strategy",{}).get("pooled_replay") or a["model"].get("model",{}).get("kind")=="pooled_replay"
                if pooled:
                    m=replay_lab.approved_model(a["kind"],a["symbol"])
                    if m:hist=min(m["validation"]["1"]["mean_net"],m["test"]["1"]["mean_net"])
                prior=hist>0 and a.get("net_sum",0)>=0 and e["drawdown"]<=.02 and e["net"]>=0
                ranked.append(dict(e,key=k,market=a["kind"],symbol=a["symbol"],family="swing",historical=prior,historical_score=hist if prior else 0.))
            league.update("forward",ranked)
            logging.info("FORWARD cycle: active=%s open=%s closed=%s errors=%s",len(active),sum(bool(a.get("position")) for a in accounts.values()),sum(a["closed"] for a in accounts.values()),json.dumps(errors,ensure_ascii=False)[:1200])
            event("tester","Параллельная проверка на новых котировках","degraded" if errors else "ok",accounts=len(accounts),active=len(active))
        except Exception:
            logging.exception("Forward lab error")
        time.sleep(45)

def lab_evidence(kind,sym,model):
    a=LAB.get("accounts",{}).get(model_key(kind,sym,model),{})
    n=a.get("closed",0)
    return n>=10 and a.get("net_sum",0)>0 and a.get("drawdown",1)<=.08

def lab_summary():
    accounts=LAB.get("accounts",{});active=set(LAB.get("active",[]))
    rows=[{"key":k,"market":a["kind"],"symbol":a["symbol"],"equity":a["equity"],
           "closed":a["closed"],"wins":a["wins"],"drawdown":a["drawdown"],
           "open":bool(a.get("position")),"active":k in active,"avg_net":a["net_sum"]/max(1,a["closed"])}
          for k,a in accounts.items()]
    breakdown={}
    for kind in ("linear","spot"):
        group=[x for x in rows if x["market"]==kind];live=[x for x in group if x["active"]]
        tested=[x for x in group if x["closed"]>0]
        breakdown[kind]={"active":len(live),"accounts":len(group),"closed":sum(x["closed"] for x in group),"open":sum(x["open"] for x in group),"positive_models":sum(x["avg_net"]>0 for x in tested),"tested_models":len(tested),"top":sorted(tested,key=lambda x:(x["closed"]>=10,x["avg_net"]),reverse=True)[:5],"symbols":sorted({x["symbol"] for x in live})}
    return {"time":LAB.get("time"),"breakdown":breakdown,"active":len(active),"accounts":len(rows),
            "open":sum(x["open"] for x in rows),"closed":sum(x["closed"] for x in rows),
            "eligible":sum(x["closed"]>=10 and x["avg_net"]>0 and x["drawdown"]<=.08 for x in rows),
            "rows":sorted(rows,key=lambda x:(x["active"],x["closed"],x["equity"]),reverse=True),
            "errors":LAB.get("errors",{}),"execution":"fresh streaming 50-level book; depth haircut 50%; latency >=1s for new entries"}

def market_worker():
    retry={}
    while True:
        failures={}
        try:
            active=market.load_universe()
            for sym in active:
                if retry.get(sym,(0,0))[0]>time.time():continue
                try:
                    old=store.get("candles:"+sym,[])
                    if market.candles(sym,3 if len(old)<800 else 1):retry.pop(sym,None)
                except Exception as exc:
                    failures[sym]=str(exc)[:150]
                    n=min(5,retry.get(sym,(0,0))[1]+1);retry[sym]=(time.time()+min(900,30*2**n),n)
            event("analyst","Обновление реальных свечей","ok" if not failures else "degraded",symbols=len(active))
            logging.info("MARKET feed: symbols=%s errors=%s feed=%s",len(active),failures,market.feed_status())
        except Exception:logging.exception("Market data worker error")
        time.sleep(45)

def portfolio_worker():
    global PAPER_VIEW
    # Sole writer of main virtual portfolio; research threads never mutate it.
    s=normalize_portfolio(store.get("paper",risk.initial()))
    seen=dict(s.get("league_seen",{}));last_save=last_log=0.;prev_leaders={}
    while True:
        now=time.time();failures={}
        try:
            risk.roll(s)
            market.pin_positions(s["positions"])
            before=(len(s["trades"]),len(s["positions"]),s["balance"],s["halted"])
            complete=portfolio_mark(s,failures)
            view=league.snapshot(now,league.blocked(s["trades"],now))
            leaders={r["symbol"]:r["key"] for r in view["leaders"]}
            if leaders!=prev_leaders:
                logging.info("LEAGUE leadership changed: %s",leaders);prev_leaders=leaders
            for intent in view["signals"]:
                if not complete or not portfolio_allowed(s):break
                key=intent["key"];stamp=intent["time"]
                if now-stamp<paper_exec.LATENCY or stamp<=seen.get(key,0):continue
                try:
                    if portfolio_entry(s,intent):seen[key]=stamp
                except Exception as exc:failures["entry:"+intent["symbol"]]=str(exc)[:150]
            seen={k:t for k,t in seen.items() if now-t<180}
            PAPER_VIEW={k:s[k] for k in ("balance","equity","peak","day","day_start","halted")}
            PAPER_VIEW.update(time=now,start=risk.START,target_daily=risk.TARGET_DAILY,positions=len(s["positions"]))
            changed=before!=(len(s["trades"]),len(s["positions"]),s["balance"],s["halted"])
            if changed or now-last_save>=15:
                s["league_leaders"]=leaders;s["league_seen"]=seen
                store.put("paper",s);last_save=now
            if now-last_log>=60:
                record_equity(s)
                event("manager","Лига стратегий: независимые эксперименты и отбор","ok",qualified=view["qualified"],leaders=len(leaders))
                event("trader","Единый портфель, без лимита прибыли","ok",positions=len(s["positions"]))
                event("risk","Контроль убытков","ok" if complete else "degraded",halted=s["halted"])
                logging.info("LEAGUE cycle: evaluated=%s qualified=%s leaders=%s positions=%s equity=%.4f errors=%s practice_signals=%s practice_open=%s portfolio_closed=%s",view["evaluated"],view["qualified"],len(leaders),len(s["positions"]),s["equity"],failures,view["practice_signals"],sum(p.get("admission_tier")=="practice" for p in s["positions"]),len(s["trades"]))
                last_log=now
            STATE.update(status="degraded" if failures else "running",error=None,symbol_errors=failures,last_poll=now)
        except Exception as exc:
            logging.exception("Portfolio worker error")
            STATE.update(status="degraded",error=str(exc)[:180],last_poll=now)
        time.sleep(1)

EXPLORER={}
def explore_worker():
    # Extra exploration on each newly closed bar, no admission and no holdout reuse.
    # One symbol per pass keeps the paid small instance within its CPU budget.
    global EXPLORER
    import autolab
    cursor=0
    while True:
        try:
            syms=list(market.SYMBOLS)
            if syms:
                sym=syms[cursor%len(syms)];cursor+=1
                rows=store.get("candles:"+sym,[]) or []
                previous=store.get("explore:"+sym,{}) or {}
                if len(rows)>=800 and rows[-1][0]>previous.get("bar",0):
                    a,f,valid=autolab.indicators(rows,store.get("micro:"+sym,[]) or [],store.get("flow:linear:"+sym,[]))
                    n=len(a);train=autolab.np.arange(autolab.LOOKBACK,int(n*.5)-2)
                    validation=autolab.np.arange(int(n*.5)+2,int(n*.75)-2)
                    if valid[train].sum()>200 and valid[validation].sum()>100:
                        rng=autolab.np.random.default_rng(int(rows[-1][0]//market.BAR)+sum(map(ord,sym))*103)
                        parents=(store.get("autolab:"+sym,{}) or {}).get("archive",[])[:6]
                        parents=[p["strategy"] for p in parents if autolab.validate(p.get("strategy"))]
                        pool=[autolab.mutate(p,rng,f,train) for p in parents]
                        while len(pool)<24:pool.append(autolab.new_candidate(rng,f,train))
                        tested={}
                        for model in pool:
                            key=autolab.fingerprint(model)
                            if key not in tested:tested[key]={"strategy":model,"id":key,"validation":autolab.summarize(model,a,f,valid,validation)}
                        top=sorted(tested.values(),key=lambda x:x["validation"]["score"],reverse=True)[:3]
                        result={"time":time.time(),"bar":rows[-1][0],"symbol":sym,"tested":len(tested),"total":previous.get("total",0)+len(tested),"top":top}
                        store.put("explore:"+sym,result)
                        EXPLORER=result
                        logging.info("EXPLORE cycle: symbol=%s tested=%s lifetime=%s best_validation=%s",sym,len(tested),result["total"],top[0]["validation"] if top else None)
        except Exception:
            logging.exception("Continuous exploration error")
        time.sleep(75)

def trainer_worker():
    attempts={}
    while True:
        try:
            # Dedicated process keeps risk polling responsive.
            for sym in sorted(list(market.SYMBOLS),key=lambda x:training_priority(x,"linear")):
                now=time.time()
                brain=store.get("autolab:"+sym,{})
                if now-brain.get("last_cycle",0)<86400 or now-attempts.get(sym,0)<3600:continue
                if len(store.get("candles:"+sym,[]))<800:continue
                attempts[sym]=now
                STATE["training"]=sym
                event("strategist","Генерация и мутация гипотез: "+sym)
                event("tester","Историческая проверка: "+sym)
                try:
                    outcome=json.loads(run_job("evolve",sym))
                    logging.info("TRAIN cycle: symbol=%s candidates=%s approved=%s",sym,candidate_count(outcome.get("candidates")),outcome.get("approved"))
                    event("strategist","Гипотезы проверены: "+sym,"ok",candidates=outcome.get("candidates"))
                    event("tester","Проверка завершена: "+sym,"ok",approved=outcome.get("approved"))
                    store.put("last_training_result",{"symbol":sym,"time":time.time(),
                        "selected":outcome.get("selected"),"approved":outcome.get("approved"),
                        "generation":outcome.get("generation"),"candidates":outcome.get("candidates"),
                        "validation":outcome.get("validation"),"holdout":outcome.get("holdout")})
                except Exception as exc:
                    event("tester","Ошибка проверки: "+sym,"error",error=str(exc)[:180])
                    logging.exception("Training failed for %s",sym)
                    store.put("last_training_result",{"symbol":sym,"time":time.time(),
                        "error":type(exc).__name__+": "+str(exc)[-200:]})
                finally:
                    STATE["training"]=None
                time.sleep(25)
        except Exception:
            logging.exception("Training scheduler error")
            STATE["training"]=None
        time.sleep(180)

def spot_trainer_worker():
    attempts={}
    while True:
        for sym in sorted(spot_universe(),key=lambda x:training_priority(x,"spot")):
            try:
                old=store.get("spot_report:"+sym,{})
                if time.time()-old.get("time",0)<86400 or time.time()-attempts.get(sym,0)<3600:continue
                attempts[sym]=time.time()
                event("spot_research","Проверка спотовых гипотез: "+sym)
                report=spot_research(sym)
                logging.info("SPOT TRAIN cycle: symbol=%s candidates=%s approved=%s",sym,report.get("candidates",0) if report else 0,report.get("approved") if report else None)
                event("spot_research","Проверка спота завершена: "+sym if report else "Недостаточно истории: "+sym,"ok" if report else "waiting",approved=report.get("approved") if report else None)
            except Exception as exc:event("spot_research","Ошибка спотового исследования: "+sym,"error",error=str(exc)[:180])
            time.sleep(10)
        time.sleep(180)

@app.get("/health")
def health():return {"service":"smart-trader-ai","mode":"paper","status":STATE["status"]}

# The web request path does not wait for database reads or market research.
DASH_JSON=None
DASH_TIME=0.
DASH_ERROR=None
PAPER_VIEW=None
def build_dashboard():
    symbols=list(market.SYMBOLS);spots=spot_universe()
    keys=["paper","equity_history","team_scout","research_universe","micro_status","arb_scan","last_training_result","research_history"]
    keys += ["spot_report:"+k for k in spots]
    keys += [prefix+k for k in symbols for prefix in ("candles:","micro:","autolab:","report:","champion:")]
    d=store.get_many(keys)
    s=normalize_portfolio(d.get("paper") or risk.initial());risk.roll(s)
    history=[dict(x,candidates=candidate_count(x.get("candidates"))) for x in (d.get("research_history") or []) if isinstance(x,dict)]
    return dict(mode="PAPER + BYBIT DEMO",bybit_demo=bybit_demo.VIEW,target_daily=risk.TARGET_DAILY,start=risk.START,day=s["day"],day_start=s["day_start"],
        equity_history=(d.get("equity_history") or [])[-8640:],storage="postgres" if store.URL else "ephemeral_sqlite",
        replay=replay_lab.VIEW,online_ml=online_ml.VIEW,online_fast=online_ml.FAST_VIEW,knowledge={"sources":context_lab.SOURCES,"ideas":context_lab.IDEAS,"markets":dict(CONTEXT)},competition=league.snapshot(excluded=league.blocked(s["trades"],time.time())),feature_count=24+len(market_lab.TECH)+len(market_lab.FLOW),
        flow=tick_flow.status(),scalp=scalp_lab.status(),feed=market.feed_status(),team=dict(TEAM),learning=LEARNING,exploration=EXPLORER,
        scout=d.get("team_scout"),spot_reports=[d["spot_report:"+k] for k in spots if d.get("spot_report:"+k)],universe=d.get("research_universe",{}),
        micro_status=d.get("micro_status"),arbitrage=d.get("arb_scan"),latest_training=d.get("last_training_result"),recent_research=history,
        state=dict(STATE),balance=s["balance"],equity=s["equity"],peak=s["peak"],halted=s["halted"],position=s["position"],positions=s["positions"],
        portfolio_exposure=exposure(s),forward_lab=lab_summary(),trades=s["trades"],
        symbols=[{"symbol":k,"bars":len(d.get("candles:"+k,[])),"micro_bars":len(d.get("micro:"+k,[])),
        "brain":{key:value for key,value in d.get("autolab:"+k,{}).items() if key!="archive"},"report":d.get("report:"+k),
        "champion":d.get("champion:"+k),"latest_micro":(d.get("micro:"+k) or [None])[-1]} for k in symbols],
        snapshot_time=time.time())
def dashboard_worker():
    global DASH_JSON,DASH_TIME,DASH_ERROR
    while True:
        try:
            t=time.monotonic();view=build_dashboard()
            payload=json.dumps(view,ensure_ascii=False,allow_nan=False,separators=(",",":"))
            DASH_JSON=payload;DASH_TIME=view["snapshot_time"];DASH_ERROR=None
            logging.info("DASHBOARD snapshot ready bytes=%s seconds=%.2f",len(payload),time.monotonic()-t)
        except Exception as exc:
            DASH_ERROR=str(exc)[:160];logging.exception("Dashboard snapshot failed")
        time.sleep(30)
@app.get("/api/status")
def status():
    payload=DASH_JSON
    if payload is None:return jsonify(error=DASH_ERROR or "Initial snapshot not ready"),503
    return app.response_class(payload,mimetype="application/json",headers={"Cache-Control":"no-store","X-Snapshot-Age":str(round(time.time()-DASH_TIME))})

@app.get("/api/demo")
def demo_status():return jsonify(**bybit_demo.VIEW,deep_history=deep_history.VIEW)

@app.get("/api/overview")
def overview():
    s=PAPER_VIEW
    if s is None:return jsonify(error="Portfolio starting"),503
    return jsonify(**s,state=dict(STATE),snapshot_time=s["time"])

PAGE=r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SMART TRADER AI — кабинет</title>
<style>
:root{color-scheme:dark;--bg:#0b1019;--card:#141e2b;--line:#28384b;--text:#edf4fb;--muted:#98a9bf;--up:#53e0ae;--down:#ff8a98;--blue:#78aaff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}main{max-width:1280px;margin:auto;padding:22px}header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}h1{font-size:24px;margin:0}h2{font-size:17px;margin:0 0 14px}h3{font-size:15px;margin:0 0 8px}p{margin:8px 0}small,.muted{color:var(--muted)}.tag{font-size:11px;letter-spacing:.08em;background:#193a35;color:var(--up);padding:6px 10px;border-radius:20px}nav{display:flex;gap:8px;overflow:auto;margin:22px 0}nav a{padding:9px 13px;border:1px solid var(--line);border-radius:8px;color:var(--text);text-decoration:none;white-space:nowrap}section,.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:17px;margin-bottom:14px}section{scroll-margin-top:10px}.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.tile{margin:0}.metric{font-size:clamp(18px,3vw,31px);font-weight:700;font-variant-numeric:tabular-nums;margin-top:8px;overflow-wrap:anywhere}.up{color:var(--up)}.down{color:var(--down)}.split{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-top:14px}.bar{height:10px;border-radius:8px;background:#263447;overflow:hidden;margin:14px 0}.bar div{height:100%;background:var(--up);width:0}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left;font-variant-numeric:tabular-nums}th,td{padding:11px 9px;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}th{color:var(--muted);font-weight:500}td.wrap{white-space:normal;min-width:180px}.empty{padding:20px;color:var(--muted);text-align:center}button,select{background:#1d2b3e;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit}.chart{width:100%;height:220px;display:block}.subgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.model{padding:13px;border:1px solid var(--line);border-radius:9px;overflow-wrap:anywhere}.pill{font-size:12px;background:#27384b;padding:4px 7px;border-radius:5px;display:inline-block;margin:3px}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}.warn{color:#ffd18a}.chartnote{min-height:20px}footer{color:var(--muted);font-size:12px;padding-bottom:20px}@media(max-width:760px){main{padding:13px}.tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.tile,section{padding:12px}.split,.subgrid{grid-template-columns:1fr}.metric{font-size:23px}.chart{height:190px}}
</style></head><body><main>
<header><div><h1>SMART TRADER AI</h1><p class="muted">Лаборатория автономной торговли · Bybit</p></div><div><span class="tag">PAPER + BYBIT DEMO</span><p id="health" class="muted">Получение данных…</p></div></header>
<nav><a href="#overview">Обзор</a><a href="#trading">Сделки</a><a href="#lab">Стратегии</a><a href="#learning">Развитие</a><a href="#market">Рынок</a><a href="#team">Команда</a><a href="#forward">Практика</a><a href="#scalp">Скальпинг</a><a href="#league">Лига</a></nav>
<section><h2>Bybit Demo · отдельный биржевой счёт</h2><div id="demoState">Подключение…</div><div id="deepHistory" class="muted"></div><small>Лимит капитала 1000 USDT; только демонстрационные фьючерсы. Локальный портфель ниже — отдельная симуляция.</small></section><section><h2>Состояние рабочих процессов</h2><div id="runtime"></div><small>Последнее успешное обновление и ошибки; работа веб-сервера не означает работу обучения.</small></section><div id="overview" class="tiles">
<div class="tile"><small>Капитал сейчас</small><div class="metric" id="equity">—</div><small id="total">Старт: 1 000 USDT</small></div>
<div class="tile"><small>Баланс без переоценки</small><div class="metric" id="balance">—</div><small>USDT · виртуальный</small></div>
<div class="tile"><small>Результат сегодня (UTC)</small><div class="metric" id="daily">—</div><small id="daypct">—</small></div>
<div class="tile"><small>Закрытые сделки сегодня</small><div class="metric" id="tradecount">—</div><small id="wins">—</small></div>
</div><div class="split">
<section><div class="toolbar"><h2>Динамика капитала</h2><select id="period"><option value="1">24 часа</option><option value="7">7 дней</option><option value="30">30 дней</option></select></div><svg id="equityChart" class="chart" viewBox="0 0 650 220" preserveAspectRatio="none"></svg><small id="chartNote" class="chartnote">Только сохранённые наблюдения</small></section>
<section><h2>Дневная цель · 10%</h2><div class="metric" id="goal">—</div><small id="target">—</small><div class="bar"><div id="progress"></div></div><p id="remaining">—</p><small>Исследовательский ориентир, не гарантия. Лимит дневного убытка 3%, максимальная просадка 15%.</small><p id="riskstate"></p></section></div>
<section id="league"><h2>Лига стратегий · конкуренция за капитал</h2><div id="leagueStats">—</div><div id="leagueRows"></div><small>Только чистые результаты новых практических сделок. Учебный режим: до 3 пробных позиций, до 3% капитала на каждую, свежий сигнал без накопленного чистого убытка. Подтверждённые стратегии: 2,5–10%. Цель 10% не останавливает торговлю; прибыль остаётся в капитале.</small></section><section id="replay"><h2>Коллективное обучение на истории</h2><div id="replayStats">Ожидание исторического обучения…</div><small>15-минутные свечи, глобальное разделение по времени, альтернативные выходы 15/60/240 минут. Не тиковый симулятор. Повторные исторические проверки не независимы.</small></section><section id="onlineML"><h2>Онлайн-машинное обучение</h2><div id="onlineStats">Ожидание данных…</div><div id="onlineRows"></div><small>Прогнозы на 60 секунд и 15 минут; три обучаемых модели и контрольная модель, конкурентный отбор и обнаружение дрейфа. Веса обновляются только после наступления результата. Ошибка прогноза измеряется до обучения. Все сделки виртуальные.</small></section><section id="knowledge"><h2>База знаний и рыночный контекст</h2><div id="knowledgeStats">Загрузка исследований…</div><div id="knowledgeRows"></div><small>Источники отобраны вручную; модели проверяют гипотезы, а не гарантируют прибыль. Исторические свечи не заменяют реальное исполнение.</small></section><section id="activity"><h2>Что робот делает сейчас</h2><div id="activityStats">Получение статистики…</div><div id="directionStats" class="subgrid"></div><small>Эксперименты не являются сделками основного портфеля. Нулевое число допущенных моделей означает, что фильтр рисков не разрешил вход.</small></section><section id="trading"><h2>Открытые позиции основного портфеля</h2><div id="position">—</div><div id="portfolioPositions"></div><h2 style="margin-top:20px">История виртуальных сделок</h2><div class="toolbar"><small id="tradesNote"></small><select id="tradeperiod"><option value="today">Сегодня UTC</option><option value="all">Все сохранённые</option></select></div><div class="scroll"><table><thead><tr><th>Вход / выход</th><th>Пара</th><th>Сторона</th><th>Вход</th><th>Выход</th><th>Комиссии*</th><th>Чистый P&L</th><th>Стратегия / причина выхода</th></tr></thead><tbody id="trades"></tbody></table></div><small>* Модельные комиссии; проскальзывание включено в цены. Фандинг пока не начисляется.</small></section>
<section id="lab"><h2>Лаборатория стратегий</h2><div id="labstats" class="tiles"></div><p id="training" class="muted"></p><div id="models" class="subgrid"></div><small>Историческая проверка не подтверждает будущую прибыль. Допуск означает лишь право на виртуальную сделку.</small></section>
<section id="learning"><h2>История обучения по дням</h2><svg id="learnChart" class="chart" viewBox="0 0 650 220" preserveAspectRatio="none"></svg><div class="scroll"><table><thead><tr><th>Дата UTC</th><th>Эксперименты</th><th>Циклы</th><th>Допуски</th><th>Отклонения</th></tr></thead><tbody id="learnrows"></tbody></table></div><small>Количество экспериментов — активность, а не показатель интеллекта. Качество сравниваем с результатами на новых данных.</small></section>
<section id="market"><h2>Данные Bybit</h2><p id="marketstatus"></p><div class="scroll"><table><thead><tr><th>Пара</th><th>Свечи 15м</th><th>Снимки</th><th>Фандинг</th><th>Дисбаланс стакана</th><th>Дельта сделок</th><th>Обновлено</th></tr></thead><tbody id="markets"></tbody></table></div><h2 style="margin-top:20px">Треугольный арбитраж · наблюдение</h2><div id="arbs"></div></section>
<section id="team"><h2>Команда и направления</h2><p class="muted">Программные роли, фактические задачи и отметки времени. Не отдельные языковые модели.</p><div id="teamcards" class="subgrid"></div><h2 style="margin-top:20px">Накопительная память команды</h2><div id="teamlearning"></div><h2 style="margin-top:20px">Спот · независимые проверки</h2><div id="spotreports"></div><h2 style="margin-top:20px">Новые ниши · наблюдение</h2><div id="scout"></div></section><section id="forward"><h2>Параллельная практика на новых котировках</h2><div id="forwardStats"></div><div class="scroll"><table><thead><tr><th>Стратегия</th><th>Рынок</th><th>Баланс</th><th>Закрыто</th><th>Средний net</th><th>Просадка</th><th>Статус</th></tr></thead><tbody id="forwardRows"></tbody></table></div><small>Каждая модель имеет отдельные 1 000 виртуальных USDT. Эти деньги и результаты не суммируются с главным портфелем. Допуск в главный портфель: историческая проверка плюс минимум 10 закрытых тестовых сделок, положительный результат и просадка до 8%. Не гарантия будущей прибыли.</small></section><section id="scalp"><h2>Скальпинг и микроструктура рынка</h2><div id="scalpStats"></div><div id="scalpFamilies"></div><div id="scalpTop"></div><small>Изолированные виртуальные счета. Исполнение по свежим котировкам после задержки, пассивное — только по последующей сделке сквозь цену. Не доказательство реального исполнения.</small></section><footer>Данные из рабочей базы SMART TRADER AI. Обновление каждые 30 секунд. Время сделок — локальное время устройства, торговые сутки — UTC. Панель только для чтения, без приватных ключей и реальных ордеров.</footer>
<script>
let data=null;const el=id=>document.getElementById(id);const fmt=(x,n=2)=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toLocaleString('ru-RU',{minimumFractionDigits:n,maximumFractionDigits:n});const money=x=>fmt(x)+' USDT';const pct=x=>x==null?'—':fmt(x*100)+'%';const dt=t=>t?new Date(t*1000).toLocaleString('ru-RU'):'—';const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const col=x=>x>0?'up':x<0?'down':'';const signed=x=>(x>0?'+':'')+fmt(x);const utc=t=>new Date(t*1000).toISOString().slice(0,10);const side=x=>x===1?'LONG':'SHORT';
const names={mom4:'Импульс 1ч',mom12:'Импульс 3ч',mom24:'Импульс 6ч',ema_gap:'Разница EMA',rsi:'RSI',boll_z:'Bollinger Z',vol_ratio:'Объём',atr_ratio:'ATR',book_imbalance:'Дисбаланс стакана',taker_delta:'Дельта агрессивных сделок',funding:'Фандинг',oi_change:'Изменение OI',liq_long:'Ликвидации LONG',liq_short:'Ликвидации SHORT',spot_basis:'Базис спот/фьючерс',basis:'Базис mark/index'};
function strategy(s){return s?.all?.length?s.all.map(p=>esc(names[p.feature]||p.feature)+' × '+esc(p.direction)+' > '+fmt(p.threshold,6)).join('<br>'):'Условия не сохранены';}
function rows(id,arr,empty,span){el(id).innerHTML=arr.length?arr.join(''):'<tr><td colspan="'+span+'" class="empty">'+esc(empty)+'</td></tr>'}
function value(id,x,text){el(id).textContent=text;el(id).className='metric '+col(x)}
function plot(id,points,baseline,bar=false){const svg=el(id);if(!points.length){svg.innerHTML='<text x="325" y="110" fill="#98a9bf" text-anchor="middle">Пока недостаточно данных</text>';return;}const W=650,H=220,L=65,R=15,T=15,B=32;const vals=points.map(p=>p.y);let lo=Math.min(...vals,baseline??Infinity),hi=Math.max(...vals,baseline??-Infinity);if(hi-lo<.01){lo-=1;hi+=1}const pad=(hi-lo)*.08;lo-=pad;hi+=pad;const x=i=>L+(W-L-R)*(points.length===1?.5:i/(points.length-1));const y=v=>T+(H-T-B)*(hi-v)/(hi-lo);let h='';for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4;h+='<line x1="'+L+'" y1="'+y(v)+'" x2="'+(W-R)+'" y2="'+y(v)+'" stroke="#28384b"/><text x="'+(L-6)+'" y="'+(y(v)+4)+'" font-size="11" text-anchor="end" fill="#98a9bf">'+fmt(v,bar?0:2)+'</text>'}if(bar){const bw=Math.min(28,(W-L-R)/Math.max(points.length,1)*.65);points.forEach((p,i)=>{h+='<rect x="'+(x(i)-bw/2)+'" y="'+y(p.y)+'" width="'+bw+'" height="'+Math.max(0,y(0)-y(p.y))+'" rx="3" fill="#78aaff"><title>'+esc(p.label)+': '+fmt(p.y,0)+'</title></rect>'})}else{if(points.length>1)h+='<polyline fill="none" stroke="#53e0ae" stroke-width="2.5" points="'+points.map((p,i)=>x(i)+','+y(p.y)).join(' ')+'"/>';points.forEach((p,i)=>{h+='<circle cx="'+x(i)+'" cy="'+y(p.y)+'" r="'+(points.length<80?3:1.5)+'" fill="#53e0ae"><title>'+esc(p.label)+': '+fmt(p.y)+'</title></circle>'})}h+='<text x="'+L+'" y="210" fill="#98a9bf" font-size="11">'+esc(points[0].short)+'</text><text x="'+(W-R)+'" y="210" text-anchor="end" fill="#98a9bf" font-size="11">'+esc(points.at(-1).short)+'</text>';svg.innerHTML=h}
function draw(){if(!data)return;const j=data, cutoff=Date.now()/1000-Number(el('period').value)*86400;let points=(j.equity_history||[]).filter(p=>p.time>=cutoff).map(p=>({y:p.equity,label:dt(p.time),short:new Date(p.time*1000).toLocaleDateString('ru-RU')}));if(j.state.last_poll)points.push({y:j.equity,label:dt(j.state.last_poll),short:'Сейчас'});plot('equityChart',points,null);el('chartNote').textContent='Наблюдений: '+points.length+' · исторические значения до запуска панели не восстановлены';const all=j.trades||[],today=all.filter(t=>utc(t.closed)===j.day);const ts=el('tradeperiod').value==='today'?today:all;el('tradesNote').textContent='Показано '+Math.min(ts.length,200)+' из '+ts.length;rows('trades',ts.slice(-200).reverse().map(t=>'<tr><td>'+esc(dt(t.opened))+'<br>'+esc(dt(t.closed))+'</td><td>'+esc(t.symbol)+' · '+esc(t.market||'linear')+'</td><td>'+side(t.side)+'</td><td>'+fmt(t.entry,6)+'</td><td>'+fmt(t.exit,6)+'</td><td>'+fmt((t.entry_fee||0)+(t.exit_fee??t.qty*t.exit*.0006),4)+'</td><td class="'+col(t.pnl)+'">'+signed(t.pnl)+'</td><td class="wrap">'+strategy(t.strategy)+'<br><small>'+esc(t.model)+' · '+esc(({time_exit:'Выход по времени',stop_observed:'Стоп',drawdown:'Просадка',daily_loss:'Дневной лимит'})[t.reason]||t.reason)+'</small></td></tr>'),'Закрытых сделок пока нет',8)}
function renderDirections(j){const f=j.forward_lab||{},s=j.scalp||{},sc=j.scout||{},e=j.exploration||{},l=j.learning||{},g=j.competition||{};const out=[];for(const [k,label] of [["linear","Фьючерсы"],["spot","Спот"]]){const x=f.breakdown?.[k]||{};const tests=k==="linear"?l.history?.[j.day]?.futures_tests_24h:l.history?.[j.day]?.spot_tests_24h;const qualified=(g.leaders||[]).filter(a=>a.market===k&&a.family==="swing").length;out.push("<div class=\"model\"><h3>"+label+"</h3><p>Моделей: "+(x.active??"—")+" · открыто: "+(x.open??"—")+" · закрыто: "+(x.closed??"—")+"</p><p>Чистый плюс: "+(x.positive_models??"—")+" из "+(x.tested_models??"—")+" проверенных · лидеров: "+qualified+"</p><p>Исторических тестов за 24ч: "+(tests??"—")+"</p><small>"+esc((x.symbols||[]).join(", "))+"</small>"+(x.top||[]).map(t=>"<p>"+esc(t.symbol)+" · "+t.closed+" сделок · средний net "+pct(t.avg_net)+"</p>").join("")+"<small>Практика: "+dt(f.time)+"</small></div>")}out.push("<div class=\"model\"><h3>Скальпинг</h3><p>"+(s.active_models??s.models??"—")+" активных моделей · "+(s.closed??"—")+" закрыто</p><p>Чистый плюс: "+(s.depth_evidence?.positive_models??"—")+" · поколение "+(s.generation??"—")+"</p><small>"+dt(s.time)+"</small></div>");out.push("<div class=\"model\"><h3>Арбитраж</h3><p>Сканирование: "+(sc.routes_checked??"—")+" цепочек</p><p>Виртуальное исполнение ещё не реализовано.</p><small>"+dt(sc.time)+"</small></div>");out.push("<div class=\"model\"><h3>Фандинг и базис</h3><p>Сбор рыночных ставок и разницы цен.</p><p>Начисления и хеджированные сделки ещё не реализованы.</p><small>"+dt(sc.time)+"</small></div>");out.push("<div class=\"model\"><h3>Маркетмейкинг</h3><p>Пассивные эксперименты: "+(s.families?.passive?.closed??"—")+" закрыто.</p><p>Полноценная двусторонняя стратегия ещё не реализована.</p></div>");el("directionStats").innerHTML=out.join("")}function render(j){data=j;el("replayStats").innerHTML=Object.entries(j.replay||{}).map(([k,r])=>"<p><b>"+esc(k)+"</b> · рынков "+r.symbols+" · примеров "+r.rows+" · признаков "+r.features+" · "+(r.approved?"Допуск к paper-проверке":"Исторический допуск не пройден")+"</p>"+Object.entries(r.test||{}).map(([h,m])=>"<p>"+(Number(h)*15)+" мин · "+m.trades+" проверок · средняя чистая доходность "+pct(m.mean_net)+" · положительных рынков "+m.positive_symbols+"</p>").join("")).join("")||"Ожидание данных";const ml=j.online_ml||{},fast=j.online_fast||{};el("onlineStats").textContent="15 мин: прогнозов "+(ml.predictions||0)+" · изучено "+(ml.labels||0)+" | 60 сек: прогнозов "+(fast.predictions||0)+" · изучено "+(fast.labels||0)+" · виртуальных закрытий "+((ml.closed||0)+(fast.closed||0));el("onlineRows").innerHTML=[[ml,"15 мин"],[fast,"60 сек"]].map(([m,h])=>"<h3>"+h+"</h3>"+Object.entries(m.markets||{}).map(([sym,r])=>"<p><b>"+esc(sym)+"</b> · исходов "+r.labels+" · лидер "+esc(r.champion||"—")+" · смен "+(r.switches||0)+" · "+(r.drift?"Дрейф: пауза":"Обычный режим")+" · "+(r.choice?"сигнал":"нет сигнала")+" · "+Object.entries(r.experts||{}).map(([k,e])=>esc(k)+": "+Number(e.loss||0).toFixed(2)+" б.п.").join(" | ")+"</p>").join("")).join("");const kn=j.knowledge||{},mk=Object.entries(kn.markets||{});el("knowledgeStats").textContent="Источников: "+Object.keys(kn.sources||{}).length+" · рынков с проверками: "+mk.length+" · гипотез: "+Object.keys(kn.ideas||{}).length;el("knowledgeRows").innerHTML=Object.entries(kn.ideas||{}).map(([id,x])=>"<div class=\"model\"><h3>"+esc(id)+"</h3><p>"+esc(x.why)+"</p><small>"+esc(x.invalid)+" · "+esc(kn.sources?.[x.source]?.title)+"</small></div>").join("")+mk.map(([sym,v])=>"<p><b>"+esc(sym)+"</b> · "+esc(dt(v.time))+" · "+(v.reports||[]).map(r=>esc(r.hypothesis)+": "+r.samples+" похожих ситуаций, net "+pct(r.mean_net)+(r.signal?" · сигнал":"")).join(" | ")+"</p>").join("");try{renderDirections(j)}catch(e){el("directionStats").textContent="Ошибка статистики направлений: "+e.message}const sc=j.scalp||{}, ev=sc.depth_evidence||{},fw=j.forward_lab||{},lc=j.competition||{};el("activityStats").innerHTML="<p>Скальпинг: <b>"+fmt(sc.closed,0)+"</b> закрыто · "+fmt(sc.open,0)+" открыто · поколение "+(sc.generation||0)+"</p><p>Активных моделей: "+(sc.active_models??sc.models??0)+" · отсеяно: "+(sc.retired_models||0)+"</p><p>Спот и фьючерсы: "+(fw.closed||0)+" закрыто · "+(fw.open||0)+" открыто</p><p>Скальпинг с чистым плюсом: "+(ev.positive_models||0)+" · допущено в портфель: "+(lc.qualified||0)+"</p><p>"+((lc.qualified||0)===0?"Учебный режим: свежие сигналы спот/фьючерсов допускаются без ожидания серии сделок, если нет накопленного чистого убытка.":"Есть допущенные стратегии; ожидание сигнала и проверка риска.")+"</p><small>Снимок: "+esc(dt(j.snapshot_time))+"</small>";const lg=j.competition||{};el("leagueStats").textContent="Моделей: "+(lg.evaluated||0)+" · квалифицировано: "+(lg.qualified||0)+" · лидеров: "+(lg.leaders||[]).length+" · учебных сигналов: "+(lg.practice_signals??0);el("leagueRows").innerHTML=(lg.leaders||[]).map(x=>"<p>"+esc(x.symbol)+" · "+esc(x.market)+" · "+esc(x.family)+" · "+x.trades+" сделок · "+x.days+" дней · оценка "+pct(x.score)+" · допуск "+pct(x.allocation)+"</p>").join("")||"<p>Пока нет моделей, прошедших независимый отбор.</p>";renderRuntime(j);try{renderScalp(j)}catch(e){el("scalpStats").textContent=e.message}try{renderForward(j)}catch(e){el("forwardStats").textContent="Ошибка отображения практики: "+e.message}try{renderTeam(j)}catch(e){el("teamlearning").textContent="Ошибка отображения команды: "+e.message}const e=j.equity, d=e-j.day_start, ret=d/j.day_start, today=(j.trades||[]).filter(t=>utc(t.closed)===j.day);value('equity',e-j.start,money(e));value('balance',0,money(j.balance));el('total').textContent='С начала: '+signed(e-j.start)+' USDT ('+pct(e/j.start-1)+')';value('daily',d,signed(d)+' USDT');el('daypct').textContent=pct(ret)+' · '+j.day;el('tradecount').textContent=today.length;el('wins').textContent=today.filter(t=>t.pnl>0).length+' прибыльных / '+today.filter(t=>t.pnl<0).length+' убыточных';value('goal',ret,pct(ret));el('target').textContent='Целевой капитал: '+money(j.day_start*(1+j.target_daily));el('remaining').textContent='До цели: '+money(Math.max(0,j.day_start*(1+j.target_daily)-e));el('progress').style.width=Math.max(0,Math.min(100,ret/j.target_daily*100))+'%';el('riskstate').textContent=(j.halted?'Торговля остановлена контролёром':'Контроль риска активен')+' · просадка '+pct(1-e/j.peak);el('health').textContent=j.state.version+' · '+({running:'работает',starting:'запуск',degraded:'сбой данных'})[j.state.status]+' · '+dt(j.state.last_poll);const p=j.position;el('position').innerHTML=p?'<div class="model"><h3>'+esc(p.symbol)+' · '+esc(p.market||'linear')+' · '+side(p.side)+'</h3><p>Открыта '+esc(dt(p.opened))+' · вход '+fmt(p.entry,6)+' · номинал '+money(p.qty*p.entry)+'</p><p>Текущая переоценка: <strong class="'+col(e-j.balance)+'">'+signed(e-j.balance)+' USDT</strong></p><small>Условия входа</small><p>'+strategy(p.strategy)+'</p></div>':'<div class="empty">Открытых позиций нет</div>';const sy=j.symbols||[], hist=j.recent_research||[];const total=sy.reduce((a,s)=>a+(s.brain?.total_tested||0),0), approved=sy.filter(s=>s.champion).length;el('labstats').innerHTML=[['Инструменты',sy.length],['Проверено (активные пары)',total],['Допущено моделей',approved],['Признаков в коде',j.feature_count??54]].map(([k,v])=>'<div class="tile"><small>'+esc(k)+'</small><div class="metric">'+v+'</div></div>').join('');el('training').textContent=j.state.training?'Сейчас обучается: '+j.state.training:'Последний цикл: '+(j.latest_training?.symbol||'—')+' · '+dt(j.latest_training?.time)+(j.latest_training?.error?' · '+j.latest_training.error:'');el('models').innerHTML=sy.map(s=>{const r=s.report||{},c=s.champion,b=s.brain||{};return '<div class="model"><h3>'+esc(s.symbol)+' <span class="pill">'+(c?'Допущена':r.time?'Не допущена':'Нет теста')+'</span></h3><small>Поколение '+(b.generation||0)+' · экспериментов '+(b.total_tested||0)+' · доступных признаков '+(r.eligible_features?.length??'—')+'</small><p>Validation: <b class="'+col(r.validation?.return)+'">'+pct(r.validation?.return)+'</b> · Holdout: <b class="'+col(r.holdout?.return)+'">'+pct(r.holdout?.return)+'</b></p><small>Просадка holdout '+pct(r.holdout?.drawdown)+' · сделок '+(r.holdout?.trades??'—')+'</small><p>'+strategy(c?.strategy||r.selected_params)+'</p><small>Последний тест '+esc(dt(r.time))+'</small></div>'}).join('');const days={};hist.forEach(r=>{if(!r.time)return;const k=utc(r.time),v=days[k]||{n:0,c:0,a:0};v.n+=r.candidates||0;v.c++;v.a+=r.approved?1:0;days[k]=v});const ds=Object.entries(days).sort((a,b)=>a[0].localeCompare(b[0]));plot('learnChart',ds.slice(-30).map(([k,v])=>({y:v.n,label:k,short:k.slice(5)})),0,true);rows('learnrows',ds.reverse().map(([k,v])=>'<tr><td>'+k+'</td><td>'+v.n+'</td><td>'+v.c+'</td><td>'+v.a+'</td><td>'+(v.c-v.a)+'</td></tr>'),'Пока нет завершённых циклов',5);const m=j.micro_status;el('marketstatus').textContent='Хранилище: '+j.storage+' · ликвидации WebSocket: '+(m?.liquidation_stream?.connected?'подключён':'не подтверждён')+' · сбор: '+dt(m?.time)+(m?.errors&&Object.keys(m.errors).length?' · ошибки: '+JSON.stringify(m.errors):'');rows('markets',sy.map(s=>{const q=s.latest_micro||{};return '<tr><td>'+esc(s.symbol)+'</td><td>'+s.bars+'</td><td>'+s.micro_bars+'</td><td>'+pct(q.funding)+'</td><td>'+pct(q.book_imbalance)+'</td><td>'+pct(q.taker_delta)+'</td><td>'+esc(dt(q.observed/1000))+'</td></tr>'}),'Нет данных',7);el('arbs').innerHTML=(j.arbitrage?.routes||[]).map(r=>'<p>'+esc(r.path.join(' → '))+' <b class="'+col(r.net_estimate)+'">'+pct(r.net_estimate)+'</b></p>').join('')||'<p class="muted">Нет сохранённых маршрутов</p>';draw()}
function renderTeam(j){renderLearning(j);const labels={manager:'Управляющий',analyst:'Аналитик',strategist:'Стратег',tester:'Тестировщик',risk:'Риск-менеджер',optimizer:'Оптимизатор',capital:'Капитал',trader:'Трейдер',scout:'Исследователь ниш',spot_research:'Спотовая лаборатория'};el('teamcards').innerHTML=Object.entries(labels).map(([k,n])=>{const t=j.team?.[k];return '<div class="model"><h3>'+esc(n)+'</h3><p>'+esc(t?.task||'Нет подтверждённого цикла')+'</p><small>'+esc(t?.status||'waiting')+' · '+esc(dt(t?.time))+'</small>'+(t?.error?'<p class="warn">'+esc(t.error)+'</p>':'')+'</div>'}).join('');el('spotreports').innerHTML=(j.spot_reports||[]).map(r=>'<div class="model"><b>'+esc(r.symbol)+'</b> · '+(r.approved?'Допущена':'Отклонена')+' · '+esc(r.model.kind)+' · '+esc(r.candidates)+' гипотез<p>Validation '+pct(r.validation.return)+' · Holdout '+pct(r.holdout.return)+'</p></div>').join('')||'<p>Нет завершённых проверок</p>';const s=j.scout;el('scout').innerHTML=s?'<p>Спотовых пар: '+esc(s.spot_pairs)+' · фьючерсных пар: '+esc(s.linear_pairs)+' · маршрутов 3–5 обменов: '+esc(s.routes_checked)+' · '+esc(dt(s.time))+'</p><h3>Маршруты (оценки)</h3>'+s.routes.map(r=>'<p>'+esc(r.path.join(' → '))+' · '+pct(r.net_estimate)+'</p>').join('')+'<h3>Фандинг (ставка, не прибыль)</h3>'+s.funding.map(r=>'<p>'+esc(r.symbol)+' · '+pct(r.funding_rate)+'</p>').join('')+'<h3>Базис (оценка)</h3>'+s.basis.map(r=>'<p>'+esc(r.symbol)+' · '+pct(r.basis)+'</p>').join('')+'<small>Сделки по цепочкам и хеджам не исполняются. Оценки не зачисляются на баланс.</small>':'Нет подтверждённых данных';}
function renderLearning(j){const l=j.learning||{},p=l.profile||{},o=p.overall||{};const d=Object.entries(l.daily||{}).sort((a,b)=>b[0].localeCompare(a[0]));let html='<p>Последний анализ '+esc(dt(l.time))+' · выборка '+esc(o.trades??0)+' закрытых сделок · масштаб позиции '+pct(p.size_scale)+' от лимита 25%</p><p>Средняя чистая доходность на номинал '+pct(o.avg_net)+' · серия убытков '+esc(o.loss_streak??0)+'</p>';html+=d.slice(0,7).map(([day,roles])=>'<div class="model"><h3>'+esc(day)+'</h3>'+Object.entries(roles).map(([k,v])=>'<p>'+esc(k)+' · событий '+esc(v.events)+' · завершено '+esc(v.completed)+' · ошибок '+esc(v.errors)+'</p>').join('')+'</div>').join('');const h=Object.entries(l.history||{}).sort((a,b)=>b[0].localeCompare(a[0]));html+=h.slice(0,7).map(([day,v])=>'<p>'+esc(day)+' · капитал '+money(v.equity)+' · тесты фьючерсы '+esc(v.futures_tests_24h)+' / спот '+esc(v.spot_tests_24h)+' · день '+pct(v.day_return)+'</p>').join('');el('teamlearning').innerHTML=html+'<small>Счётчики активности не являются оценкой интеллекта. Адаптация использует закрытые виртуальные сделки, если они есть.</small>';}
function renderForward(j){const l=j.forward_lab||{};el('forwardStats').textContent='Активных моделей '+(l.active||0)+' · открыто экспериментов '+(l.open||0)+' · закрыто '+(l.closed||0)+' · прошли порог практики '+(l.eligible||0)+' · '+dt(l.time);rows('forwardRows',(l.rows||[]).map(x=>'<tr><td>'+esc(x.key)+'</td><td>'+esc(x.market)+'</td><td>'+money(x.equity)+'</td><td>'+x.closed+'</td><td>'+pct(x.avg_net)+'</td><td>'+pct(x.drawdown)+'</td><td>'+ (x.open?'Открыта':x.active?'Активна':'Архив')+'</td></tr>'),'Пока нет экспериментов',7);el('portfolioPositions').innerHTML='<p>Позиций '+(j.positions||[]).length+' / 6 · номинал '+money(j.portfolio_exposure)+' / до 75% капитала</p>'+(j.positions||[]).map(p=>'<div class="model">'+esc(p.market||'linear')+' · '+esc(p.symbol)+' · '+(p.admission_tier==='practice'?'Учебная · ':'')+side(p.side)+' · '+money(p.qty*p.entry)+'</div>').join('');}
function renderRuntime(j){const flow=j.flow||{};const feed=j.feed||{};const st=j.state||{},l=j.learning||{},f=j.forward_lab||{},m=j.micro_status||{};const age=t=>!t?'Нет подтверждения':Date.now()/1000-t>900?'Устарело · '+dt(t):dt(t);const items=[['Торговый цикл',st.last_poll,st.error||JSON.stringify(st.symbol_errors||{})],['Память и обучение',l.time,l.time?'':'Цикл пока не подтверждён'],['Параллельная практика',f.time,JSON.stringify(f.errors||{})],['Рыночные данные',m.time,JSON.stringify(m.errors||{})],['Исторический тест',j.latest_training?.time,j.latest_training?.error||''],['Дополнительное исследование',j.exploration?.time,j.exploration?.symbol?'Пара '+j.exploration.symbol+' · проверено '+j.exploration.tested+' гипотез':'']];el('runtime').innerHTML='<p><b>Тиковый поток</b> · принято '+esc(flow.trades??0)+' сделок · проверенных полных свечей '+esc(flow.complete??0)+' / '+esc(flow.saved??0)+' · профиль 1 б.п.</p><p><b>WebSocket</b> · '+Object.entries(feed.streams||{}).map(([k,v])=>esc(k)+': '+(v.connected?'соединён':'отключён')+' · '+esc(v.messages||0)+' сообщений · '+esc(dt(v.last_message))+(v.error?' · '+esc(v.error):'')).join(' / ')+'</p><p>Свежие стаканы: '+esc(feed.fresh_books??0)+' · запросы из потока: '+esc(feed.ws_hits??0)+' · REST: '+esc(feed.rest_calls??0)+' · пауза REST: '+esc(feed.rest_cooldown_seconds??0)+' сек.</p>'+items.map(([n,t,e])=>'<p><b>'+esc(n)+'</b> · '+esc(age(t))+(e&&e!=='{}'?' · <span class="warn">'+esc(e)+'</span>':'')+'</p>').join('');}
function renderScalp(j){const s=j.scalp||{};el('scalpStats').textContent='Моделей '+(s.models||0)+' · сигналов '+(s.signals||0)+' · ожидают '+(s.pending||0)+' · открыто '+(s.open||0)+' · закрыто '+(s.closed||0)+' · поколение '+(s.generation||0)+' · '+dt(s.time);const labels={momentum:'Импульс',absorption:'Поглощение',liquidity_sweep:'Снятие ликвидности',depth_shift:'Изменение глубины',passive:'Пассивные заявки',cost_trend:'Тренд с фильтром расходов',cost_reversal:'Разворот с фильтром расходов'};el('scalpFamilies').innerHTML=Object.entries(s.families||{}).map(([k,v])=>'<p><b>'+esc(labels[k]||k)+'</b> · '+v.models+' моделей · '+v.signals+' сигналов · '+v.closed+' закрыто · '+v.wins+' в плюс</p>').join('')+'<p>Потоки: '+Object.entries(s.feeds||{}).map(([k,v])=>esc(k)+' ('+v.seconds+' секунд с сделками; окна '+Object.keys(v.windows||{}).join('/')+')').join(' · ')+'</p>';el('scalpTop').innerHTML=(s.top||[]).filter(x=>x.closed>0).map(x=>'<p>'+esc(x.symbol)+' · '+esc(x.market)+' · '+esc(labels[x.config[0]]||x.config[0])+' / '+x.config[1]+'с · '+x.closed+' сделок · '+money(x.equity)+' · средний net '+pct(x.avg)+'</p>').join('')||'<p>Пока нет завершённых экспериментов</p>';}
let loading=false;
async function fetchTimed(url){const ac=new AbortController();const timer=setTimeout(()=>ac.abort(),12000);try{const r=await fetch(url,{cache:'no-store',signal:ac.signal});if(!r.ok)throw Error('HTTP '+r.status);return await r.json()}finally{clearTimeout(timer)}}
async function refresh(){if(loading)return;loading=true;
try{const o=await fetchTimed('/api/overview');const e=o.equity,d=e-o.day_start;value('equity',e-o.start,money(e));value('balance',0,money(o.balance));value('daily',d,signed(d)+' USDT');el('total').textContent='С начала: '+signed(e-o.start)+' USDT ('+pct(e/o.start-1)+')';el('daypct').textContent=pct(d/o.day_start)+' · '+o.day;el('health').textContent='Капитал обновлён · загрузка лаборатории…'}catch(e){el('health').textContent='Нет свежего снимка капитала: '+e.message}
try{const j=await fetchTimed('/api/status');render(j);if(Date.now()/1000-j.snapshot_time>90)el('health').textContent+=' · снимок устарел'}catch(e){el('health').textContent='Подробные данные недоступны: '+e.message+' · повторяем загрузку'}finally{loading=false}}
el('period').onchange=draw;el('tradeperiod').onchange=draw;refresh();setInterval(refresh,30000);

async function demoRefresh(){try{const r=await fetch('/api/demo',{cache:'no-store'});const d=await r.json();document.getElementById('demoState').textContent='Статус: '+d.status+' · Баланс USDT: '+(d.wallet_usdt??'—')+' · Equity: '+(d.equity_usdt??'—')+' · Позиций робота: '+(d.managed??0)+' · Закрыто: '+(d.closed??0)+' · Режим: '+(d.direct_strategy_mode?'прямые сигналы стратегий':'зеркало портфеля')+' · Сигналов: '+(d.selection?.signals??0)+' · Диагностика завершена · Проверки входов: '+Object.keys(d.probes||{}).length+' · Успешные циклы: '+Object.values(d.probes||{}).filter(p=>p.status==='roundtrip_confirmed').length+' · PnL стратегий (сверено '+(d.strategy_pnl_matched??0)+'): '+Number(d.strategy_pnl??0).toFixed(4)+' · PnL диагностики (сверено): '+Number(d.diagnostic_pnl??0).toFixed(4)+(d.error?' · '+d.error:'');const h=Object.values(d.deep_history?.history||{});document.getElementById('deepHistory').textContent='Исторические свечи: '+h.reduce((a,b)=>a+b.bars,0)+' из примерно 51840 · Завершено рынков: '+h.filter(x=>x.done).length+'/6';}catch(e){document.getElementById('demoState').textContent='Нет связи с сервером';}}
demoRefresh();setInterval(demoRefresh,10000);
</script></main></body></html>"""
@app.get("/")
@app.get("/admin")
def dashboard():return render_template_string(PAGE)

def start_workers():
    global LAB,LEARNING
    STATE["status"]="waiting_for_worker_lock"
    lock=store.acquire_worker_lock()
    logging.info("WORKER LOCK acquired; starting single worker group")
    threading.Thread(target=store.monitor_worker_lock,args=(lock,),daemon=True).start()
    team_selftest()
    replay_lab.selftest()
    context_lab.selftest()
    online_ml.selftest()
    CONTEXT.update(store.get("context_research",{}) or {})
    market.feed_selftest()
    tick_flow.selftest()
    scalp_lab.selftest()
    market.start_feeds()
    threading.Thread(target=scalp_lab.worker,args=(market,),daemon=True).start()
    threading.Thread(target=tick_flow.writer,args=(market,),daemon=True).start()
    assert candidate_count([1,2])==2 and candidate_count(3)==3 and candidate_count(None)==0
    test=normalize_portfolio(risk.initial())
    assert portfolio_allowed(test) and exposure(test)==0
    paper_exec.selftest()
    assert not make_position("spot","BTCUSDT",1,{"model":{"kind":"test"}},{"bid":99.,"ask":100.},100.,time.time())
    LAB=store.get("forward_lab",{}) or {}
    threading.Thread(target=replay_lab.worker,args=(market,spot_universe),daemon=True).start()
    threading.Thread(target=deep_history.worker,daemon=True).start()
    threading.Thread(target=lab_worker,daemon=True).start()
    threading.Thread(target=online_ml.worker,args=(market,make_position,valuation,costs,model_key,lab_account,spot_universe),daemon=True).start()
    threading.Thread(target=online_ml.worker,args=(market,make_position,valuation,costs,model_key,lab_account,spot_universe,True),daemon=True).start()
    threading.Thread(target=explore_worker,daemon=True).start()
    LEARNING=store.get("team_learning",{}) or {}
    threading.Thread(target=learning_worker,daemon=True).start()
    threading.Thread(target=scout_worker,daemon=True).start()
    threading.Thread(target=spot_trainer_worker,daemon=True).start()
    threading.Thread(target=market_lab.stream_worker,daemon=True).start()
    threading.Thread(target=market_lab.collector,daemon=True).start()
    league.selftest()
    threading.Thread(target=market_worker,daemon=True).start()
    threading.Thread(target=portfolio_worker,daemon=True).start()
    threading.Thread(target=bybit_demo.worker,daemon=True).start()
    threading.Thread(target=dashboard_worker,daemon=True).start()
    threading.Thread(target=trainer_worker,daemon=True).start()

if __name__=="__main__":
    def guarded_start():
        try:start_workers()
        except BaseException:
            logging.exception("Worker startup failed");os._exit(1)
    threading.Thread(target=guarded_start,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=4)
