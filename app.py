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
        bybit_demo.worker()
    except BaseException:
        logging.exception("CLEAN BASE worker failed")
        os._exit(1)
if __name__=="__main__":
    threading.Thread(target=start_workers,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=4)
