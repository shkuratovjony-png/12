"""Clean demo foundation: no legacy strategy workers, no training, no new orders."""
import os,time,threading,logging
from flask import Flask,jsonify,send_from_directory
from waitress import serve
import store,market,bybit_demo,sir_live,sir_paper,breakout_paper,sergey_paper
app=Flask(__name__)
logging.basicConfig(level=logging.INFO)
STATE={"status":"starting","version":"sir-demo-v1.3-sergey","mode":"demo","entries_enabled":True,"research_workers":0,"strategies":["sir_short_v1","sir_long_experimental_v1"]}
def payload():
    return {"state":dict(STATE),"demo":dict(bybit_demo.VIEW),"demo_detail":bybit_demo.DASH_VIEW,"market":market.feed_status(),"server_time":time.time(),"archive_preserved":True,"sir":sir_live.VIEW,"paper":{**sir_paper.VIEW,"breakout":breakout_paper.VIEW,"sergey":sergey_paper.VIEW}}
@app.get("/health")
def health():
    return {"service":"smart-trader-ai","status":STATE["status"],"mode":"demo"}
@app.get("/api/status")
@app.get("/api/cabinet")
@app.get("/api/overview")
def status():return jsonify(payload())
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
        logging.info("SIR DEMO ready: legacy entries disabled; isolated strategy registry; database retained")
        threading.Thread(target=sir_paper.worker,daemon=True,name="sir-paper").start()
        threading.Thread(target=breakout_paper.worker,daemon=True,name="breakout-paper").start()
        threading.Thread(target=sergey_paper.worker,daemon=True,name="sergey-paper").start()
        bybit_demo.worker()
    except BaseException:
        logging.exception("CLEAN BASE worker failed")
        os._exit(1)
if __name__=="__main__":
    threading.Thread(target=start_workers,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=4)
