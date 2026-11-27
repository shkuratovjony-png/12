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
def start_impulse():
    time.sleep(15)
    try:
        if not store.URL:
            logging.error("IMPULSE_DISABLED: persistent PostgreSQL unavailable")
            return
        import impulse_research
        STATE["research_workers"]=1
        logging.info("IMPULSE_START: shared API, durable PostgreSQL, read-only")
        import impulse_adaptive
        saved=store.get(impulse_research.CHECKPOINT_KEY)
        if saved:
            impulse_research.diagnostics(saved['events'],len(saved['scanned']),len(saved['universe']),len(saved['scanned'])==len(saved['universe']))
        try:
            impulse_adaptive.run(pilot=True)
        except Exception:
            logging.exception('ADAPTIVE_PILOT_ERROR')
        impulse_research.run()
        saved_report=store.get(impulse_research.REPORT_KEY) or {}
        if saved_report.get('results',{}).get('Cameron_5x_10pct',{}).get('complete'):
            impulse_adaptive.run()
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
