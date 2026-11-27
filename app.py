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
    "september_range":("research:september_range_validation:v2",("impulse_control","impulse_no_breakeven","range_control","range_no_breakeven","range_hold60","range_target125","range_midpoint","range_wick_confirm","range_cost_filter")),
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
def september_structure_research(batch_limit=None):
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
            print("SEPT_STRUCTURE_RESULT "+json.dumps(state["report"],separators=(",",":")),flush=True);return True
        groups=defaultdict(list)
        for idx,e in enumerate(events):groups[e[2]].append((idx,e))
        tasks=[]
        for sym,items in sorted(groups.items()):
            items.sort(key=lambda it:it[1][0])
            while items:
                first=items[0][1][0];n=0
                while n<len(items) and items[n][1][0]-first<=500:n+=1
                batch,items=items[:n],items[n:];tasks.append((sym,first,batch))
        processed=0
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
            processed+=1
            if batch_limit and processed>=batch_limit and len(state["done"])<len(tasks):return False
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
        return True
    except Exception:
        logging.exception("SEPT_STRUCTURE_RESEARCH_FAILED")


# September validation of frozen October exits and sweep entry. Run sequentially
# with the existing September worker to avoid adding market API concurrency.
def september_range_replay(batch_limit=None):
    import numpy as np
    import pandas as pd
    import impulse_adaptive as a
    import impulse_daily_risk as dr
    import impulse_research as old
    key="research:september_range_validation:v2"
    models=("impulse_control","impulse_no_breakeven","range_control","range_no_breakeven","range_hold60","range_target125","range_midpoint","range_wick_confirm","range_cost_filter")
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
        # Old four-model state cannot be extended from outcomes alone.
        # Preserve its original archive; use a new version for all nine models.
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
        if state["complete"]:return True
        processed=0
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
                                def replay(name,signals,hold=6,target=2,trail=1):
                                    state["events"][name].extend(a.exits(sym,m,signals,rates,hold,target,trail,"switch",end=end))
                                # Exact original September M5 warm-up (30 minutes)
                                # for the archived impulse baseline, distinct from
                                # October Range Sweep's 120-minute warm-up.
                                im=m.loc[m.index>=start-pd.Timedelta(minutes=30)]
                                for name,trail in (("impulse_control",1),("impulse_no_breakeven",None)):
                                    state["events"][name].extend(a.exits(sym,im,a.setups(im,allowed,start,end),rates,6,2,trail,"switch",end=end))
                                replay("range_control",ss)
                                replay("range_no_breakeven",ss,6,2,None)
                                replay("range_hold60",ss,12)
                                replay("range_target125",ss,6,1.25,1)
                                wick=[];cheap=[]
                                for sig in ss:
                                    i,side,e,stop,d,*_=sig
                                    b=m.iloc[i-1];prior=m.iloc[i-13:i-1]
                                    if len(prior)==12:
                                        mid=(float(prior.high.max())+float(prior.low.min()))/2
                                        target=side*(mid-e)/d
                                        if 1<=target<=4:replay("range_midpoint",[sig],12,target,None)
                                    span=float(b.high-b.low)
                                    if span>0:
                                        tail=(min(b.open,b.close)-b.low) if side==1 else (b.high-max(b.open,b.close))
                                        close_loc=(b.close-b.low)/span if side==1 else (b.high-b.close)/span
                                        if tail/span>=.35 and close_loc>=.65:wick.append(sig)
                                    if 2*(a.F+a.SLIP)*e/d<=.08:cheap.append(sig)
                                replay("range_wick_confirm",wick)
                                replay("range_cost_filter",cheap)
                                del im
                        del m
                del hourly
            state["scanned"].append(sym);state["complete"]=len(state["scanned"])==len(admitted)
            publish()
            processed+=1
            if batch_limit and processed>=batch_limit and not state["complete"]:return False
        return True
    except Exception:
        logging.exception("SEPT_RANGE_VALIDATION_FAILED")
def september_research_queue():
    structure_done=range_done=False
    while not (structure_done and range_done):
        if not range_done:
            r=september_range_replay(batch_limit=2)
            if r is None:return
            range_done=r
        if not structure_done:
            r=september_structure_research(batch_limit=5)
            if r is None:return
            structure_done=r


# Dashboard exposes historical aggregates only; never credentials, raw candles,
# account balances, private trades or order controls.
_DASH_CACHE=None
_DASH_AT=0.
_DASH_LOCK=threading.Lock()
_YEAR_KEY="research:percoco_year_allmarket:v1"
_OCT_KEY="research:range_sweep_refine:october:v1"
_STRUCT_KEY="research:september_structure_rank:v1"
_SEPT_KEY="research:september_range_validation:v2"
_YEAR_PERIOD="21.11.2025 — 20.11.2026"
def october_finished(d):
    return bool(d.get("complete") and d.get("rank_report",{}).get("status") in ("complete_development_check","insufficient_data"))
def compact_model(name,value,leader=True):
    value=value or {}
    out={"name":name,"roi":value.get("roi"),"balance":value.get("balance"),"dd":value.get("dd"),"trades":value.get("trades"),"wins":value.get("wins"),"leader":leader}
    balance=1000.;daily=[]
    for date,v in sorted((value.get("daily") or {}).items()):
        pnl=float(v.get("pnl",0.));balance+=pnl
        daily.append({"date":date,"pnl":pnl,"roi":v.get("roi"),"balance":v.get("balance",round(balance,4)),"trades":v.get("trades",0)})
    if daily:out["daily"]=daily
    return out
