"""Ozon Pay / SBP-only frontend preview for Sovpali.

Public demonstration ONLY. It neither collects card numbers nor initiates
charges. Never enable actual payment or unlock service from a return URL.
The real Ozon Acquiring API integration must verify a signed payment outcome
and match amount, order and merchant before granting digital services.
"""
from flask import make_response

_PAGE = """<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#151217"><meta name="robots" content="noindex,nofollow">
<title>Оплата через СБП · Совпали</title>
<style>
:root{color-scheme:dark;--bg:#151217;--ink:#fbefec;--m:#b9aab4;--pink:#e7adaf;--line:#ffffff26}
*{box-sizing:border-box}html{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-text-size-adjust:100%;scroll-behavior:smooth}body{margin:0;background:radial-gradient(ellipse at 75% 2%,#61414d50,transparent 50%),var(--bg);color:var(--ink);min-height:100svh;overflow-x:hidden}
button,input{font:inherit}button:focus-visible,input:focus-visible{outline:2px solid var(--pink);outline-offset:4px}
header{display:flex;align-items:center;justify-content:space-between;padding:26px 5%;border-bottom:1px solid var(--line)}.logo{font-weight:750;font-size:27px;letter-spacing:-1.8px}.logo span{color:var(--pink)}.head-status{font-size:10px;font-weight:700;letter-spacing:1.8px;color:#cbb6be}.head-status i{display:inline-block;background:#d9a3aa;width:6px;height:6px;border-radius:50%;box-shadow:0 0 0 5px #c57a8d28;margin-right:10px}
main{display:grid;grid-template-columns:1.07fr .93fr;gap:clamp(25px,4vw,85px);max-width:1500px;padding:clamp(52px,8vh,105px) 5% 95px;margin:auto;align-items:start}
.eyebrow{font-size:10px;font-weight:750;letter-spacing:2.2px;color:var(--pink);text-transform:uppercase}
h1{font-weight:560;letter-spacing:-.075em;font-size:clamp(62px,7vw,119px);line-height:.94;margin:25px 0 32px}h1 em,h2 em{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-style:italic;color:var(--pink);letter-spacing:-.07em}.intro{font-size:15px;line-height:1.85;color:var(--m);max-width:540px}.steps{margin-top:64px;border-top:1px solid var(--line);max-width:560px}.step{display:flex;align-items:center;gap:18px;padding:19px 0;border-bottom:1px solid var(--line);color:#d6c9ce;font-size:13px}.step b{font-size:12px;font-weight:500;color:#ebaeaf;width:25px;letter-spacing:1px}.step span{line-height:1.65}.note{margin-top:37px;max-width:540px;border-left:2px solid #e6acb2;padding:2px 0 2px 18px;font-size:11px;color:#a79ba6;line-height:1.8}
.panel{background:linear-gradient(150deg,#362630,#201b24 65%);border:1px solid #ffffff35;padding:clamp(25px,4vw,46px);box-shadow:0 30px 120px #0005;position:relative}.panel:before{content:"";position:absolute;left:0;right:0;top:0;height:3px;background:linear-gradient(90deg,#7e4358,#e9b3b7,#7e4358)}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;color:#f2cfcd;font-size:10px;letter-spacing:1.4px;font-weight:750}.test{border:1px solid #d89ba46c;padding:7px 9px;white-space:nowrap;color:#e6b9c5;font-size:9px;letter-spacing:.6px}.product{padding:38px 0 18px;border-bottom:1px solid #ffffff35}.product small{font-size:10px;letter-spacing:2px;color:#b29ba7}.product h2{font-size:clamp(32px,3.1vw,48px);letter-spacing:-.065em;line-height:1.06;margin:16px 0;font-weight:550}.product p{font-size:12px;line-height:1.75;color:#ae9caa;max-width:400px}
.selector{display:grid;gap:8px;margin:23px 0}.option{display:flex;align-items:center;justify-content:space-between;gap:15px;border:1px solid #ffffff2b;background:#ffffff08;color:#f5e7e7;text-align:left;padding:15px 16px;transition:border-color .18s,background .18s;cursor:pointer}.option:hover{background:#ffffff11}.option[aria-pressed="true"]{border-color:#edb5b5;background:#aa768026}.option strong{font-size:13px;font-weight:560}.option small{display:block;font-size:10px;margin-top:6px;color:#ad9ba7;line-height:1.5}.option b{font-size:19px;white-space:nowrap;font-weight:600;letter-spacing:-.6px}
.payline{display:flex;align-items:end;justify-content:space-between;gap:12px;padding:22px 0 25px;border-bottom:1px solid #ffffff25}.payline span{color:#b49eaa;font-size:12px}.payline strong{font-size:49px;letter-spacing:-3px;font-weight:620}
.method{margin-top:26px}.method-title{font-size:11px;color:#c8b2bd;letter-spacing:1.7px;font-weight:700}.sbp{display:flex;gap:15px;align-items:center;margin-top:14px;padding:20px;border:1px solid #e7b4b38a;background:#efadb014}.sbp-icon{display:grid;place-items:center;border:1px solid #e7b4b398;color:#ffccd1;width:51px;height:51px;font-size:25px;flex:0 0 51px}.sbp strong{display:block;font-size:15px}.sbp small{display:block;color:#bcaab5;font-size:11px;margin-top:5px;line-height:1.6}
.email-label{display:block;margin:27px 0 9px;color:#c7b9c2;font-size:11px;letter-spacing:1.2px}.receipt{width:100%;border:1px solid #ffffff4a;background:#211b24;padding:17px;color:#f8e9ef;outline:none;border-radius:0;font-size:14px}.receipt::placeholder{color:#847682}
.cta{margin-top:22px;padding:20px 17px;display:flex;align-items:center;justify-content:center;gap:14px;width:100%;border:0;background:#e5adaf;color:#291b25;font-size:12px;font-weight:750;letter-spacing:1px;opacity:.8;cursor:not-allowed}.cta span{font-size:20px}.hint{text-align:center;color:#b1a0ae;font-size:11px;line-height:1.7;margin:14px 0 0}.checks{border-top:1px solid #ffffff29;margin-top:26px;padding-top:23px;display:grid;gap:12px;font-size:11px;color:#cfbec8}.checks div{display:flex;align-items:center;gap:10px}.checks b{color:#e8a8b0;font-weight:500}
footer{border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:15px;padding:27px 5%;font-size:10px;letter-spacing:1px;color:#857882}
@media(max-width:920px){main{grid-template-columns:1fr;gap:35px;padding-top:50px}.copy h1{font-size:clamp(64px,10vw,103px)}.steps{margin-top:36px;display:none}.note{margin-top:25px}.panel{width:min(600px,100%);margin:auto}}
@media(max-width:560px){header{padding:22px 6%}.logo{font-size:23px}.head-status{font-size:8px;letter-spacing:.9px}main{padding:53px 6% 75px;gap:30px}.copy h1{font-size:clamp(56px,13vw,86px);margin:19px 0 24px}.intro{font-size:13px}.panel{padding:27px 22px}.panel-head{letter-spacing:.5px}.product{padding-top:29px}.product h2{font-size:35px}.option{padding:14px}.option strong{font-size:12px}.option b{font-size:17px}.payline strong{font-size:43px}footer{padding:25px 6%;font-size:8px}footer span:nth-child(2){display:none}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style></head><body>
<header><div class="logo">♡ совпали<span>.</span></div><div class="head-status"><i></i> ЗАЩИЩЁННЫЙ ПЛАТЁЖ · СБП</div></header>
<main><section class="copy"><div class="eyebrow">01 / простой способ сделать следующий шаг</div><h1>НАЧАЛО<br><em>ВАШЕЙ ИСТОРИИ.</em></h1>
<p class="intro">Оплата цифровой услуги через Систему быстрых платежей — без ввода данных карты. Сначала выбери услугу. Когда Ozon Pay будет подключён, оплата откроется в приложении твоего банка.</p>
<div class="steps"><div class="step"><b>01</b><span>Выбери услугу и проверь итоговую стоимость</span></div><div class="step"><b>02</b><span>Перейди к оплате через СБП, подтверди её в банке</span></div><div class="step"><b>03</b><span>После подтверждения банк сообщит нам об оплате</span></div></div>
<div class="note">Это предварительный макет. Пока мы тестируем взаимные знакомства в Telegram, деньги не списываются и платные функции не открываются. Для запуска нужно подключить Ozon Pay и автоматическую проверку оплаты.</div></section>
<section class="panel" aria-label="Предпросмотр оплаты">
<div class="panel-head"><span>ОФОРМЛЕНИЕ · СОВПАЛИ</span><span class="test">ДЕМО · БЕЗ СПИСАНИЙ</span></div>
<div class="product"><small>ЦИФРОВАЯ УСЛУГА</small><h2 id="product-name">Подсказки для<br><em>общения.</em></h2><p id="product-desc">Персональная помощь с продолжением переписки. Доступ предоставляется после подтверждённой оплаты.</p></div>
<div class="selector" aria-label="Услуга">
<button class="option" type="button" data-service="coach" aria-pressed="true"><span><strong>Помощник в переписке</strong><small>Продолжение диалога после ответа</small></span><b>900 ₽</b></button>
<button class="option" type="button" data-service="contact" aria-pressed="false"><span><strong>Запрос на знакомство</strong><small>Контакт только после взаимного согласия</small></span><b>100 ₽</b></button>
<button class="option" type="button" data-service="premium" aria-pressed="false"><span><strong>Премиум на месяц</strong><small>Расширенные функции сервиса</small></span><b>1 200 ₽</b></button>
</div>
<div class="payline"><span>Итого к оплате</span><strong id="sum">900 ₽</strong></div>
<div class="method"><div class="method-title">СПОСОБ ОПЛАТЫ</div><div class="sbp"><div class="sbp-icon">↗</div><div><strong>СБП · быстрый платёж</strong><small>В мобильном банке или по QR-коду.<br>Номер карты не нужен.</small></div></div></div>
<label class="email-label" for="email">Электронная почта для чека · при необходимости</label>
<input class="receipt" id="email" type="email" inputmode="email" autocomplete="email" placeholder="your@email.ru" maxlength="180">
<button class="cta" type="button" disabled aria-disabled="true">ОПЛАТИТЬ ЧЕРЕЗ СБП <span>↗</span></button>
<p class="hint" role="status">Тестовый экран: Ozon Pay ещё не активирован. Данные карты не собираются, списаний нет.</p>
<div class="checks"><div><b>✓</b> Точная стоимость до оплаты</div><div><b>✓</b> Открытие услуги только после подтверждения банка</div><div><b>✓</b> Платёжные данные обрабатывает банк, не «Совпали»</div></div>
</section></main>
<footer><span>♡ СОВПАЛИ · ОПЛАТА ЧЕРЕЗ СБП</span><span>ЦИФРОВЫЕ УСЛУГИ · ТЕСТОВЫЙ ЭКРАН</span><span>18+</span></footer>
<script>
(function(){
 "use strict";
 var data={
   coach:{amount:900,name:"Подсказки для общения.",desc:"Персональная помощь с продолжением переписки после реального ответа. Откроется после успешной оплаты."},
   contact:{amount:100,name:"Шаг к знакомству.",desc:"Запрос на знакомство; контакт будет открыт только после взаимного согласия. Пока тестируется бесплатно."},
   premium:{amount:1200,name:"Больше возможностей.",desc:"Премиум-функции на 30 дней после подключения платёжного сервиса и проверки доступа."}
 };
 var labels=document.querySelectorAll("[data-service]");
 labels.forEach(function(btn){btn.addEventListener("click",function(){
   var chosen=data[btn.getAttribute("data-service")];if(!chosen)return;
   labels.forEach(function(x){x.setAttribute("aria-pressed",String(x===btn));});
   document.getElementById("product-name").textContent=chosen.name;
   document.getElementById("product-desc").textContent=chosen.desc;
   document.getElementById("sum").textContent=chosen.amount.toLocaleString("ru-RU")+" ₽";
 });});
})();
</script></body></html>"""


def register_ozon_billing_preview(app, ns):
    @app.get("/billing/demo")
    def ozon_billing_demo():
        # No runtime credentials, payment intents or bank network calls.
        reply=make_response(_PAGE)
        reply.headers["Cache-Control"]="private,no-store"
        reply.headers["X-Robots-Tag"]="noindex,nofollow,noarchive"
        reply.headers["Referrer-Policy"]="no-referrer"
        reply.headers["X-Content-Type-Options"]="nosniff"
        return reply
