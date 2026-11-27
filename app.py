"""Clean demo foundation: no legacy strategy workers, no training, no new orders."""
import os,time,threading,logging,requests
from flask import Flask,jsonify,send_from_directory
from waitress import serve
import store,market,bybit_demo,sir_live,sir_paper,sergey_paper
app=Flask(__name__)
logging.basicConfig(level=logging.INFO)
STATE={"status":"starting","version":"short1042-v1.1-no-m1","mode":"demo","entries_enabled":True,"research_workers":0,"strategies":["short1042_h1","short1042_m5","short1042_m15","sergey_paper"]}
def payload():
    return {"state":dict(STATE),"demo":dict(bybit_demo.VIEW),"demo_detail":bybit_demo.DASH_VIEW,"market":market.feed_status(),"server_time":time.time(),"archive_preserved":True,"sir":sir_live.VIEW,"paper":{**sir_paper.VIEW,"sergey":sergey_paper.VIEW}}
@app.get("/health")
def health():
    return {"service":"smart-trader-ai","status":STATE["status"],"mode":"demo"}
@app.get("/api/status")
@app.get("/api/cabinet")
@app.get("/api/overview")
def status():return jsonify(payload())
# Durable research status; never contacts Bybit from the HTTP handler.
@app.get("/api/research/impulse")
def impulse_research():
    try:
        d=store.get("research:impulse_pro:20260915:v2:report")
        return jsonify({"data":d,"fetched_at":d.get("updated") if d else None,"error":None if d else "Ожидание первого сохранённого отчёта"})
    except Exception:
        return jsonify({"data":None,"fetched_at":None,"error":"Исследовательская база временно недоступна"})
@app.get("/api/research/adaptive")
def adaptive_status():
    try:
        out={}
        for version in ("v1","v2"):
            d=store.get("research:impulse_adaptive:20260915:"+version)
            if d:out[version]={"scanned":len(d["scanned"]),"universe":len(d["universe"]),"complete":d["complete"],"results":d.get("result"),"updated":d.get("updated")}
        d=store.get("research:impulse_adaptive:20260915:v2:daily_risk")
        if d:
            out["daily_risk"]={k:d[k] for k in ("scanned","universe","complete","updated","models")}
        d=store.get("research:adaptive_holdout:20261001:v1")
        if d:out["month"]={k:d[k] for k in ("period","model","policy","complete","updated","result")}|{"scanned":len(d["scanned"]),"universe":len(d["universe"]),"excluded_count":len(d["excluded"])}
        if "month" in out:out["month"]["archived"]=True
        d=store.get("research:adaptive_entry_quality:october:v1")
        if d:out["quality"]={"scanned":len(d["scanned"]),"universe":len(d["universe"]),"complete":d["complete"],"updated":d["updated"],"result":d.get("result",{}),"excluded_count":len(d["excluded"])}
        if "quality" in out:out["quality"]["archived"]=True
        d=store.get("research:adaptive_recovery:october:v1")
        if d:out["recovery"]={"scanned":len(d["scanned"]),"universe":len(d["universe"]),"complete":d["complete"],"updated":d["updated"],"result":d.get("result",{}),"excluded_count":len(d["excluded"]),"reused":d["reused"]}
        if "recovery" in out:out["recovery"]["archived"]=True
        d=store.get("research:adaptive_forensics:october:v1")
        if d:out["forensics"]={"scanned":len(d["scanned"]),"universe":len(d["universe"]),"complete":d["complete"],"updated":d["updated"],"result":d.get("result",{}),"excluded_count":len(d["excluded"]),"diagnosis":d["excursion_summary"],"archive":d["archive"],"archive_scanned":d["archive_scanned"]}
        if "forensics" in out:out["forensics"]["archived"]=True
        d=store.get("research:range_sweep_refine:october:v1")
        if d:out["range_refine"]={"scanned":len(d["scanned"]),"universe":len(d["universe"]),"complete":d["complete"],"updated":d["updated"],"result":d.get("result",{}),"excluded_count":len(d["excluded"]),"diagnosis":d["diagnosis"],"archive":d["archive"],"archive_scanned":d["archive_scanned"],"reused_empty":d["reused_empty"]}
        if d and "rank_report" in d:
            out["range_rank"]={**d["rank_report"],"scanned":len(d["scanned"]),"universe":len(d["universe"]),"feature_rows":len(d["rank_rows"]),"candidate_total":len(d["events"]["target125"]),"backfill_done":len(d["rank_done"]),"backfill_total":len(d["rank_backfill"])}
        return jsonify(out)
    except Exception:
        return jsonify({"error":"Исследовательская база временно недоступна"}),503