_RANGE_NAMES={"control":"Range Sweep","no_breakeven":"No Breakeven","midpoint":"Midpoint","cost_filter":"Фильтр издержек","wick_confirm":"Свечная тень","target125":"Тейк 1,25R","hold60":"Удержание 60 мин"}
@app.get("/research-dashboard")
@app.get("/research")
def research_dashboard_page():
    from flask import Response
    response=Response("<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Smart Trader · Лаборатория</title><style>\n:root{color-scheme:dark;--bg:#0b1019;--panel:#131c2a;--line:#263346;--text:#eaf1fa;--muted:#91a2ba;--green:#49d9a0;--blue:#6da7ff;--red:#ff818a}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 70% 0,#172d42 0,transparent 45%),var(--bg);color:var(--text);font:15px/1.5 -apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif}main{max-width:1180px;margin:auto;padding:28px 18px 64px}header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.eyebrow{font-size:11px;letter-spacing:2px;color:var(--blue);font-weight:700}h1{font-size:clamp(25px,5vw,39px);line-height:1.15;letter-spacing:-1.3px;margin:6px 0 8px}h2{font-size:18px;margin:0;font-weight:650}p{margin:0;color:var(--muted)}a{color:var(--blue);text-decoration:none;font-size:13px}.top{margin:22px 0;display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.stat,.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px}.stat b{display:block;font-size:26px;font-variant-numeric:tabular-nums}.small{font-size:12px;color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.heading,.spread{display:flex;align-items:center;justify-content:space-between;gap:8px}.pill{border:1px solid var(--line);border-radius:999px;padding:4px 9px;font-size:11px;white-space:nowrap;color:var(--muted)}.running{color:var(--blue)}.done,.pos{color:var(--green)}.neg,.error{color:var(--red)}.pct{font-size:32px;font-weight:700;letter-spacing:-1px;margin:17px 0 3px;font-variant-numeric:tabular-nums}.bar{height:9px;border-radius:20px;background:#253246;margin:10px 0;overflow:hidden}.bar i{display:block;height:100%;border-radius:20px;background:linear-gradient(90deg,#367cf5,#48d7ae);transition:width .6s}.desc{font-size:12px;color:var(--muted);margin:7px 0 15px}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}th,td{text-align:right;padding:10px 5px;border-bottom:1px solid #263346}th{font-weight:500;color:var(--muted)}th:first-child,td:first-child{text-align:left;white-space:normal;min-width:105px}td:nth-child(2){font-weight:650}tbody tr:last-child td{border-bottom:0}.lead{background:#193329}.note{margin-top:16px;color:var(--muted);font-size:12px}.foot{margin-top:22px}.signal{width:7px;height:7px;background:var(--green);display:inline-block;border-radius:50%;margin-right:5px}.warn .signal{background:#eeb450}@media(max-width:720px){.grid{grid-template-columns:1fr}.stat,.card{padding:14px}.top{gap:7px}.stat b{font-size:19px}.small{font-size:11px}main{padding:20px 12px 40px}}@media(prefers-reduced-motion:reduce){*{transition:none!important}} .daydetail{border-top:1px solid var(--line);margin-top:12px;padding-top:10px}.daydetail summary{cursor:pointer;color:var(--blue);font-size:13px;font-weight:600}.dayrows{max-height:380px;overflow:auto;margin-top:8px}.dayrows th{position:sticky;top:0;background:var(--panel)}.dayrows td:first-child{min-width:85px;white-space:nowrap}</style></head><body><main><header><div><div class=\"eyebrow\">SMART TRADER / RESEARCH LAB</div><h1>Торговая лаборатория</h1><p>Исторические тесты · единый старт 1 000 USDT · UTC</p></div><div><a href=\"/admin\">← Кабинет бота</a><p class=\"small\" id=\"clock\"><span class=\"signal\"></span>Подключение…</p></div></header><div class=\"top\"><div class=\"stat\"><span class=\"small\">Направления</span><b id=\"jobcount\">5</b></div><div class=\"stat\"><span class=\"small\">Завершено</span><b id=\"completed\">—</b></div><div class=\"stat\"><span class=\"small\">Обновление</span><b>20 с</b></div></div><section class=\"grid\" id=\"cards\"><div class=\"card\">Загружаем результаты…</div></section><p class=\"note foot\">Промежуточный ROI не является прогнозом прибыли. Сравнение корректно на одинаковом периоде и покрытии. Просадка по закрытым сделкам; в годовом тесте отдельно по дневному балансу. Никаких торговых команд с этой страницы.</p></main><script>\nconst el=document.getElementById('cards'),clock=document.getElementById('clock');const esc=x=>String(x??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const num=(v,n=2)=>Number.isFinite(v)?v.toLocaleString('ru-RU',{minimumFractionDigits:n,maximumFractionDigits:n}):'—';const roi=v=>Number.isFinite(v)?(v>0?'+':'')+num(v)+'%':'—';const cls=v=>v>0?'pos':v<0?'neg':'';const status={queued:'В очереди',running:'В процессе',complete:'Завершено',error:'Ошибка',waiting:'Ожидание данных'};let busy=false;\nlet openDaily=new Set();\nfunction dailyTables(j,rows){return rows.filter(r=>r.daily?.length).map(r=>{const key=j.title+'|'+r.name;return '<details class=\"daydetail\" data-key=\"'+esc(key)+'\"'+(openDaily.has(key)?' open':'')+'><summary>'+esc(r.name)+' · по дням ('+r.daily.length+')</summary><div class=\"tablewrap dayrows\"><table><thead><tr><th>Дата UTC</th><th>P/L USDT</th><th>Доходность</th><th>Баланс</th><th>Сделок</th></tr></thead><tbody>'+r.daily.map(v=>'<tr><td>'+esc(v.date)+'</td><td class=\"'+cls(v.pnl)+'\">'+(v.pnl>0?'+':'')+num(v.pnl)+'</td><td class=\"'+cls(v.roi)+'\">'+roi(v.roi)+'</td><td>'+num(v.balance)+'</td><td>'+esc(v.trades)+'</td></tr>').join('')+'</tbody></table></div></details>'}).join('')}\nfunction render(d){openDaily=new Set([...document.querySelectorAll('details.daydetail[open]')].map(x=>x.dataset.key));document.getElementById('jobcount').textContent=d.jobs.length;document.getElementById('completed').textContent=d.jobs.filter(j=>j.status==='complete').length+' / '+d.jobs.length;el.innerHTML=d.jobs.map(j=>{const p=j.total?Math.min(100,j.done/j.total*100):0;let rows=j.models||[],valid=rows.filter(x=>Number.isFinite(x.roi)&&x.trades>0&&x.leader!==false),best=valid.length?valid.reduce((a,b)=>a.roi>=b.roi?a:b):null;return '<article class=\"card\"><div class=\"heading\"><h2>'+esc(j.title)+'</h2><span class=\"pill '+(j.status==='complete'?'done':esc(j.status))+'\">'+esc(status[j.status]||j.status)+'</span></div><div class=\"small\">'+esc(j.period)+'</div><div class=\"spread\"><div class=\"pct\">'+num(p,1)+'%</div><div style=\"text-align:right\"><div class=\"small\">'+(best?'Лидер':'Доходность')+'</div><strong class=\"'+cls(best?.roi)+'\">'+roi(best?.roi)+'</strong></div></div><div class=\"bar\"><i style=\"width:'+p+'%\"></i></div><div class=\"spread small\"><span>'+esc(j.done)+' / '+esc(j.total??'—')+' '+esc(j.unit)+'</span><span>'+esc(best?.name??'')+'</span></div><p class=\"desc\">'+esc(j.note)+'</p>'+(rows.length?'<div class=\"tablewrap\"><table><thead><tr><th>Стратегия</th><th>ROI</th><th>Баланс</th><th>DD</th><th>Сделок</th></tr></thead><tbody>'+rows.map(r=>'<tr class=\"'+(r===best?'lead':'')+'\"><td>'+esc(r.name)+'</td><td class=\"'+cls(r.roi)+'\">'+roi(r.roi)+'</td><td>'+num(r.balance)+'</td><td>'+ (Number.isFinite(r.dd)?num(r.dd)+'%':'—')+'</td><td>'+esc(r.trades??'—')+'</td></tr>').join('')+'</tbody></table></div>':'<p class=\"small\">Результаты появятся после расчёта.</p>')+dailyTables(j,rows)+'<p class=\"note\">'+(j.updated?'Отчёт: '+new Date(j.updated*1000).toLocaleString('ru-RU'):'Отчёта пока нет')+'</p></article>'}).join('');clock.className='small'+(d.stale?' warn':'');clock.innerHTML='<span class=\"signal\"></span>'+esc(d.stale?'Данные временно устарели':'Связь установлена')+' · '+new Date(d.server_time*1000).toLocaleTimeString('ru-RU')}\nasync function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/research/dashboard',{cache:'no-store'});if(!r.ok)throw Error('offline');render(await r.json())}catch(e){clock.className='small warn';clock.innerHTML='<span class=\"signal\"></span>Нет свежих данных · повторим запрос'}finally{busy=false}}refresh();setInterval(refresh,20000);\n</script></body></html>",mimetype="text/html")
    response.headers["Cache-Control"]="no-store"
    return response
