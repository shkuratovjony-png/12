"""Free-tier research service; no live execution or private Bybit API."""
import os,time,threading,subprocess,sys,json,logging
from flask import Flask,jsonify,render_template_string
from waitress import serve
import store,market,risk
app=Flask(__name__)
logging.basicConfig(level=logging.INFO)
STATE={"status":"starting","error":None,"last_poll":None,"training":None}
store.init()
if store.get("paper") is None:store.put("paper",risk.initial())

def run_job(mode,symbol):
    p=subprocess.run([sys.executable,"research.py",mode,symbol],capture_output=True,text=True,timeout=240)
    if p.returncode:raise RuntimeError((p.stderr or p.stdout or "research failed")[-500:])
    return p.stdout.strip().splitlines()[-1]

def worker():
    last_train=0
    while True:
        try:
            s=store.get("paper",risk.initial())
            if s["position"]:
                bid,ask=market.quote(s["position"]["symbol"])
                risk.mark(s,bid,ask)
                store.put("paper",s)
            for sym in market.SYMBOLS:
                old=store.get("candles:"+sym,[])
                rows=market.candles(sym,3 if len(old)<800 else 1)
                if not rows:continue
                bar=rows[-1][0]
                if s["last_signals"].get(sym)==bar:continue
                s["last_signals"][sym]=bar
                # Only a fresh completed bar can generate a prospective paper entry.
                fresh=0<=time.time()*1000-(bar+market.BAR)<=120000
                ch=store.get("champion:"+sym)
                if fresh and ch and risk.entry_allowed(s):
                    side=int(run_job("signal",sym))
                    if side:
                        bid,ask=market.quote(sym)
                        risk.entry(s,sym,side,bid,ask,ch["version"])
                store.put("paper",s)
            now=time.time()
            if not s["position"] and now-last_train>300:
                for sym in market.SYMBOLS:
                    report=store.get("report:"+sym,{})
                    if now-report.get("time",0)>86400 and len(store.get("candles:"+sym,[]))>=800:
                        last_train=now
                        STATE["training"]=sym
                        try:run_job("train",sym)
                        finally:STATE["training"]=None
                        break
            STATE.update(status="running",error=None,last_poll=time.time())
        except Exception as e:
            logging.exception("worker error")
            STATE.update(status="degraded",error=type(e).__name__+": "+str(e)[:250])
            # Retry with backoff; do not open trades on failed market data.
        time.sleep(45)

@app.get("/health")
def health():return {"service":"smart-trader-ai","mode":"paper","status":STATE["status"]}

@app.get("/api/status")
def status():
    s=store.get("paper",risk.initial())
    return jsonify(mode="PAPER ONLY",target_daily=0.10,storage="postgres" if store.URL else "ephemeral_sqlite",
                   state=STATE,balance=s["balance"],equity=s["equity"],peak=s["peak"],halted=s["halted"],
                   position=s["position"],trades=s["trades"][-30:],
                   symbols=[{"symbol":k,"bars":len(store.get("candles:"+k,[])),"report":store.get("report:"+k)} for k in market.SYMBOLS])

PAGE="""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMART TRADER AI</title><style>
body{font:16px system-ui;background:#10151d;color:#e8edf5;max-width:960px;margin:32px auto;padding:0 18px}
h1{font-size:30px}section{background:#1b2431;padding:20px;border:1px solid #324054;border-radius:14px;margin:12px 0}
small{color:#aab7ca}pre{white-space:pre-wrap;overflow-wrap:anywhere}strong{font-size:24px}
</style><h1>SMART TRADER AI</h1><p>Исследовательская лаборатория · только виртуальные сделки</p>
<section><small>Виртуальный капитал</small><br><strong id="equity">—</strong><p id="status">Загрузка…</p><small>Цель исследования 10%/сутки; не прогноз. Лимит дневного убытка 3%, просадка 15%, одна позиция без плеча. При сне сервера мониторинг прекращается.</small></section>
<section><h2>Рынок и модели</h2><pre id="models">—</pre></section><section><h2>Последние виртуальные сделки</h2><pre id="trades">—</pre></section>
<script>async function update(){try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);let j=await r.json();
document.getElementById('equity').textContent='$'+j.equity.toFixed(2);
document.getElementById('status').textContent=j.mode+' | '+j.storage+' | '+j.state.status+(j.state.error?' | '+j.state.error:'');
document.getElementById('models').textContent=JSON.stringify(j.symbols,null,2);
document.getElementById('trades').textContent=JSON.stringify(j.trades,null,2);
}catch(e){document.getElementById('status').textContent=String(e)}}update();setInterval(update,30000)</script></html>"""
@app.get("/")
def dashboard():return render_template_string(PAGE)

if __name__=="__main__":
    threading.Thread(target=worker,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=2)