# Historical research only. Never accept arbitrary database keys or SQL.
import json, hashlib, hmac
from flask import request
RESEARCH_ARCHIVES={
    "september_range":("research:september_range_validation:v1",("impulse_control","impulse_no_breakeven","range_control","range_no_breakeven")),
    "september_structure":("research:september_structure_rank:v1",("rank_rows",)),
    "september":("research:impulse_adaptive:20260915:v2",("M5_30m","M5_15m","M5_60m","M5_60m_fixed","M5_30m_aligned","M5_60m_aligned","M5_30m_switch","M5_60m_switch")),
    "october":("research:range_sweep_refine:october:v1",("control","hold60","no_breakeven","target125","midpoint","wick_confirm","cost_filter","rank_rows")),
}
EVENT_FIELDS=("entry_minute_utc","negative_volume_score","symbol","exit_minute_utc","entry_price","risk_per_unit","net_pnl_per_unit","fee_per_unit","funding_per_unit")
def research_rows(state,model):
    if model=="rank_rows":return state.get("rank_rows",[])
    return state.get("events",{}).get(model,[])
def research_snapshot(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def research_response(data,status=200):
    response=jsonify(data)
    response.status_code=status
    response.headers["Cache-Control"]="no-store"
    return response
@app.get("/api/research/archive/<period>")
def research_archive(period):
    token=os.getenv("RESEARCH_API_TOKEN","")
    supplied=request.headers.get("Authorization","")
    if len(token)<32 or not hmac.compare_digest(supplied.encode(),("Bearer "+token).encode()):
        return research_response({"error":"unauthorized"},401)
    if period not in RESEARCH_ARCHIVES:return research_response({"error":"unknown archive"},404)
    key,models=RESEARCH_ARCHIVES[period]
    model=request.args.get("model")
    if model is not None and model not in models:return research_response({"error":"unknown model"},404)
    try:
        offset=int(request.args.get("offset","0"));limit=int(request.args.get("limit","100"))
        if offset<0 or not 1<=limit<=250:return research_response({"error":"invalid pagination"},400)
    except ValueError:return research_response({"error":"invalid pagination"},400)
    try:
        state=store.get(key)
        if not state:return research_response({"error":"archive not available"},404)
        meta={"period":period,"updated":state.get("updated"),"complete":bool(state.get("complete")),"scanned":len(state.get("scanned",[])),"universe":len(state.get("universe",[]))}
        if model is None:
            return research_response({**meta,"models":{m:len(research_rows(state,m)) for m in models},"event_fields":EVENT_FIELDS,"report":state.get("report") if period in ("september_structure","september_range") else None})
        rows=research_rows(state,model);snapshot=research_snapshot(rows)
        expected=request.args.get("snapshot")
        if expected and expected!=snapshot:return research_response({"error":"snapshot changed; restart pagination"},409)
        return research_response({**meta,"model":model,"snapshot":snapshot,"total":len(rows),"offset":offset,"next_offset":offset+limit if offset+limit<len(rows) else None,"rows":rows[offset:offset+limit],"event_fields":EVENT_FIELDS})
    except Exception:
        logging.warning("RESEARCH_ARCHIVE_READ_FAILED")
        return research_response({"error":"archive unavailable"},503)

# Bounded read-only public market gateway. No trading commands or raw DB writes.
import re
_MARKET_QUEUE_URL="https://raw.githubusercontent.com/shkuratovjony-png/12/research-data-requests/market_request.json"
_MARKET_GATE_LOCK=threading.Lock()
_MARKET_GATE_NEXT=0.
def market_query(q):
    if not isinstance(q,dict) or set(q)-{"kind","symbol","interval","start","end"}:raise ValueError("invalid fields")
    kind=q.get("kind");sym=q.get("symbol");start=q.get("start");end=q.get("end")
    if kind not in ("kline","funding") or not isinstance(sym,str) or not re.fullmatch(r"[A-Z0-9]{2,30}USDT",sym):raise ValueError("invalid market")
    if type(start)!=int or type(end)!=int or not 1483228800000<=start<end<=int(time.time()*1000):raise ValueError("invalid historical range")
    if kind=="kline":
        i=q.get("interval")
        if type(i)!=int or i not in (1,3,5,15,30,60,120,240,360,720):raise ValueError("invalid interval")
        step=i*60000
        if start%step or end%step or (end-start)//step>1000:raise ValueError("aligned window max 1000 candles")
        return "kline",{"symbol":sym,"interval":str(i),"start":start,"end":end-1,"limit":1000},step
    if "interval" in q or end-start>7*86400000:raise ValueError("funding max 7 days")
    return "funding/history",{"symbol":sym,"startTime":start,"endTime":end-1,"limit":200},0
def market_fetch(q):
    import paper_feed
    global _MARKET_GATE_NEXT
    path,params,step=market_query(q)
    if not _MARKET_GATE_LOCK.acquire(blocking=False):raise RuntimeError("busy")
    try:
        now=time.time()
        if now%3600<190 or now%300<50 or paper_feed.HTTP.locked() or time.monotonic()<max(paper_feed.PAUSE,_MARKET_GATE_NEXT):raise RuntimeError("busy")
        _MARKET_GATE_NEXT=time.monotonic()+15
        data=paper_feed.request(path,**params)
        start,end=q["start"],q["end"]
        if step:
            rows=sorted([row[:7] for row in data["list"] if start<=int(row[0])<end],key=lambda row:int(row[0]))
            complete=[int(row[0]) for row in rows]==list(range(start,end,step))
        else:
            rows=sorted([[row["fundingRateTimestamp"],row["fundingRate"]] for row in data["list"] if start<=int(row["fundingRateTimestamp"])<end],key=lambda row:int(row[0]))
            complete=len(data["list"])<200
        return {"query":q,"rows":rows,"complete":complete}
    finally:_MARKET_GATE_LOCK.release()
@app.post("/api/research/market")
def market_endpoint():
    token=os.getenv("RESEARCH_API_TOKEN","")
    supplied=request.headers.get("Authorization","")
    if len(token)<32 or not hmac.compare_digest(supplied.encode(),("Bearer "+token).encode()):
        return research_response({"error":"unauthorized"},401)
    if request.content_length is None or request.content_length>2048:return research_response({"error":"invalid body size"},400)
    try:return research_response(market_fetch(request.get_json(silent=True)))
    except ValueError:return research_response({"error":"invalid market request"},400)
    except Exception:return research_response({"error":"market busy; retry later"},429)
def market_queue_worker():
    import requests as http
    session=http.Session();key="research:market_gateway:metadata:v1"
    while True:
        try:
            if not store.URL or len(os.getenv("RESEARCH_API_TOKEN",""))<32:
                time.sleep(30);continue
            with session.get(_MARKET_QUEUE_URL,timeout=8,stream=True,allow_redirects=False) as resp:
                if resp.status_code!=200:raise RuntimeError("queue unavailable")
                buf=bytearray()
                for part in resp.iter_content(4096):
                    buf.extend(part)
                    if len(buf)>32768:raise ValueError("queue too large")
            job=json.loads(buf)
            if not isinstance(job,dict) or set(job)!={"id","requests"}:raise ValueError("invalid job")
            jid,queries=job["id"],job["requests"]
            if not isinstance(jid,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}",jid) or not isinstance(queries,list) or not 1<=len(queries)<=32:raise ValueError("invalid job")
            for q in queries:market_query(q)
            digest=research_snapshot(job);meta=store.get(key,{})
            if meta.get("digest")!=digest:
                meta={"digest":digest,"id":jid,"done":[]};store.put(key,meta)
            for index,q in enumerate(queries):
                if index in meta["done"]:continue
                try:data=market_fetch(q)
                except Exception:break
                rows=data["rows"];tag=research_snapshot(rows)
                for off in range(0,len(rows),20):
                    print("MARKET_GATEWAY_V1 "+json.dumps({"id":jid,"index":index,"snapshot":tag,"offset":off,"rows":rows[off:off+20]},separators=(",",":"),allow_nan=False),flush=True)
                print("MARKET_GATEWAY_MANIFEST_V1 "+json.dumps({"id":jid,"index":index,"snapshot":tag,"query":q,"total":len(rows),"complete":data["complete"]},separators=(",",":")),flush=True)
                meta["done"].append(index);store.put(key,meta)
                del data,rows
                # One page per poll; low priority, bounded output.
                break
        except Exception:
            logging.warning("MARKET_GATEWAY_QUEUE_UNAVAILABLE")
        time.sleep(30)

def research_log_bridge():
    # Authenticated Render logs provide a second read-only transport for
    # historical research records, without public DB access or trading secrets.
    seen={}
    while True:
        try:
            if store.URL:
                for period,selected in (("september",("M5_30m_switch",)),("october",("target125","rank_rows","midpoint","cost_filter","control"))):
                    state=store.get(RESEARCH_ARCHIVES[period][0])
                    if not state:continue
                    for model in selected:
                        rows=research_rows(state,model);digest=research_snapshot(rows)
                        prior=seen.get((period,model))
                        if prior and prior[0]==digest and time.time()-prior[1]<86400:continue
                        for offset in range(0,len(rows),10):
                            print("RESEARCH_EXPORT_V1 "+json.dumps({"period":period,"model":model,"snapshot":digest,"offset":offset,"total":len(rows),"rows":rows[offset:offset+10]},ensure_ascii=True,separators=(",",":"),allow_nan=False),flush=True)
                        print("RESEARCH_EXPORT_MANIFEST_V1 "+json.dumps({"period":period,"model":model,"snapshot":digest,"total":len(rows),"scanned":len(state.get("scanned",[])),"complete":bool(state.get("complete"))},separators=(",",":")),flush=True)
                        seen[(period,model)]=(digest,time.time())
        except Exception:
            logging.warning("RESEARCH_EXPORT_FAILED",exc_info=False)
        time.sleep(900)


# Read-only market research, isolated checkpoints. No order placement.
def september_structure_research():
    import math
    import numpy as np
    import paper_feed
    import impulse_daily_risk as dr
    from collections import defaultdict
    key="research:september_structure_rank:v1"
    feature_names=("log_rvol","risk_pct","side","m15_trend_aligned","m1_trend_aligned","m1_recent_choch","m1_recent_fvg","fvg_mid_distance_r","m5_relative_volume","m15_efficiency")
    def structure(bars):
        hi=[];lo=[];trend=0;last_h=last_l=-1;changes=[];gaps=[]
        for i,b in enumerate(bars):
            if i>=4:
                p=i-2
                if bars[p][2]>max(bars[j][2] for j in (p-2,p-1,p+1,p+2)):hi.append((p,bars[p][2]))
                if bars[p][3]<min(bars[j][3] for j in (p-2,p-1,p+1,p+2)):lo.append((p,bars[p][3]))
                if hi and b[4]>hi[-1][1] and last_h!=hi[-1][0]:
                    if trend==-1:changes.append((i,1))
                    trend=1;last_h=hi[-1][0]
                if lo and b[4]<lo[-1][1] and last_l!=lo[-1][0]:
                    if trend==1:changes.append((i,-1))
                    trend=-1;last_l=lo[-1][0]
            if i>=2:
                if b[3]>bars[i-2][2]:gaps.append((i,1,(b[3]+bars[i-2][2])/2))
                if b[2]<bars[i-2][3]:gaps.append((i,-1,(b[2]+bars[i-2][3])/2))
        d=0
        if len(hi)>1 and len(lo)>1:
            if hi[-1][1]>hi[-2][1] and lo[-1][1]>lo[-2][1] and trend==1:d=1
            if hi[-1][1]<hi[-2][1] and lo[-1][1]<lo[-2][1] and trend==-1:d=-1
        return d,changes,gaps
    def aggregate(bars,n):
        buckets=defaultdict(list)
        for b in bars:buckets[b[0]//n*n].append(b)
        return [[t,v[0][1],max(b[2] for b in v),min(b[3] for b in v),v[-1][4],sum(b[5] for b in v)] for t,v in sorted(buckets.items()) if len(v)==n and v[0][0]==t and v[-1][0]==t+n-1]
    def features(ev,by_time):
        t,negvol,sym,end,entry,risk,*_=ev
        if any(k not in by_time for k in range(t-480,t+1)):return None
        bars=[by_time[k] for k in range(t-480,t)]
        # Entry open determines original side from the archived slippage; no
        # subsequent price or outcome is used as a predictor.
        op=by_time[t][1];delta=entry/op-1
        if abs(abs(delta)-.0002)>1e-6:return None
        side=1 if delta>0 else -1
        m15=aggregate(bars,15);m5=aggregate(bars,5)
        d15,_,_=structure(m15);d1,ch,gaps=structure(bars)
        recent_ch=any(i>=len(bars)-10 and s==side for i,s in ch)
        recent_gaps=[(i,p) for i,s,p in gaps if s==side and i>=len(bars)-15]
        distance=min((abs(bars[-1][4]-p)/risk for i,p in recent_gaps),default=5.)
        v=m5[-1][5]/max(sum(b[5] for b in m5[-21:-1])/20,1e-12)
        cl=[b[4] for b in m15[-13:]]
        er=abs(cl[-1]-cl[0])/max(sum(abs(y-x) for x,y in zip(cl,cl[1:])),1e-12)
        x=[math.log(max(-negvol,1e-12)),risk/entry,side,side*d15,side*d1,float(recent_ch),float(bool(recent_gaps)),min(distance,5.),math.log(max(v,1e-12)),er]
        return x if all(math.isfinite(z) for z in x) else None
    def predict_fit(train,test):
        if len(train)<30:return None
        X=np.array([x for e,x in train]);y=np.array([e[6]/e[5] for e,x in train])
        if not (np.any(y>0) and np.any(y<=0)):return None
        lo,hi=np.quantile(X,[.05,.95],axis=0);X=np.clip(X,lo,hi);mu=X.mean(0);sd=X.std(0);sd[sd<1e-8]=1
        z=(X-mu)/sd;coef=np.linalg.solve(z.T@z+20*np.eye(z.shape[1]),z.T@(y-y.mean()))
        return [(e,float(y.mean()+((np.clip(x,lo,hi)-mu)/sd)@coef)) for e,x in test],coef.tolist()
    try:
        if not store.URL:return
        src=store.get("research:impulse_adaptive:20260915:v2")
        if not src or not src.get("complete"):return
        events=src["events"]["M5_30m_switch"]
        digest=research_snapshot(events)
        state=store.get(key)
        if state and state.get("source")!=digest:
            logging.warning("SEPT_STRUCTURE_SOURCE_CHANGED; refusing mixed snapshot");return
        if not state:state={"source":digest,"done":[],"rank_rows":[],"missing":[],"complete":False}
        if state.get("complete"):
            print("SEPT_STRUCTURE_RESULT "+json.dumps(state["report"],separators=(",",":")),flush=True);return
        groups=defaultdict(list)
        for idx,e in enumerate(events):groups[e[2]].append((idx,e))
        tasks=[]
        for sym,items in sorted(groups.items()):
            items.sort(key=lambda it:it[1][0])
            while items:
                first=items[0][1][0];n=0
                while n<len(items) and items[n][1][0]-first<=500:n+=1
                batch,items=items[:n],items[n:];tasks.append((sym,first,batch))
        for sym,first,batch in tasks:
            ident=sym+":"+str(first)
            if ident in state["done"]:continue
            last=batch[-1][1][0];start=first-480
            cached=store.get(key+":candles:"+ident)
            if cached is None:
                # One request per group (<=981 bars), low priority, respecting
                # shared cooldown and existing trading/research quiet windows.
                while True:
                    now=time.time()
                    if now%3600<190 or now%300<50 or paper_feed.HTTP.locked() or time.monotonic()<paper_feed.PAUSE:
                        time.sleep(5);continue
                    try:
                        data=paper_feed.request("kline",symbol=sym,interval="1",start=start*60000,end=(last+1)*60000-1,limit=1000)
                        cached=[[int(r[0])//60000,*map(float,r[1:6])] for r in data["list"] if start<=int(r[0])//60000<=last]
                        # Raw candles are transient; persist derived features and progress only.
                        break
                    except Exception:
                        logging.warning("SEPT_STRUCTURE_COOLDOWN %s",sym);time.sleep(120)
                time.sleep(15)
            by_time={r[0]:r for r in cached}
            for idx,ev in batch:
                x=features(ev,by_time)
                if x is None:state["missing"].append(idx)
                else:state["rank_rows"].append([ev,x])
            state["done"].append(ident);state["updated"]=time.time();state["scanned"]=state["done"];state["universe"]=[s+":"+str(t) for s,t,b in tasks];store.put(key,state)
            del by_time, cached
            print("SEPT_STRUCTURE_PROGRESS "+json.dumps({"groups":len(state["done"]),"total_groups":len(tasks),"features":len(state["rank_rows"]),"total_events":len(events),"missing":len(state["missing"])},separators=(",",":")),flush=True)
        rows=state["rank_rows"];cut=int(__import__("datetime").datetime(2026,9,18,tzinfo=__import__("datetime").timezone.utc).timestamp()/60)
        train=[(e,x) for e,x in rows if e[0]<cut and e[3]<cut];test=[(e,x) for e,x in rows if e[0]>=cut]
        report={"coverage":len(rows),"total":len(events),"missing":len(state["missing"]),"train":len(train),"test":len(test),"feature_names":feature_names,"baseline_full":dr.replay(events,"profit_lock"),"baseline_test":dr.replay([e for e,x in test],"profit_lock"),"status":"insufficient_or_partial"}
        fit=predict_fit(train,test)
        if fit is not None:
            scored,coef=fit;ranked=[];positive=[]
            for e,v in scored:
                q=list(e);q[1]=-v;ranked.append(q)
                if v>0:positive.append(q)
            report.update(coef=coef,rank_test=dr.replay(ranked,"profit_lock"),positive_test=dr.replay(positive,"profit_lock"),status="complete" if len(rows)==len(events) else "partial_coverage")
            if len(rows)==len(events):
                initial=[e for e in events if e[0]<cut]
                report["rank_week"]=dr.replay(initial+ranked,"profit_lock");report["positive_week"]=dr.replay(initial+positive,"profit_lock")
        state["complete"]=True;state["report"]=report;state["updated"]=time.time();store.put(key,state)
        print("SEPT_STRUCTURE_RESULT "+json.dumps(report,separators=(",",":"),allow_nan=False),flush=True)
    except Exception:
        logging.exception("SEPT_STRUCTURE_RESEARCH_FAILED")


# September validation of frozen October exits and sweep entry. Run sequentially
# with the existing September worker to avoid adding market API concurrency.
def september_range_replay():
    import numpy as np
    import pandas as pd
    import impulse_adaptive as a
    import impulse_daily_risk as dr
    import impulse_research as old
    key="research:september_range_validation:v1"
    models=("impulse_control","impulse_no_breakeven","range_control","range_no_breakeven")
    start,end=a.START,a.END
    def sweep(hourly,m,allowed):
        efficiency=(hourly.close-hourly.close.shift(12)).abs()/hourly.close.diff().abs().rolling(12).sum().replace(0,np.nan)
        efficiency.index=efficiency.index+pd.Timedelta(hours=1)
        vol=m.volume/m.volume.shift(1).rolling(20).mean()
        out=[]
        for side in (1,-1):
            o=side*m.open;c=side*m.close;low=m.low if side==1 else -m.high
            level=low.shift(1).rolling(12).min()
            mask=(low<level)&(c>level)&(c>o)&(vol>=1)
            for i in np.flatnonzero(mask.fillna(False).to_numpy())+1:
                if i<1 or i+12>=len(m):continue
                t=m.index[i]
                if not start<=t<end:continue
                f=allowed.get(t.floor("h"))
                if not f or not efficiency.get(t.floor("h"),np.nan)<=.25:continue
                entry=float(m.open.iloc[i])*(1+side*a.SLIP)
                stop=float(side*low.iloc[i-1])*(1-side*.0002)
                dist=side*(entry-stop)
                if not .01<=dist/entry<=.03 or side*(float(m.open.iloc[i])-stop)<=0:continue
                out.append((i,side,entry,stop,dist,float(f[1]),f[0]==side,True))
        return list({(x[0],x[1]):x for x in out}.values())
    try:
        if not store.URL:return
        src=store.get("research:impulse_adaptive:20260915:v2")
        if not src or not src.get("complete"):return
        # The old scanner retained every hourly-eligible symbol with valid M5,
        # including zero-signal symbols. Retry previously excluded M5/H1 only
        # separately in future; preserve exactly the admitted universe here.
        admitted=sorted(src["candidates"])
        digest=research_snapshot([admitted,src["events"]["M5_30m_switch"]])
        state=store.get(key)
        if state and state.get("source")!=digest:
            logging.warning("SEPT_RANGE_SOURCE_CHANGED");return
        if not state:
            state={"source":digest,"universe":admitted,"scanned":[],"complete":False,"events":{m:[] for m in models},"excluded":[],"original_excluded":src.get("excluded",[])}
        baseline=dr.replay(src["events"]["M5_30m_switch"],"profit_lock")
        def publish():
            results={k:dr.replay(v,"profit_lock") for k,v in state["events"].items()}
            for value in results.values():
                for t in pd.date_range(start,end-pd.Timedelta(days=1),freq="D"):
                    value["daily"].setdefault(t.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0,"entries":0})
                value["daily"]=dict(sorted(value["daily"].items()))
                value["flat_days"]=sum(v["pnl"]==0 for v in value["daily"].values())
            check=results["impulse_control"]
            matches=abs(check["roi"]-baseline["roi"])<.0002 and check["trades"]==baseline["trades"]
            state["report"]={"period":["2026-09-15","2026-09-21"],"scanned":len(state["scanned"]),"total":len(admitted),"complete":state["complete"],"original_universe":len(src["universe"]),"original_excluded":state["original_excluded"],"excluded":state["excluded"],"baseline_archived":baseline,"baseline_reproduced":matches,"results":results}
            state["updated"]=time.time();old.db_put(key,state)
            compact={k:{n:v[n] for n in ("balance","roi","dd","trades","wins","positive_days","negative_days","flat_days")} for k,v in results.items()}
            print("SEPT_RANGE_VALIDATION "+json.dumps({"scanned":len(state["scanned"]),"total":len(admitted),"complete":state["complete"],"baseline_reproduced":matches,"excluded":len(state["excluded"]),"results":compact},default=old.json_number,separators=(",",":")),flush=True)
        publish()
        if state["complete"]:return
        for sym in admitted:
            if sym in state["scanned"]:continue
            hourly=a.window(sym,60,start-pd.Timedelta(days=32),end)
            if hourly is None:
                state["excluded"].append(sym+":H1")
            else:
                allowed=a.eligible(hourly,start,end)
                if allowed:
                    m=a.window(sym,5,start-pd.Timedelta(minutes=120),end+pd.Timedelta(minutes=65))
                    if m is None:state["excluded"].append(sym+":M5")
                    else:
                        impulse=a.setups(m,allowed,start,end)
                        ss=sweep(hourly,m,allowed)
                        if impulse or ss:
                            rates=a.funding(sym)
                            if not rates:state["excluded"].append(sym+":funding")
                            else:
                                for name,signals,trail in (("impulse_control",impulse,1),("impulse_no_breakeven",impulse,None),("range_control",ss,1),("range_no_breakeven",ss,None)):
                                    state["events"][name].extend(a.exits(sym,m,signals,rates,6,2,trail,"switch",end=end))
                        del m
                del hourly
            state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(admitted)
            publish()
    except Exception:
        logging.exception("SEPT_RANGE_VALIDATION_FAILED")
def september_research_queue():
    september_structure_research()
    september_range_replay()

def start_impulse():
    time.sleep(15)
    try:
        if not store.URL:
            logging.error("IMPULSE_DISABLED: persistent PostgreSQL unavailable")
            return
        import impulse_range_refine
        STATE["research_workers"]=1
        logging.info("RANGE_REFINE_START: previous forensic lab archived; frozen September risk")
        impulse_range_refine.run()
    except Exception:
        logging.exception("IMPULSE_WORKER_ERROR")
    finally:
        STATE["research_workers"]=0
@app.get("/api/demo")
def demo():return jsonify(bybit_demo.VIEW)
@app.get("/")
@app.get("/admin")
@app.get("/details")
def dashboard():return send_from_directory(os.path.dirname(os.path.abspath(__file__)),"cabinet.html",max_age=0)
def start_workers():
    try:
        store.init()
        STATE["status"]="waiting_for_worker_lock"
        lock=store.acquire_worker_lock()
        threading.Thread(target=store.monitor_worker_lock,args=(lock,),daemon=True).start()
        assert not bybit_demo.NEW_ENTRIES_ENABLED
        STATE["status"]="demo"
        logging.info("SHORT1042 ready: H1 demo, M5/M15 paper, Sergey paper; legacy and breakout entries disabled; archive retained")
        threading.Thread(target=sir_paper.worker,daemon=True,name="sir-paper").start()
        threading.Thread(target=sergey_paper.worker,daemon=True,name="sergey-paper").start()
        threading.Thread(target=start_impulse,daemon=True,name="impulse-research").start()
        threading.Thread(target=research_log_bridge,daemon=True,name="research-export").start()
        threading.Thread(target=market_queue_worker,daemon=True,name="market-gateway").start()
        threading.Thread(target=september_research_queue,daemon=True,name="september-research").start()
        bybit_demo.worker()
    except BaseException:
        logging.exception("CLEAN BASE worker failed")
        os._exit(1)
if __name__=="__main__":
    threading.Thread(target=start_workers,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=4)