@app.get("/api/research/dashboard")
def research_dashboard_api():
    global _DASH_CACHE,_DASH_AT
    with _DASH_LOCK:
        if _DASH_CACHE is not None and time.monotonic()-_DASH_AT<15:return research_response(_DASH_CACHE)
        try:
            keys=(_OCT_KEY,_STRUCT_KEY,_SEPT_KEY,_YEAR_KEY,_HALF_KEY,"research:impulse_adaptive:20260915:v2:daily_risk")
            data=store.get_many(keys)
            o=data.get(_OCT_KEY,{})
            p=data.get(_STRUCT_KEY,{})
            s=data.get(_SEPT_KEY,{})
            y=data.get(_YEAR_KEY,{})
            half=data.get(_HALF_KEY,{})
            baseline=data.get(keys[-1],{}).get("models",{}).get("M5_30m_switch",{}).get("profit_lock")
            pr=p.get("report",{})
            octnote="Общий отбор монет; семь вариантов входа/выхода. "+("Расчёт рейтинга завершён." if october_finished(o) else "После сканирования — расчёт рейтинга.")
            if o.get("complete") and not october_finished(o):octnote="Сканирование завершено; рейтинг: "+str(len(o.get("rank_done",[])))+" / "+str(len(o.get("rank_backfill",[])))+" монет."
            octmodels=[compact_model(label,o.get("result",{}).get(k)) for k,label in _RANGE_NAMES.items()]
            if o.get("rank_report",{}).get("results"):
                octnote+=" Рейтинг проверен отдельно на 16–31 октября."
                for k,v in o["rank_report"]["results"].items():octmodels.append(compact_model("16–31.10 · "+k,v,False))
            jobs=[
                {"title":"01 · Октябрь","period":"1–31 октября 2026","done":len(o.get("scanned",[])),"total":len(o.get("universe",[])) or 698,"unit":"монет","status":"complete" if october_finished(o) else "running" if o else "waiting","updated":o.get("updated"),"note":octnote,"models":octmodels},
                {"title":"02 · Сентябрь + Percoco","period":"15–21 сентября 2026","done":len(p.get("done",[])),"total":len(p.get("universe",[])) or 125,"unit":"групп свечей","status":"complete" if p.get("complete") else "running" if p else "waiting","updated":p.get("updated"),"note":"Признаки: "+str(len(p.get("rank_rows",[])))+" / 234 сигналов. "+("Проверка с 18 сентября; обучение 15–17 сентября." if p.get("complete") else "Доходность новой модели появится после расчёта."),"models":[compact_model("Исходная · 7 дней",baseline,False),compact_model("Рейтинг · 7 дней",pr.get("rank_week")),compact_model("Фильтр · 7 дней",pr.get("positive_week")),compact_model("Рейтинг · 18–21.09",pr.get("rank_test"),False),compact_model("Фильтр · 18–21.09",pr.get("positive_test"),False)]},
                {"title":"03 · Сентябрь · семь моделей","period":"15–21 сентября 2026","done":len(s.get("scanned",[])),"total":len(s.get("universe",[])) or 121,"unit":"отобранных монет","status":"complete" if s.get("complete") else "running" if s else "waiting","updated":s.get("updated"),"note":"Тот же период и риск. Пропущено: "+str(len(s.get("excluded",[])))+". "+("Исходный результат воспроизведён." if s.get("report",{}).get("baseline_reproduced") else "Сверка с исходной моделью после полного охвата."),"models":[compact_model("Исходная · архив",baseline,False),compact_model("Impulse · повтор",s.get("report",{}).get("results",{}).get("impulse_control"),False),compact_model("Impulse · без безубытка",s.get("report",{}).get("results",{}).get("impulse_no_breakeven"))]+[compact_model(label,s.get("report",{}).get("results",{}).get("range_"+k)) for k,label in _RANGE_NAMES.items()]},
                {"title":"04 · Годовой Percoco","period":_YEAR_PERIOD,"done":y.get("done",0),"total":y.get("total"),"unit":"монета-недель","status":y.get("status","queued"),"updated":y.get("updated"),"note":y.get("note","Автостарт после трёх исследований и полугодового теста риска. Адаптация M15/M1 · CHoCH · FVG 50% · цели 3R/4R. Все доступные USDT perpetual; неполная историческая вселенная."),"models":[compact_model("Percoco · "+k,v) for k,v in y.get("results",{}).items()]}
            ]
            jobs.append({"title":"05 · Динамический риск · полгода","period":_HALF_PERIOD,"done":half.get("done",0),"total":half.get("total"),"unit":"монета-месяцев","status":half.get("status","queued"),"updated":half.get("updated"),"note":half.get("note","Автостарт после трёх текущих исследований, перед годовым Percoco. Range Sweep · четыре модели риска · доступные USDT perpetual. Завершённых месячных блоков: "+str(len(half.get("months",[])))+". Пропуски: "+str(half.get("excluded",0)+half.get("gaps",0))+". Недостаточно истории: "+str(half.get("no_history",0))+". Дневной баланс только по завершённым блокам; закрытия на границе месяца."),"models":[compact_model(_HALF_MODELS[k],v) for k,v in half.get("results",{}).items()]})
            _DASH_CACHE={"server_time":time.time(),"jobs":jobs,"stale":False};_DASH_AT=time.monotonic()
            return research_response(_DASH_CACHE)
        except Exception:
            logging.warning("RESEARCH_DASHBOARD_UNAVAILABLE")
            if _DASH_CACHE is not None:return research_response(dict(_DASH_CACHE,stale=True))
            return research_response({"error":"report unavailable"},503)


