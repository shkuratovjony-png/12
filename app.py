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
            return research_response({**meta,"models":{m:len(research_rows(state,m)) for m in models},"event_fields":EVENT_FIELDS})
        rows=research_rows(state,model);snapshot=research_snapshot(rows)
        expected=request.args.get("snapshot")
        if expected and expected!=snapshot:return research_response({"error":"snapshot changed; restart pagination"},409)
        return research_response({**meta,"model":model,"snapshot":snapshot,"total":len(rows),"offset":offset,"next_offset":offset+limit if offset+limit<len(rows) else None,"rows":rows[offset:offset+limit],"event_fields":EVENT_FIELDS})
    except Exception:
        logging.warning("RESEARCH_ARCHIVE_READ_FAILED")
        return research_response({"error":"archive unavailable"},503)
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
        bybit_demo.worker()
    except BaseException:
        logging.exception("CLEAN BASE worker failed")
        os._exit(1)
if __name__=="__main__":
    threading.Thread(target=start_workers,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=4)
