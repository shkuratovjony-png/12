"""Always-on bounded autonomous research, paper only; never submits exchange orders."""
import os,time,threading,subprocess,sys,json,logging
from flask import Flask,jsonify,render_template_string
from waitress import serve
import store,market,risk,market_lab
app=Flask(__name__)
logging.basicConfig(level=logging.INFO)
STATE={"status":"starting","error":None,"last_poll":None,"training":None,"version":"autonomous-research-v0.4","symbol_errors":{}}
store.init()
if store.get("paper") is None:store.put("paper",risk.initial())

def run_job(mode,symbol):
    script="autolab.py" if mode=="evolve" else "research.py"
    p=subprocess.run([sys.executable,script,mode,symbol],capture_output=True,text=True,timeout=240)
    if p.returncode:raise RuntimeError((p.stderr or p.stdout or "research failed")[-500:])
    return p.stdout.strip().splitlines()[-1]

def market_worker():
    while True:
        failures={}
        try:
            active=market.load_universe()
            s=store.get("paper",risk.initial())
            if s["position"]:
                try:
                    bid,ask=market.quote(s["position"]["symbol"])
                    risk.mark(s,bid,ask)
                except Exception as exc:
                    failures["position_quote"]=type(exc).__name__+": "+str(exc)[:150]
            for sym in active:
                try:
                    old=store.get("candles:"+sym,[])
                    rows=market.candles(sym,3 if len(old)<800 else 1)
                    if not rows:continue
                    bar=rows[-1][0]
                    if s["last_signals"].get(sym)==bar:continue
                    s["last_signals"][sym]=bar
                    fresh=0<=time.time()*1000-(bar+market.BAR)<=120000
                    champion=store.get("champion:"+sym)
                    if fresh and champion and risk.entry_allowed(s):
                        side=int(run_job("signal",sym))
                        if side in (-1,1):
                            bid,ask=market.quote(sym)
                            risk.entry(s,sym,side,bid,ask,champion["version"])
                except Exception as exc:
                    failures[sym]=type(exc).__name__+": "+str(exc)[:150]
            store.put("paper",s)
            STATE.update(status="degraded" if failures else "running",error=None,
                         symbol_errors=failures,last_poll=time.time())
        except Exception as exc:
            logging.exception("market worker error")
            STATE.update(status="degraded",error=type(exc).__name__+": "+str(exc)[:180],
                         symbol_errors=failures,last_poll=time.time())
        time.sleep(45)

def trainer_worker():
    attempts={}
    while True:
        try:
            # Dedicated process keeps risk polling responsive.
            for sym in list(market.SYMBOLS):
                now=time.time()
                brain=store.get("autolab:"+sym,{})
                if now-brain.get("last_cycle",0)<86400 or now-attempts.get(sym,0)<3600:continue
                if len(store.get("candles:"+sym,[]))<800:continue
                attempts[sym]=now
                STATE["training"]=sym
                try:
                    outcome=json.loads(run_job("evolve",sym))
                    store.put("last_training_result",{"symbol":sym,"time":time.time(),
                        "selected":outcome.get("selected"),"approved":outcome.get("approved"),
                        "generation":outcome.get("generation"),"candidates":outcome.get("candidates"),
                        "validation":outcome.get("validation"),"holdout":outcome.get("holdout")})
                except Exception as exc:
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

@app.get("/health")
def health():return {"service":"smart-trader-ai","mode":"paper","status":STATE["status"]}

@app.get("/api/status")
def status():
    s=store.get("paper",risk.initial())
    return jsonify(mode="PAPER ONLY",target_daily=0.10,storage="postgres" if store.URL else "ephemeral_sqlite",
                   universe=store.get("research_universe",{}),micro_status=store.get("micro_status"),arbitrage=store.get("arb_scan"),latest_training=store.get("last_training_result"),
                   recent_research=store.get("research_history",[])[-12:],
                   state=STATE,balance=s["balance"],equity=s["equity"],peak=s["peak"],halted=s["halted"],
                   position=s["position"],trades=s["trades"][-30:],
                   symbols=[{"symbol":k,"bars":len(store.get("candles:"+k,[])),"micro_bars":len(store.get("micro:"+k,[])),
                     "brain":{key:value for key,value in store.get("autolab:"+k,{}).items() if key!="archive"},
                     "report":store.get("report:"+k)} for k in market.SYMBOLS])

PAGE="""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMART TRADER AI</title><style>
body{font:16px system-ui;background:#10151d;color:#e8edf5;max-width:960px;margin:32px auto;padding:0 18px}
h1{font-size:30px}section{background:#1b2431;padding:20px;border:1px solid #324054;border-radius:14px;margin:12px 0}
small{color:#aab7ca}pre{white-space:pre-wrap;overflow-wrap:anywhere}strong{font-size:24px}
</style><h1>SMART TRADER AI</h1><p>Исследовательская лаборатория · только виртуальные сделки</p>
<section><small>Виртуальный капитал</small><br><strong id="equity">—</strong><p id="status">Загрузка…</p><small>Цель исследования 10%/сутки; не прогноз. Лимит дневного убытка 3%, просадка 15%, одна позиция без плеча. При сне сервера мониторинг прекращается.</small></section>
<section><h2>Автономные исследования</h2><pre id="research">—</pre><small>Новые стратегии создаются из безопасных правил и проверяются на истории. Положительная история не гарантирует прибыль в будущем.</small></section>
<section><h2>Рынок и модели</h2><pre id="models">—</pre></section><section><h2>Последние виртуальные сделки</h2><pre id="trades">—</pre></section>
<script>async function update(){try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);let j=await r.json();
document.getElementById('equity').textContent='$'+j.equity.toFixed(2);
document.getElementById('status').textContent=j.mode+' | '+j.storage+' | '+j.state.status+(j.state.error?' | '+j.state.error:'');
document.getElementById('research').textContent=JSON.stringify({latest_training:j.latest_training,recent:j.recent_research,micro:j.micro_status,arbitrage:j.arbitrage},null,2);
document.getElementById('models').textContent=JSON.stringify(j.symbols,null,2);
document.getElementById('trades').textContent=JSON.stringify(j.trades,null,2);
}catch(e){document.getElementById('status').textContent=String(e)}}update();setInterval(update,30000)</script></html>"""
@app.get("/")
def dashboard():return render_template_string(PAGE)

if __name__=="__main__":
    threading.Thread(target=market_lab.stream_worker,daemon=True).start()
    threading.Thread(target=market_lab.collector,daemon=True).start()
    threading.Thread(target=market_worker,daemon=True).start()
    threading.Thread(target=trainer_worker,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=2)