# Historical-only sizing lab. Identical Range Sweep entries throughout the
# six-month period; no calls to the private trading or order APIs.
_HALF_KEY="research:dynamic_halfyear_range:v1"
_HALF_PERIOD="28.05.2026 — 27.11.2026 UTC"
_HALF_MODELS={"fixed1":"Фиксированный риск 1%","fixed3":"Фиксированный риск 3%","dynamic":"Динамический риск 1–3% по стопу","earned":"Динамический 1–3% · защита 50% прибыли"}
def halfyear_replay(events,mode,start_date,end_date):
    import heapq
    from datetime import datetime,timezone
    import pandas as pd
    cash=peak=1000.;dd=used=0.;active=[];symbols=set();days={};last_by_sym={};last_loss=-10**20;seq=trades=wins=raised=0;cur=None
    def roll(t):
        nonlocal cur
        day=int(t)//1440
        if cur!=day:
            cur=day;days[day]={"start":cash,"net":0.,"peak":0.,"streak":0,"trades":0,"entries":0}
        return days[day]
    def settle():
        nonlocal cash,peak,dd,used,trades,wins,last_loss
        end,_,sym,margin,net,reserved=heapq.heappop(active)
        d=roll(end);symbols.remove(sym);used-=margin;cash+=net
        d["net"]+=net;d["peak"]=max(d["peak"],d["net"]);d["streak"]=d["streak"]+1 if net<0 else 0;d["trades"]+=1
        if net<0:last_loss=end
        last_by_sym[sym]=(end,net);trades+=1;wins+=int(net>0);peak=max(peak,cash);dd=max(dd,1-cash/peak)
    for t,score,sym,end,e,risk,net,fee,fu in sorted(events):
        while active and active[0][0]<t:settle()
        d=roll(t)
        if len(active)>=4 or sym in symbols or cash<=20 or e<=0 or risk<=0 or t-last_loss<30:continue
        quality=.03 if risk/e>=.02 else .02 if risk/e>=.015 else .01
        reserved=sum(x[-1] for x in active)
        if mode=="fixed1":base=.01;scale=2.
        elif mode=="fixed3":base=.03;scale=6.
        elif mode=="dynamic":base=quality;scale=4.
        elif mode=="earned":base=min(quality,.01+max(0.,d["net"])*.5/cash);scale=2.
        else:raise ValueError("unknown sizing mode")
        fraction=base
        if d["streak"]>=2:fraction*=.5
        if d["streak"]>=3 or d["net"]<=-.01*scale*d["start"]:fraction=min(fraction,base*.25)
        previous=last_by_sym.get(sym)
        if previous and t-previous[0]<=240 and previous[1]<=0:fraction*=.5
        allowance=min(cash*fraction,max(0.,d["net"]+.015*scale*d["start"]-reserved))
        if mode=="earned":
            allowance=min(allowance,max(0.,.01*cash+.5*max(0.,d["net"])-reserved))
            if d["peak"]>=.01*d["start"]:allowance=min(allowance,max(0.,d["net"]-.5*d["peak"]-reserved))
        elif d["peak"]>=.0075*scale*d["start"]:
            allowance=min(allowance,max(0.,d["net"]-max(0.,d["peak"]-.005*scale*d["start"])-reserved))
        if allowance<=0:continue
        q=min(allowance/risk,max(0.,cash-used)/(e*(.1+.0006)))
        if q*e<10:continue
        margin=q*e*(.1+.0006);used+=margin;symbols.add(sym);seq+=1;d["entries"]+=1;raised+=int(q*risk/cash>.0100001)
        heapq.heappush(active,(end,seq,sym,margin,net*q,risk*q))
    while active:settle()
    lo=int(start_date.timestamp())//86400;hi=int(end_date.timestamp())//86400
    daily={};balance=1000.
    # A trade closed exactly at a monthly boundary is booked on that UTC date.
    # Include the terminal boundary only if there are actual settlements there.
    for day in range(lo,hi+int(hi in days)):
        v=days.get(day,{});pnl=v.get("net",0.);balance+=pnl
        daily[datetime.fromtimestamp(day*86400,timezone.utc).strftime("%Y-%m-%d")]={"pnl":round(pnl,4),"roi":round(100*pnl/v["start"],4) if v.get("start",0)>0 else 0.,"balance":round(balance,4),"trades":v.get("trades",0),"entries":v.get("entries",0)}
    return {"balance":round(cash,4),"roi":round(100*(cash/1000-1),4),"dd":round(100*dd,4),"trades":trades,"wins":wins,"positive_days":sum(v["pnl"]>0 for v in daily.values()),"negative_days":sum(v["pnl"]<0 for v in daily.values()),"flat_days":sum(v["pnl"]==0 for v in daily.values()),"days2":sum(v["roi"]>=2 for v in daily.values()),"higher_risk_trades":raised,"daily":daily}

