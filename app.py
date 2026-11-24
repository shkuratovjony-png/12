"""Always-on bounded autonomous research, paper only; never submits exchange orders."""
import os,time,threading,subprocess,sys,json,logging
from flask import Flask,jsonify,render_template_string
from datetime import datetime,timezone
from waitress import serve
import store,market,risk,market_lab
app=Flask(__name__)
logging.basicConfig(level=logging.INFO)
STATE={"status":"starting","error":None,"last_poll":None,"training":None,"version":"autonomous-research-v0.4.1","symbol_errors":{}}
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

def market_worker():
    while True:
        failures={}
        try:
            active=market.load_universe()
            s=store.get("paper",risk.initial())
            risk.roll(s)
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
                            if risk.entry(s,sym,side,bid,ask,champion["version"]):
                                s["position"]["strategy"]=champion.get("strategy")
                                s["position"]["strategy_id"]=champion.get("id")
                except Exception as exc:
                    failures[sym]=type(exc).__name__+": "+str(exc)[:150]
            store.put("paper",s)
            record_equity(s)
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
    risk.roll(s)
    return jsonify(mode="PAPER ONLY",target_daily=risk.TARGET_DAILY,start=risk.START,day=s["day"],day_start=s["day_start"],equity_history=store.get("equity_history",[]),storage="postgres" if store.URL else "ephemeral_sqlite",
                   universe=store.get("research_universe",{}),micro_status=store.get("micro_status"),arbitrage=store.get("arb_scan"),latest_training=store.get("last_training_result"),
                   recent_research=store.get("research_history",[]),
                   state=STATE,balance=s["balance"],equity=s["equity"],peak=s["peak"],halted=s["halted"],
                   position=s["position"],trades=s["trades"],
                   symbols=[{"symbol":k,"bars":len(store.get("candles:"+k,[])),"micro_bars":len(store.get("micro:"+k,[])),
                     "brain":{key:value for key,value in store.get("autolab:"+k,{}).items() if key!="archive"},
                     "report":store.get("report:"+k),"champion":store.get("champion:"+k),"latest_micro":(store.get("micro:"+k,[]) or [None])[-1]} for k in market.SYMBOLS])

