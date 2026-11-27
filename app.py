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
# Read-only bridge to the separate research service. No Bybit calls here.
RESEARCH_URL="https://smart-trader-research.onrender.com/status"
_research_lock=threading.Lock()
_research_cache={"data":None,"fetched_at":None,"checked_at":0,"error":None}
@app.get("/api/research/impulse")
def impulse_research():
    now=time.time()
    if now-_research_cache["checked_at"]>=10 and _research_lock.acquire(blocking=False):
        try:
            if time.time()-_research_cache["checked_at"]>=10:
                _research_cache["checked_at"]=time.time()
                try:
                    r=requests.get(RESEARCH_URL,timeout=(2,4))
                    r.raise_for_status()
                    d=r.json()
                    if not isinstance(d,dict) or not isinstance(d.get("status"),dict) or not isinstance(d.get("results"),dict):
                        raise ValueError("Invalid research response")
                    _research_cache.update(data=d,fetched_at=time.time(),error=None)
                except Exception:
                    _research_cache["error"]="Исследовательский сервер временно недоступен"
        finally:
            _research_lock.release()
    return jsonify({"data":_research_cache["data"],"fetched_at":_research_cache["fetched_at"],"error":_research_cache["error"]})
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
        bybit_demo.worker()
    except BaseException:
        logging.exception("CLEAN BASE worker failed")
        os._exit(1)
if __name__=="__main__":
    threading.Thread(target=start_workers,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=4)