def halfyear_worker():
    import numpy as np
    import pandas as pd
    import impulse_adaptive as a
    import impulse_holdout as funding_source
    import impulse_research as old
    import paper_feed
    start=pd.Timestamp("2026-05-28",tz="UTC")
    end=pd.Timestamp("2026-11-28",tz="UTC")
    def sweep(hourly,m,allowed,begin,finish):
        # Identical causal Range Sweep selection to impulse_forensics.signals.
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
                if not begin<=t<finish:continue
                f=allowed.get(t.floor("h"))
                if not f or not efficiency.get(t.floor("h"),np.nan)<=.25:continue
                entry=float(m.open.iloc[i])*(1+side*a.SLIP)
                stop=float(side*low.iloc[i-1])*(1-side*.0002);dist=side*(entry-stop)
                if not .01<=dist/entry<=.03 or side*(float(m.open.iloc[i])-stop)<=0:continue
                out.append((i,side,entry,stop,dist,float(f[1]),f[0]==side,True))
        return list({(x[0],x[1]):x for x in out}.values())
    try:
        # Keep all existing experiments intact. The long jobs share one queue.
        while True:
            states=store.get_many((_OCT_KEY,_STRUCT_KEY,_SEPT_KEY,_HALF_KEY))
            state=states.get(_HALF_KEY) or {}
            if state.get("status")=="complete":return True
            if october_finished(states.get(_OCT_KEY) or {}) and (states.get(_STRUCT_KEY) or {}).get("complete") and (states.get(_SEPT_KEY) or {}).get("complete") and not STATE.get("research_workers") and time.time()>=end.timestamp()+3900:break
            time.sleep(60)
        if not state.get("symbols"):
            meta=paper_feed.instruments()
            symbols=sorted([[sym,int(m.get("launchTime") or 0)] for sym,m in meta.items() if int(m.get("launchTime") or 0)<int(end.timestamp()*1000)])
            if not symbols:raise RuntimeError("empty universe")
            spans=[];p=start
            while p<end:
                q=min(end,(p+pd.offsets.MonthBegin(1)).normalize());spans.append([p.isoformat(),q.isoformat()]);p=q
            state={"symbols":symbols,"spans":spans,"cursor":0,"done":0,"total":len(symbols)*len(spans),"pending":[],"event_keys":[],"results":{},"months":[],"excluded":0,"gaps":0,"no_history":0}
        def save():
            state["updated"]=time.time();old.db_put(_HALF_KEY,state)
        state["status"]="running";save()
        symbols=state["symbols"];spans=state["spans"];n=len(symbols)
        while state["cursor"]<state["total"]:
            cursor=state["cursor"];mi,si=divmod(cursor,n)
            begin,finish=map(pd.Timestamp,spans[mi]);sym,launch=symbols[si]
            listed=pd.Timestamp(launch,unit="ms",tz="UTC").ceil("h")
            # Existing eligibility needs 31 days of prior volume.
            if listed+pd.Timedelta(days=31)>=finish:state["no_history"]+=1
            else:
                hs=max(begin-pd.Timedelta(days=32),listed)
                hourly=a.window(sym,60,hs,finish)
                if hourly is None:state["excluded"]+=1
                else:
                    allowed=a.eligible(hourly,begin,finish)
                    if allowed:
                        # Only fetch M5 around eligible hours, with enough preceding
                        # bars for the range and volume and enough trailing bars.
                        windows=[]
                        for t in sorted(allowed):
                            lo=max(t-pd.Timedelta(minutes=120),listed)
                            hi=min(finish+pd.Timedelta(minutes=65),t+pd.Timedelta(minutes=125))
                            if windows and (lo<=windows[-1][1] or hi-windows[-1][0]<=pd.Timedelta(minutes=5000)):
                                windows[-1]=(windows[-1][0],max(windows[-1][1],hi))
                            else:windows.append((lo,hi))
                        rates=None;seen=set()
                        for lo,hi in windows:
                            m=a.window(sym,5,lo,hi)
                            if m is None:state["gaps"]+=1;continue
                            ss=sweep(hourly,m,allowed,begin,finish)
                            # Never duplicate an entry if overlapping windows exist.
                            ss=[x for x in ss if (m.index[x[0]],x[1]) not in seen]
                            if ss:
                                if rates is None:rates=funding_source.funding(sym,begin,finish)
                                if not rates:state["excluded"]+=1;break
                                for x in ss:seen.add((m.index[x[0]],x[1]))
                                state["pending"].extend(a.exits(sym,m,ss,rates,6,2,1,"switch",end=finish))
                            del m
                del hourly
            state["cursor"]=cursor+1;state["done"]=cursor+1
            if si==n-1:
                # Persist only derived candidate outcomes, never raw candles.
                ek=_HALF_KEY+":events:"+str(mi)
                old.db_put(ek,{"events":state["pending"]})
                if ek not in state["event_keys"]:state["event_keys"].append(ek)
                state["pending"]=[]
                events=[]
                for record in store.get_many(state["event_keys"]).values():events.extend(record["events"])
                state["results"]={k:halfyear_replay(events,k,start,finish) for k in _HALF_MODELS}
                state["months"].append(finish.isoformat());del events
            state["status"]="complete" if state["done"]==state["total"] else "running"
            save()
            if cursor%10==0 or si==n-1:
                print("HALFYEAR_DYNAMIC_PROGRESS "+json.dumps({"done":state["done"],"total":state["total"],"status":state["status"],"months":len(state["months"]),"excluded":state["excluded"],"gaps":state["gaps"],"no_history":state["no_history"],"results":{k:{n:v[n] for n in ("roi","dd","balance","trades","positive_days","negative_days","days2")} for k,v in state["results"].items()}},separators=(",",":")),flush=True)
        return True
    except Exception:
        logging.exception("HALFYEAR_DYNAMIC_FAILED")
        try:
            state=store.get(_HALF_KEY) or {}
            state.update(status="error",updated=time.time(),note="Ошибка исследования; контрольная точка сохранена.")
            store.put(_HALF_KEY,state)
        except Exception:pass
        return False