PAGE=r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SMART TRADER AI — кабинет</title>
<style>
:root{color-scheme:dark;--bg:#0b1019;--card:#141e2b;--line:#28384b;--text:#edf4fb;--muted:#98a9bf;--up:#53e0ae;--down:#ff8a98;--blue:#78aaff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}main{max-width:1280px;margin:auto;padding:22px}header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}h1{font-size:24px;margin:0}h2{font-size:17px;margin:0 0 14px}h3{font-size:15px;margin:0 0 8px}p{margin:8px 0}small,.muted{color:var(--muted)}.tag{font-size:11px;letter-spacing:.08em;background:#193a35;color:var(--up);padding:6px 10px;border-radius:20px}nav{display:flex;gap:8px;overflow:auto;margin:22px 0}nav a{padding:9px 13px;border:1px solid var(--line);border-radius:8px;color:var(--text);text-decoration:none;white-space:nowrap}section,.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:17px;margin-bottom:14px}section{scroll-margin-top:10px}.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.tile{margin:0}.metric{font-size:clamp(18px,3vw,31px);font-weight:700;font-variant-numeric:tabular-nums;margin-top:8px;overflow-wrap:anywhere}.up{color:var(--up)}.down{color:var(--down)}.split{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-top:14px}.bar{height:10px;border-radius:8px;background:#263447;overflow:hidden;margin:14px 0}.bar div{height:100%;background:var(--up);width:0}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left;font-variant-numeric:tabular-nums}th,td{padding:11px 9px;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}th{color:var(--muted);font-weight:500}td.wrap{white-space:normal;min-width:180px}.empty{padding:20px;color:var(--muted);text-align:center}button,select{background:#1d2b3e;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit}.chart{width:100%;height:220px;display:block}.subgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.model{padding:13px;border:1px solid var(--line);border-radius:9px;overflow-wrap:anywhere}.pill{font-size:12px;background:#27384b;padding:4px 7px;border-radius:5px;display:inline-block;margin:3px}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}.warn{color:#ffd18a}.chartnote{min-height:20px}footer{color:var(--muted);font-size:12px;padding-bottom:20px}@media(max-width:760px){main{padding:13px}.tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.tile,section{padding:12px}.split,.subgrid{grid-template-columns:1fr}.metric{font-size:23px}.chart{height:190px}}
</style></head><body><main>
<header><div><h1>SMART TRADER AI</h1><p class="muted">Лаборатория автономной торговли · Bybit</p></div><div><span class="tag">PAPER ONLY</span><p id="health" class="muted">Получение данных…</p></div></header>
<nav><a href="#overview">Обзор</a><a href="#trading">Сделки</a><a href="#lab">Стратегии</a><a href="#learning">Развитие</a><a href="#market">Рынок</a></nav>
<div id="overview" class="tiles">
<div class="tile"><small>Капитал сейчас</small><div class="metric" id="equity">—</div><small id="total">Старт: 1 000 USDT</small></div>
<div class="tile"><small>Баланс без переоценки</small><div class="metric" id="balance">—</div><small>USDT · виртуальный</small></div>
<div class="tile"><small>Результат сегодня (UTC)</small><div class="metric" id="daily">—</div><small id="daypct">—</small></div>
<div class="tile"><small>Закрытые сделки сегодня</small><div class="metric" id="tradecount">—</div><small id="wins">—</small></div>
</div><div class="split">
<section><div class="toolbar"><h2>Динамика капитала</h2><select id="period"><option value="1">24 часа</option><option value="7">7 дней</option><option value="30">30 дней</option></select></div><svg id="equityChart" class="chart" viewBox="0 0 650 220" preserveAspectRatio="none"></svg><small id="chartNote" class="chartnote">Только сохранённые наблюдения</small></section>
<section><h2>Дневная цель · 10%</h2><div class="metric" id="goal">—</div><small id="target">—</small><div class="bar"><div id="progress"></div></div><p id="remaining">—</p><small>Исследовательский ориентир, не гарантия. Лимит дневного убытка 3%, максимальная просадка 15%.</small><p id="riskstate"></p></section></div>
<section id="trading"><h2>Открытая позиция</h2><div id="position">—</div><h2 style="margin-top:20px">История виртуальных сделок</h2><div class="toolbar"><small id="tradesNote"></small><select id="tradeperiod"><option value="today">Сегодня UTC</option><option value="all">Все сохранённые</option></select></div><div class="scroll"><table><thead><tr><th>Вход / выход</th><th>Пара</th><th>Сторона</th><th>Вход</th><th>Выход</th><th>Комиссии*</th><th>Чистый P&L</th><th>Стратегия / причина выхода</th></tr></thead><tbody id="trades"></tbody></table></div><small>* Модельные комиссии; проскальзывание включено в цены. Фандинг пока не начисляется.</small></section>
<section id="lab"><h2>Лаборатория стратегий</h2><div id="labstats" class="tiles"></div><p id="training" class="muted"></p><div id="models" class="subgrid"></div><small>Историческая проверка не подтверждает будущую прибыль. Допуск означает лишь право на виртуальную сделку.</small></section>
<section id="learning"><h2>История обучения по дням</h2><svg id="learnChart" class="chart" viewBox="0 0 650 220" preserveAspectRatio="none"></svg><div class="scroll"><table><thead><tr><th>Дата UTC</th><th>Эксперименты</th><th>Циклы</th><th>Допуски</th><th>Отклонения</th></tr></thead><tbody id="learnrows"></tbody></table></div><small>Количество экспериментов — активность, а не показатель интеллекта. Качество сравниваем с результатами на новых данных.</small></section>
<section id="market"><h2>Данные Bybit</h2><p id="marketstatus"></p><div class="scroll"><table><thead><tr><th>Пара</th><th>Свечи 15м</th><th>Снимки</th><th>Фандинг</th><th>Дисбаланс стакана</th><th>Дельта сделок</th><th>Обновлено</th></tr></thead><tbody id="markets"></tbody></table></div><h2 style="margin-top:20px">Треугольный арбитраж · наблюдение</h2><div id="arbs"></div></section>
<footer>Данные из рабочей базы SMART TRADER AI. Обновление каждые 30 секунд. Время сделок — локальное время устройства, торговые сутки — UTC. Панель только для чтения, без приватных ключей и реальных ордеров.</footer>
<script>
let data=null;const el=id=>document.getElementById(id);const fmt=(x,n=2)=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toLocaleString('ru-RU',{minimumFractionDigits:n,maximumFractionDigits:n});const money=x=>fmt(x)+' USDT';const pct=x=>x==null?'—':fmt(x*100)+'%';const dt=t=>t?new Date(t*1000).toLocaleString('ru-RU'):'—';const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const col=x=>x>0?'up':x<0?'down':'';const signed=x=>(x>0?'+':'')+fmt(x);const utc=t=>new Date(t*1000).toISOString().slice(0,10);const side=x=>x===1?'LONG':'SHORT';
const names={mom4:'Импульс 1ч',mom12:'Импульс 3ч',mom24:'Импульс 6ч',ema_gap:'Разница EMA',rsi:'RSI',boll_z:'Bollinger Z',vol_ratio:'Объём',atr_ratio:'ATR',book_imbalance:'Дисбаланс стакана',taker_delta:'Дельта агрессивных сделок',funding:'Фандинг',oi_change:'Изменение OI',liq_long:'Ликвидации LONG',liq_short:'Ликвидации SHORT',spot_basis:'Базис спот/фьючерс',basis:'Базис mark/index'};
function strategy(s){return s?.all?.length?s.all.map(p=>esc(names[p.feature]||p.feature)+' × '+esc(p.direction)+' > '+fmt(p.threshold,6)).join('<br>'):'Условия не сохранены';}
function rows(id,arr,empty,span){el(id).innerHTML=arr.length?arr.join(''):'<tr><td colspan="'+span+'" class="empty">'+esc(empty)+'</td></tr>'}
function value(id,x,text){el(id).textContent=text;el(id).className='metric '+col(x)}
function plot(id,points,baseline,bar=false){const svg=el(id);if(!points.length){svg.innerHTML='<text x="325" y="110" fill="#98a9bf" text-anchor="middle">Пока недостаточно данных</text>';return;}const W=650,H=220,L=65,R=15,T=15,B=32;const vals=points.map(p=>p.y);let lo=Math.min(...vals,baseline??Infinity),hi=Math.max(...vals,baseline??-Infinity);if(hi-lo<.01){lo-=1;hi+=1}const pad=(hi-lo)*.08;lo-=pad;hi+=pad;const x=i=>L+(W-L-R)*(points.length===1?.5:i/(points.length-1));const y=v=>T+(H-T-B)*(hi-v)/(hi-lo);let h='';for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4;h+='<line x1="'+L+'" y1="'+y(v)+'" x2="'+(W-R)+'" y2="'+y(v)+'" stroke="#28384b"/><text x="'+(L-6)+'" y="'+(y(v)+4)+'" font-size="11" text-anchor="end" fill="#98a9bf">'+fmt(v,bar?0:2)+'</text>'}if(bar){const bw=Math.min(28,(W-L-R)/Math.max(points.length,1)*.65);points.forEach((p,i)=>{h+='<rect x="'+(x(i)-bw/2)+'" y="'+y(p.y)+'" width="'+bw+'" height="'+Math.max(0,y(0)-y(p.y))+'" rx="3" fill="#78aaff"><title>'+esc(p.label)+': '+fmt(p.y,0)+'</title></rect>'})}else{if(points.length>1)h+='<polyline fill="none" stroke="#53e0ae" stroke-width="2.5" points="'+points.map((p,i)=>x(i)+','+y(p.y)).join(' ')+'"/>';points.forEach((p,i)=>{h+='<circle cx="'+x(i)+'" cy="'+y(p.y)+'" r="'+(points.length<80?3:1.5)+'" fill="#53e0ae"><title>'+esc(p.label)+': '+fmt(p.y)+'</title></circle>'})}h+='<text x="'+L+'" y="210" fill="#98a9bf" font-size="11">'+esc(points[0].short)+'</text><text x="'+(W-R)+'" y="210" text-anchor="end" fill="#98a9bf" font-size="11">'+esc(points.at(-1).short)+'</text>';svg.innerHTML=h}
function draw(){if(!data)return;const j=data, cutoff=Date.now()/1000-Number(el('period').value)*86400;let points=(j.equity_history||[]).filter(p=>p.time>=cutoff).map(p=>({y:p.equity,label:dt(p.time),short:new Date(p.time*1000).toLocaleDateString('ru-RU')}));if(j.state.last_poll)points.push({y:j.equity,label:dt(j.state.last_poll),short:'Сейчас'});plot('equityChart',points,null);el('chartNote').textContent='Наблюдений: '+points.length+' · исторические значения до запуска панели не восстановлены';const all=j.trades||[],today=all.filter(t=>utc(t.closed)===j.day);const ts=el('tradeperiod').value==='today'?today:all;el('tradesNote').textContent='Показано '+Math.min(ts.length,200)+' из '+ts.length;rows('trades',ts.slice(-200).reverse().map(t=>'<tr><td>'+esc(dt(t.opened))+'<br>'+esc(dt(t.closed))+'</td><td>'+esc(t.symbol)+'</td><td>'+side(t.side)+'</td><td>'+fmt(t.entry,6)+'</td><td>'+fmt(t.exit,6)+'</td><td>'+fmt((t.entry_fee||0)+t.qty*t.exit*.0006,4)+'</td><td class="'+col(t.pnl)+'">'+signed(t.pnl)+'</td><td class="wrap">'+strategy(t.strategy)+'<br><small>'+esc(t.model)+' · '+esc(({time_exit:'Выход по времени',stop_observed:'Стоп',drawdown:'Просадка',daily_loss:'Дневной лимит'})[t.reason]||t.reason)+'</small></td></tr>'),'Закрытых сделок пока нет',8)}
function render(j){data=j;const e=j.equity, d=e-j.day_start, ret=d/j.day_start, today=(j.trades||[]).filter(t=>utc(t.closed)===j.day);value('equity',e-j.start,money(e));value('balance',0,money(j.balance));el('total').textContent='С начала: '+signed(e-j.start)+' USDT ('+pct(e/j.start-1)+')';value('daily',d,signed(d)+' USDT');el('daypct').textContent=pct(ret)+' · '+j.day;el('tradecount').textContent=today.length;el('wins').textContent=today.filter(t=>t.pnl>0).length+' прибыльных / '+today.filter(t=>t.pnl<0).length+' убыточных';value('goal',ret,pct(ret));el('target').textContent='Целевой капитал: '+money(j.day_start*(1+j.target_daily));el('remaining').textContent='До цели: '+money(Math.max(0,j.day_start*(1+j.target_daily)-e));el('progress').style.width=Math.max(0,Math.min(100,ret/j.target_daily*100))+'%';el('riskstate').textContent=(j.halted?'Торговля остановлена контролёром':'Контроль риска активен')+' · просадка '+pct(1-e/j.peak);el('health').textContent=j.state.version+' · '+({running:'работает',starting:'запуск',degraded:'сбой данных'})[j.state.status]+' · '+dt(j.state.last_poll);const p=j.position;el('position').innerHTML=p?'<div class="model"><h3>'+esc(p.symbol)+' · '+side(p.side)+'</h3><p>Открыта '+esc(dt(p.opened))+' · вход '+fmt(p.entry,6)+' · номинал '+money(p.qty*p.entry)+'</p><p>Текущая переоценка: <strong class="'+col(e-j.balance)+'">'+signed(e-j.balance)+' USDT</strong></p><small>Условия входа</small><p>'+strategy(p.strategy)+'</p></div>':'<div class="empty">Открытых позиций нет</div>';const sy=j.symbols||[], hist=j.recent_research||[];const total=sy.reduce((a,s)=>a+(s.brain?.total_tested||0),0), approved=sy.filter(s=>s.champion).length;el('labstats').innerHTML=[['Инструменты',sy.length],['Проверено (активные пары)',total],['Допущено моделей',approved],['Признаков в коде',54]].map(([k,v])=>'<div class="tile"><small>'+esc(k)+'</small><div class="metric">'+v+'</div></div>').join('');el('training').textContent=j.state.training?'Сейчас обучается: '+j.state.training:'Последний цикл: '+(j.latest_training?.symbol||'—')+' · '+dt(j.latest_training?.time)+(j.latest_training?.error?' · '+j.latest_training.error:'');el('models').innerHTML=sy.map(s=>{const r=s.report||{},c=s.champion,b=s.brain||{};return '<div class="model"><h3>'+esc(s.symbol)+' <span class="pill">'+(c?'Допущена':r.time?'Не допущена':'Нет теста')+'</span></h3><small>Поколение '+(b.generation||0)+' · экспериментов '+(b.total_tested||0)+' · доступных признаков '+(r.eligible_features?.length??'—')+'</small><p>Validation: <b class="'+col(r.validation?.return)+'">'+pct(r.validation?.return)+'</b> · Holdout: <b class="'+col(r.holdout?.return)+'">'+pct(r.holdout?.return)+'</b></p><small>Просадка holdout '+pct(r.holdout?.drawdown)+' · сделок '+(r.holdout?.trades??'—')+'</small><p>'+strategy(c?.strategy||r.selected_params)+'</p><small>Последний тест '+esc(dt(r.time))+'</small></div>'}).join('');const days={};hist.forEach(r=>{if(!r.time)return;const k=utc(r.time),v=days[k]||{n:0,c:0,a:0};v.n+=r.candidates||0;v.c++;v.a+=r.approved?1:0;days[k]=v});const ds=Object.entries(days).sort((a,b)=>a[0].localeCompare(b[0]));plot('learnChart',ds.slice(-30).map(([k,v])=>({y:v.n,label:k,short:k.slice(5)})),0,true);rows('learnrows',ds.reverse().map(([k,v])=>'<tr><td>'+k+'</td><td>'+v.n+'</td><td>'+v.c+'</td><td>'+v.a+'</td><td>'+(v.c-v.a)+'</td></tr>'),'Пока нет завершённых циклов',5);const m=j.micro_status;el('marketstatus').textContent='Хранилище: '+j.storage+' · ликвидации WebSocket: '+(m?.liquidation_stream?.connected?'подключён':'не подтверждён')+' · сбор: '+dt(m?.time)+(m?.errors&&Object.keys(m.errors).length?' · ошибки: '+JSON.stringify(m.errors):'');rows('markets',sy.map(s=>{const q=s.latest_micro||{};return '<tr><td>'+esc(s.symbol)+'</td><td>'+s.bars+'</td><td>'+s.micro_bars+'</td><td>'+pct(q.funding)+'</td><td>'+pct(q.book_imbalance)+'</td><td>'+pct(q.taker_delta)+'</td><td>'+esc(dt(q.observed/1000))+'</td></tr>'}),'Нет данных',7);el('arbs').innerHTML=(j.arbitrage?.routes||[]).map(r=>'<p>'+esc(r.path.join(' → '))+' <b class="'+col(r.net_estimate)+'">'+pct(r.net_estimate)+'</b></p>').join('')||'<p class="muted">Нет сохранённых маршрутов</p>';draw()}
async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);render(await r.json())}catch(e){el('health').textContent='Ошибка обновления: '+e.message+' · предыдущие данные могут быть устаревшими'}}el('period').onchange=draw;el('tradeperiod').onchange=draw;refresh();setInterval(refresh,30000);
</script></main></body></html>"""
@app.get("/")
@app.get("/admin")
def dashboard():return render_template_string(PAGE)

if __name__=="__main__":
    threading.Thread(target=market_lab.stream_worker,daemon=True).start()
    threading.Thread(target=market_lab.collector,daemon=True).start()
    threading.Thread(target=market_worker,daemon=True).start()
    threading.Thread(target=trainer_worker,daemon=True).start()
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")),threads=2)