def long_research_queue():
    # User requested the six-month sizing test; execute before the previously
    # queued annual M1 experiment, without extra concurrent candle scanners.
    halfyear_worker()
    yearly_percoco_worker()


# Yearly test: deterministic, explicitly approximate rules derived from the
# known video summary; not a claim of exact reproduction. No live orders.
def yearly_percoco_worker():
    import math
    import pandas as pd
    import impulse_adaptive as a
    import impulse_daily_risk as dr
    import impulse_research as old
    import paper_feed
    start=pd.Timestamp("2025-11-21",tz="UTC")
    end=pd.Timestamp("2026-11-21",tz="UTC")
    targets=("3R","4R")
    def structure(frame):
        # A pivot is only known after two candles on its right close.
        rows=frame[["open","high","low","close"]].to_numpy()
        hi=[];lo=[];last_h=last_l=-1;direction=0;out=[]
        for i,b in enumerate(rows):
            if i>=4:
                p=i-2
                if rows[p,1]>max(rows[j,1] for j in (p-2,p-1,p+1,p+2)):hi.append((p,float(rows[p,1])))
                if rows[p,2]<min(rows[j,2] for j in (p-2,p-1,p+1,p+2)):lo.append((p,float(rows[p,2])))
            change=0
            if hi and b[3]>hi[-1][1] and last_h!=hi[-1][0]:
                if direction==-1:change=1
                direction=1;last_h=hi[-1][0]
            if lo and b[3]<lo[-1][1] and last_l!=lo[-1][0]:
                if direction==1:change=-1
                direction=-1;last_l=lo[-1][0]
            trend=0
            if len(hi)>1 and len(lo)>1:
                if direction==1 and hi[-1][1]>hi[-2][1] and lo[-1][1]>lo[-2][1]:trend=1
                if direction==-1 and hi[-1][1]<hi[-2][1] and lo[-1][1]<lo[-2][1]:trend=-1
            out.append((trend,change,lo[-1][1] if lo else None,hi[-1][1] if hi else None))
        return out
    def signals(sym,frame,trends,begin,finish,month_end,launch):
        out={k:[] for k in targets}
        st=structure(frame);bars=frame[["open","high","low","close"]].to_numpy();ts=frame.index
        setups=[]
        for i in range(4,len(frame)-1):
            t=ts[i]+pd.Timedelta(minutes=1)
            if t<begin or t>=finish:continue
            trend,score=trends.get(t.floor("15min"),(0,0.))
            side=st[i][1]
            if not side or side!=trend:continue
            # First directional FVG at or within 10 closed minutes of CHoCH.
            for j in range(i,min(i+11,len(frame)-1)):
                known=ts[j]+pd.Timedelta(minutes=1)
                if trends.get(known.floor("15min"),(0,0))[0]!=side:break
                gap=(bars[j,2]-bars[j-2,1]) if side==1 else (bars[j-2,2]-bars[j,1])
                if gap<=0:continue
                level=float((bars[j,2]+bars[j-2,1])/2 if side==1 else (bars[j-2,2]+bars[j,1])/2)
                stop=st[j][2] if side==1 else st[j][3]
                if stop is None or side*(level-stop)<=0:break
                # Conservative execution friction, no arbitrary widening of stop.
                e=level*(1+side*a.SLIP);stop=float(stop)*(1-side*.0002);dist=side*(e-stop)
                if not 0<dist/e<=.03 or 2*(a.F+a.SLIP)*e/dist>=1:break
                for k in range(j+1,min(j+31,len(frame))):
                    if ts[k]>=finish or ts[k]>=month_end:break
                    if trends.get(ts[k].floor("15min"),(0,0))[0]!=side:break
                    # A stop touched before limit entry invalidates the order.
                    # If both touched in one candle, count a conservative stop.
                    fill=bars[k,2]<=level if side==1 else bars[k,1]>=level
                    invalid=side*(float(bars[k,2] if side==1 else bars[k,1])-stop)<=0
                    if fill:
                        setups.append((k,side,e,stop,dist,score));break
                    if invalid:break
                break
        if not setups:return out,False
        # Exact funding history for the window; at most 7 days plus lookahead.
        lo=int(begin.timestamp()*1000);hi=int(min(month_end,finish+pd.Timedelta(hours=3)).timestamp()*1000)
        rates={};p=lo
        while p<hi:
            q=min(hi,p+3*86400000)
            raw=a.get("funding/history",symbol=sym,startTime=p,endTime=q-1,limit=200).get("list",[])
            if len(raw)>=200:return out,True
            for row in raw:rates[int(row["fundingRateTimestamp"])//60000]=float(row["fundingRate"])
            p=q
        if not rates:return out,True
        seen=set()
        for k,side,e,stop,dist,score in setups:
            if (k,side) in seen:continue
            seen.add((k,side))
            risk=dist+a.F*(e+stop)+a.SLIP*stop
            for target in targets:
                tp=e+side*int(target[0])*dist
                fu=0.;last=min(k+120,len(frame)-1)
                for j in range(k,last+1):
                    op,h,l,cl=bars[j];minute=int(ts[j].timestamp()/60)
                    if j>k and minute in rates:fu+=side*op*rates[minute]
                    if j>k and (ts[j]>=month_end or j==k+120):px=op;break
                    if j>k and side*(op-stop)<=0:px=op;break
                    if j>k and side*(op-tp)>=0:px=tp;break
                    if (l<=stop if side==1 else h>=stop):px=stop;break
                    # Do not award a target in the limit-fill candle.
                    if j>k and (h>=tp if side==1 else l<=tp):px=tp;break
                    if j==last:px=cl;break
                ex=px*(1-side*a.SLIP);fee=a.F*(e+ex)
                out[target].append([int(ts[k].timestamp()/60),-float(score),sym,int(ts[j].timestamp()/60),float(e),float(risk),float(side*(ex-e)-fee-fu),float(fee),float(fu)])
        return out,False
    try:
        # Wait for the full October ranking, not just its candle scan.
        while True:
            states=store.get_many((_OCT_KEY,_STRUCT_KEY,_SEPT_KEY,_YEAR_KEY))
            state=states.get(_YEAR_KEY,{})
            if state.get("status")=="complete":return
            if october_finished(states.get(_OCT_KEY,{})) and states.get(_STRUCT_KEY,{}).get("complete") and states.get(_SEPT_KEY,{}).get("complete") and not STATE.get("research_workers"):break
            time.sleep(60)
        # Freeze the currently available perpetual universe; delisted contracts
        # cannot be reconstructed from current metadata, so disclose coverage.
        if not state.get("symbols"):
            meta=paper_feed.instruments()
            symbols=sorted([[sym,int(m.get("launchTime") or 0)] for sym,m in meta.items() if int(m.get("launchTime") or 0)<int(end.timestamp()*1000)])
            if not symbols:raise RuntimeError("empty universe")
            spans=[];p=start
            while p<end:
                me=min(end,(p+pd.offsets.MonthBegin(1)).normalize())
                q=p
                while q<me:
                    nxt=min(me,q+pd.Timedelta(days=7));spans.append([q.isoformat(),nxt.isoformat(),me.isoformat()]);q=nxt
                p=me
            state={"symbols":symbols,"spans":spans,"done":0,"total":len(symbols)*len(spans),"cursor":0,"status":"running","results":{},"months":[],"event_keys":[],"excluded":0,"gaps":0,"no_history":0}
        def save(note):
            state["note"]=note;state["updated"]=time.time();old.db_put(_YEAR_KEY,state)
        state["status"]="running";save("M15 структура HH/HL и LL/LH → M1 CHoCH → FVG 50%. Адаптация; неполная историческая вселенная. ROI только завершённых месяцев.")
        symbols=state["symbols"];spans=state["spans"];n=len(symbols)
        while state["cursor"]<state["total"]:
            cursor=state["cursor"];wi,si=divmod(cursor,n)
            begin,finish,month_end=map(pd.Timestamp,spans[wi]);sym,launch=symbols[si]
            if launch>=int(finish.timestamp()*1000):state["no_history"]+=1
            else:
                hs=max(begin-pd.Timedelta(days=2),pd.Timestamp(launch,unit="ms",tz="UTC").ceil("15min"))
                # M15 bars are scanned across the entire available market.
                h=a.window(sym,15,hs,min(month_end,finish+pd.Timedelta(hours=3))) if hs<finish else None
                if h is None:state["excluded"]+=1
                else:
                    marks=structure(h);rv=h.volume/h.volume.shift(1).rolling(20).mean()
                    trends={}
                    for idx,(trend,_,_,_) in enumerate(marks):
                        known=h.index[idx]+pd.Timedelta(minutes=15)
                        if trend and pd.notna(rv.iloc[idx]):trends[known]=(trend,float(rv.iloc[idx]))
                    windows=[]
                    for t in sorted(trends):
                        if not begin<=t<finish:continue
                        lo=max(t-pd.Timedelta(hours=2),pd.Timestamp(launch,unit="ms",tz="UTC").ceil("min"));hi=min(month_end+pd.Timedelta(minutes=1),t+pd.Timedelta(hours=3))
                        if windows and lo<=windows[-1][1]:windows[-1]=(windows[-1][0],max(windows[-1][1],hi))
                        else:windows.append((lo,hi))
                    ev={k:[] for k in targets}
                    for lo,hi in windows:
                        m=a.window(sym,1,lo,hi)
                        if m is None:state["gaps"]+=1;continue
                        x,missing=signals(sym,m,trends,begin,finish,month_end,launch)
                        if missing:state["gaps"]+=1
                        for k in targets:ev[k].extend(x[k])
                        del m
                    if any(ev.values()):
                        ek=_YEAR_KEY+":events:"+str(cursor)
                        old.db_put(ek,ev)
                        if ek not in state["event_keys"]:state["event_keys"].append(ek)
                    del h
                    # Event batches have already been checkpointed.
            state["cursor"]=cursor+1;state["done"]=cursor+1
            # Replay only complete month blocks over all scanned symbols. Each
            # strategy compounds its own balance. Positions are closed at month
            # end; daily-equity DD is reported explicitly, not intraday DD.
            if si==n-1 and finish==month_end:
                events={k:[] for k in targets}
                for p in range(0,len(state["event_keys"]),30):
                    data=store.get_many(state["event_keys"][p:p+30])
                    for record in data.values():
                        for k in targets:events[k].extend(record[k])
                month={}
                for k in targets:
                    prev=state["results"].get(k,{})
                    cash=float(prev.get("balance",1000.))
                    rr=dr.replay(events[k],"profit_lock",start=cash)
                    peak=float(prev.get("daily_peak",1000.));dd=float(prev.get("dd",0.))
                    equity=cash
                    for day,v in sorted(rr["daily"].items()):
                        equity+=v["pnl"];peak=max(peak,equity)
                        if peak>0:dd=max(dd,100*(1-equity/peak))
                    equity=rr["balance"];peak=max(peak,equity)
                    if peak>0:dd=max(dd,100*(1-equity/peak))
                    daily=dict(prev.get("daily",{}))
                    month_begin=pd.Timestamp(spans[wi][0]).normalize().replace(day=1)
                    month_begin=max(start,month_begin)
                    for day in pd.date_range(month_begin,month_end-pd.Timedelta(days=1),freq="D"):
                        daily.setdefault(day.strftime("%Y-%m-%d"),{"pnl":0.,"roi":0.,"trades":0})
                    for day,v in rr["daily"].items():
                        d=daily.setdefault(day,{"pnl":0.,"roi":0.,"trades":0})
                        d["pnl"]+=v["pnl"];d["trades"]+=v["trades"]
                    bal=1000.
                    for day,v in sorted(daily.items()):
                        v["roi"]=100*v["pnl"]/bal if bal>0 else 0.;bal+=v["pnl"];v["balance"]=round(bal,4)
                    state["results"][k]={"balance":rr["balance"],"roi":100*(rr["balance"]/1000-1),"dd":dd,"daily_peak":peak,"trades":prev.get("trades",0)+rr["trades"],"wins":prev.get("wins",0)+rr["wins"],"daily":daily}
                    month[k]={z:rr[z] for z in ("balance","roi","trades","wins")}
                state["months"].append({"end":month_end.isoformat(),"result":month})
                state["event_keys"]=[];del events
            state["status"]="complete" if state["done"]==state["total"] else "running"
            save("Адаптация M15/M1 · 3R/4R · максимум 4 позиции · риск 0,5% с защитой прибыли. Завершённых месячных блоков: "+str(len(state["months"]))+". Нет истории: "+str(state["no_history"])+", пропуски M15/M1 или funding: "+str(state["excluded"]+state["gaps"])+". DD по дневному балансу; принудительное закрытие на границе месяца.")
            print("YEAR_PERCOCO_PROGRESS "+json.dumps({k:state[k] for k in ("done","total","status","results","excluded","gaps","no_history")},separators=(",",":")),flush=True)
    except Exception:
        logging.exception("YEAR_PERCOCO_FAILED")
        try:
            state=store.get(_YEAR_KEY,{})
            state.update(status="error",updated=time.time(),note="Исследование приостановлено из-за ошибки. Чекпоинт сохранён; восстановление при следующем запуске.")
            store.put(_YEAR_KEY,state)
        except Exception:pass

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
        threading.Thread(target=long_research_queue,daemon=True,name="long-research-queue").start()
        bybit_demo.worker()
    except BaseException:
        logging.exception("CLEAN BASE worker failed")
        os._exit(1)
if __name__=="__main__":
    threading.Thread(target=start_workers,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=4)
