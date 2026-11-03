"""Ozon Pay / SBP-only frontend preview for Sovpali.

Public demonstration ONLY. It neither collects card numbers nor initiates
charges. Never enable actual payment or unlock service from a return URL.
The real Ozon Acquiring API integration must verify a signed payment outcome
and match amount, order and merchant before granting digital services.
"""
from flask import make_response,redirect
import os
from urllib.parse import urlparse

_PAGE = """<!doctype html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#151217"><meta name="robots" content="noindex,nofollow">
<title>Оплата картой или через СБП · Совпали</title>
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
.method-picker{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:15px}
.payment-method{border:1px solid #ffffff30;background:#211c25;color:#f5e9eb;display:flex;align-items:center;gap:11px;text-align:left;padding:17px 13px;min-width:0;transition:border-color .2s,background .2s}
.payment-method[aria-pressed="true"]{border-color:#edb4b8;background:#dc9da328}
.payment-method:hover{border-color:#e8a8b988}
.payment-method strong{font-size:14px;display:block;font-weight:650}
.payment-method small{font-size:10px;color:#ac9daa;display:block;margin-top:5px;line-height:1.4}
.method-symbol{font-size:22px;color:#e8adb4;font-weight:450}
.method-check{font-size:12px;color:#e8b0b1;margin-left:auto;opacity:0}
.payment-method[aria-pressed="true"] .method-check{opacity:1}
.email-label{display:block;margin:27px 0 9px;color:#c7b9c2;font-size:11px;letter-spacing:1.2px}.receipt{width:100%;border:1px solid #ffffff4a;background:#211b24;padding:17px;color:#f8e9ef;outline:none;border-radius:0;font-size:14px}.receipt::placeholder{color:#847682}
.cta{margin-top:22px;padding:20px 17px;display:flex;align-items:center;justify-content:center;gap:14px;width:100%;border:0;background:#e5adaf;color:#291b25;font-size:12px;font-weight:750;letter-spacing:1px;opacity:.8;cursor:not-allowed}.cta span{font-size:20px}.hint{text-align:center;color:#b1a0ae;font-size:11px;line-height:1.7;margin:14px 0 0}.checks{border-top:1px solid #ffffff29;margin-top:26px;padding-top:23px;display:grid;gap:12px;font-size:11px;color:#cfbec8}.checks div{display:flex;align-items:center;gap:10px}.checks b{color:#e8a8b0;font-weight:500}
footer{border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:15px;padding:27px 5%;font-size:10px;letter-spacing:1px;color:#857882}
@media(max-width:920px){main{grid-template-columns:1fr;gap:35px;padding-top:50px}.copy h1{font-size:clamp(64px,10vw,103px)}.steps{margin-top:36px;display:none}.note{margin-top:25px}.panel{width:min(600px,100%);margin:auto}}
@media(max-width:560px){header{padding:22px 6%}.logo{font-size:23px}.head-status{font-size:8px;letter-spacing:.9px}main{padding:53px 6% 75px;gap:30px}.copy h1{font-size:clamp(56px,13vw,86px);margin:19px 0 24px}.intro{font-size:13px}.panel{padding:27px 22px}.panel-head{letter-spacing:.5px}.product{padding-top:29px}.product h2{font-size:35px}.option{padding:14px}.option strong{font-size:12px}.option b{font-size:17px}.payline strong{font-size:43px}footer{padding:25px 6%;font-size:8px}footer span:nth-child(2){display:none}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style></head><body>
<header><div class="logo">♡ совпали<span>.</span></div><div class="head-status"><i></i> ЗАЩИЩЁННЫЙ ПЛАТЁЖ · СБП</div></header>
<main><section class="copy"><div class="eyebrow">01 / простой способ сделать следующий шаг</div><h1>НАЧАЛО<br><em>ВАШЕЙ ИСТОРИИ.</em></h1>
<p class="intro">Выбери удобный способ оплаты: <strong>СБП</strong> или <strong>банковская карта</strong>. Вся оплата будет проходить на защищённой стороне Ozon Pay, а не внутри «Совпали».</p>
<div class="steps"><div class="step"><b>01</b><span>Выбери услугу и проверь итоговую стоимость</span></div><div class="step"><b>02</b><span>Оплати картой или через СБП на защищённой странице Ozon Pay</span></div><div class="step"><b>03</b><span>После проверки подтверждения банка откроется оплаченная услуга</span></div></div>
<div class="note">Это самостоятельная проверка банковского эквайринга. Если подключена официальная ссылка Ozon Pay на 100 ₽, списание при подтверждении в банке будет настоящим. Сам бот останется бесплатным; эта оплата не выдаёт контакт или цифровой доступ.</div></section>
<section class="panel" aria-label="Предпросмотр оплаты">
<div class="panel-head"><span>ОФОРМЛЕНИЕ · СОВПАЛИ</span><span class="test">ТЕСТ ЭКВАЙРИНГА · 100 ₽</span></div>
<div class="product"><small>ЦИФРОВАЯ УСЛУГА</small><h2 id="product-name">Тестовый<br><em>платёж.</em></h2><p id="product-desc">Для самостоятельной проверки эквайринга Ozon Pay. При наличии банковской платёжной ссылки можно оплатить 100 ₽ со своей карты. Автоматическая выдача услуг пока отключена.</p></div>
<div class="selector" aria-label="Услуга">
<button class="option" type="button" data-service="coach" aria-pressed="false"><span><strong>Помощник в переписке</strong><small>Продолжение диалога после ответа</small></span><b>900 ₽</b></button>
<button class="option" type="button" data-service="contact" aria-pressed="true"><span><strong>Проверить эквайринг</strong><small>100 ₽ — без автоматической выдачи услуг</small></span><b>100 ₽</b></button>
<button class="option" type="button" data-service="premium" aria-pressed="false"><span><strong>Премиум на месяц</strong><small>Расширенные функции сервиса</small></span><b>1 200 ₽</b></button>
</div>
<div class="payline"><span>Итого к оплате</span><strong id="sum">100 ₽</strong></div>
<div class="method"><div class="method-title">ВЫБЕРИ СПОСОБ ОПЛАТЫ</div>
<div class="method-picker" role="group" aria-label="Выберите способ оплаты">
<button class="payment-method" type="button" data-pay-method="sbp" aria-pressed="true"><span class="method-symbol">↗</span><span><strong>СБП</strong><small>Без карты · через банк</small></span><span class="method-check" aria-hidden="true">●</span></button>
<button class="payment-method" type="button" data-pay-method="card" aria-pressed="false"><span class="method-symbol">▤</span><span><strong>Картой</strong><small>На стороне Ozon Pay</small></span><span class="method-check" aria-hidden="true">●</span></button>
</div>
<div class="sbp" aria-live="polite"><div class="sbp-icon" id="method-symbol">↗</div><div><strong id="method-name">СБП · быстрый платёж</strong><small id="method-detail">Перевод через приложение банка или QR-код.<br>Номер карты не нужен.</small></div></div></div>
<label class="email-label" for="email">Электронная почта для чека · при необходимости</label>
<input class="receipt" id="email" type="email" inputmode="email" autocomplete="email" placeholder="your@email.ru" maxlength="180">
<button class="cta" id="pay-button" type="button" __PAY_BUTTON_STATE__><span id="pay-label">ПЕРЕЙТИ К ОПЛАТЕ 100 ₽</span> <span>↗</span></button>
<p class="hint" role="status" id="payment-status">__PAYMENT_STATUS__</p>
<div class="checks"><div><b>✓</b> Точная стоимость до оплаты</div><div><b>✓</b> Открытие услуги только после подтверждения банка</div><div><b>✓</b> Платёжные данные обрабатывает банк, не «Совпали»</div></div>
</section></main>
<footer><span>♡ СОВПАЛИ · КАРТА И СБП</span><span>БАНКОВСКАЯ ПРОВЕРКА · БЕЗ АВТОМАТИЧЕСКОЙ ВЫДАЧИ</span><span>18+</span></footer>
<script>
(function(){
 "use strict";
 var data={
   coach:{amount:900,name:"Подсказки для общения.",desc:"Персональная помощь с продолжением переписки после реального ответа. Откроется после успешной оплаты."},
   contact:{amount:100,name:"Проверка эквайринга.",desc:"Только для самостоятельной проверки списания 100 ₽. Доступ к услугам бота не выдаётся."},
   premium:{amount:1200,name:"Больше возможностей.",desc:"Премиум-функции на 30 дней после подключения платёжного сервиса и проверки доступа."}
 };
 var activeMethod="sbp";
 var activeService="contact";
 var bankReady=__BANK_READY__;
 var payButton=document.getElementById("pay-button");
 payButton.addEventListener("click",function(){if(bankReady&&activeService==="contact"){window.location.assign("/billing/test-payment/100");}});
 function syncButton(){payButton.disabled=!(bankReady&&activeService==="contact");payButton.setAttribute("aria-disabled",String(payButton.disabled));document.getElementById("pay-label").textContent=activeService==="contact"?names[activeMethod].label:"ДЛЯ ЭТОЙ УСЛУГИ ОПЛАТА НЕ ПОДКЛЮЧЕНА";}
 var methods=document.querySelectorAll("[data-pay-method]");
 var names={
   sbp:{title:"СБП · быстрый платёж",detail:"Перевод через приложение банка или QR-код. Номер карты не нужен.",label:"ПЕРЕЙТИ К ОПЛАТЕ ЧЕРЕЗ СБП",symbol:"↗"},
   card:{title:"Банковской картой · Ozon Pay",detail:"Перейдёшь на защищённую страницу Ozon Pay. Реквизиты карты здесь не вводятся и не хранятся.",label:"ПЕРЕЙТИ К ОПЛАТЕ КАРТОЙ",symbol:"▤"}
 };
 function chooseMethod(method){
   if(!names[method])return;
   activeMethod=method;
   methods.forEach(function(button){button.setAttribute("aria-pressed",String(button.getAttribute("data-pay-method")===method));});
   document.getElementById("method-name").textContent=names[method].title;
   document.getElementById("method-detail").textContent=names[method].detail;
   document.getElementById("method-symbol").textContent=names[method].symbol;
   document.getElementById("pay-label").textContent=activeService==="contact"?names[method].label:"ОПЛАТА ПОКА НЕ ДОСТУПНА";
 }
 methods.forEach(function(button){
   button.addEventListener("click",function(){chooseMethod(button.getAttribute("data-pay-method"));});
 });
 var labels=document.querySelectorAll("[data-service]");
 labels.forEach(function(btn){btn.addEventListener("click",function(){
   activeService=btn.getAttribute("data-service");
   var chosen=data[activeService];if(!chosen)return;
   labels.forEach(function(x){x.setAttribute("aria-pressed",String(x===btn));});
   document.getElementById("product-name").textContent=chosen.name;
   document.getElementById("product-desc").textContent=chosen.desc;
   document.getElementById("sum").textContent=chosen.amount.toLocaleString("ru-RU")+" ₽";
   syncButton();
 });});
 syncButton();
})();
</script></body></html>"""



def _payment_return_page(success):
    # A redirect never proves that payment succeeded.
    title = "Проверяем оплату" if success else "Оплата не завершена"
    subtitle = (
        "Возврат из Ozon Pay выполнен. Проверка статуса платежа банком ещё не завершена."
        if success else
        "Платёж не был завершён. Перед новой попыткой проверь операции в приложении банка."
    )
    mark = "✦" if success else "↻"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#151217"><meta name="robots" content="noindex,nofollow">
<title>{title} · Совпали</title><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100svh;background:radial-gradient(ellipse at 70% 5%,#63374755,transparent 54%),#151217;color:#f9eeec;font-family:system-ui,-apple-system,sans-serif;display:flex;flex-direction:column}}
header{{padding:24px 6%;border-bottom:1px solid #ffffff27;font-weight:750;font-size:25px;letter-spacing:-1.5px}}header b{{color:#e6a5ae}}
main{{width:100%;max-width:620px;padding:62px 7%;margin:auto}}.mark{{font-size:89px;color:#e3aab4}}
h1{{font-size:clamp(46px,9vw,79px);letter-spacing:-.075em;line-height:1;font-weight:600}}
p{{font-size:15px;line-height:1.8;color:#bdaeba}}.notice{{margin-top:30px;padding:20px;border:1px solid #e6a5ae55;background:#e6a5ae14;color:#dec6d1;font-size:12px;line-height:1.7}}
a{{display:inline-block;padding:17px 23px;background:#e6a5ae;color:#24161e;text-decoration:none;font-weight:700;margin-top:28px}}
footer{{padding:22px;text-align:center;color:#867480;border-top:1px solid #ffffff27;font-size:10px}}
</style></head><body><header>♡ совпали<b>.</b></header><main>
<div class="mark">{mark}</div><h1>{title}</h1><p>{subtitle}</p>
<div class="notice">Эта страница — не подтверждение оплаты. Доступ к цифровой услуге можно открыть только после независимой проверки платежа на сервере.</div>
<a href="/billing/demo">На страницу оформления</a>
</main><footer>СОВПАЛИ · OZON PAY · ПРОВЕРКА ПЛАТЕЖЕЙ</footer></body></html>"""


def _bank_checkout_url():
    """Only the operator-provided official Ozon payment link is ever used.

    Never assemble card-processing URLs with leaked credentials or accept a
    return URL from an untrusted query string.
    """
    raw=os.environ.get("OZON_PAY_TEST_100_URL","").strip()
    if not raw or len(raw)>2000:return None
    try:
        url=urlparse(raw)
        hostname=(url.hostname or "").lower().rstrip(".")
        permitted=(
            hostname in {"ozon.ru","ozonpay.ru","ozon.com"} or
            hostname.endswith((".ozon.ru",".ozonpay.ru",".ozon.com"))
        )
        if url.scheme!="https" or not permitted or url.username or url.password or url.port is not None:
            return None
        if not url.path or url.path=="/":return None
        return raw
    except ValueError:return None


def register_ozon_billing_preview(app, ns):
    @app.get("/billing/demo")
    def ozon_billing_demo():
        # Only the 100-ruble operator-created payment link can activate.
        # This button never interacts with exposed merchant API credentials.
        ready=bool(_bank_checkout_url())
        content=(_PAGE
                 .replace("__PAY_BUTTON_STATE__", "" if ready else 'disabled aria-disabled="true"')
                 .replace("__PAYMENT_STATUS__", (
                    "Проверка на 100 ₽: после нажатия откроется сайт Ozon Pay. Там выбери карту или СБП и сверь сумму. Списание будет настоящим; выдача услуг не подключена."
                    if ready else
                    "Платёжная ссылка Ozon Pay на 100 ₽ ещё не подключена. Создай её в банке и добавь в Render: OZON_PAY_TEST_100_URL. Пока списаний нет."
                 ))
                 .replace("__BANK_READY__","true" if ready else "false"))
        reply=make_response(content)
        reply.headers["Cache-Control"]="private,no-store"
        reply.headers["X-Robots-Tag"]="noindex,nofollow,noarchive"
        reply.headers["Referrer-Policy"]="no-referrer"
        reply.headers["X-Content-Type-Options"]="nosniff"
        return reply

    @app.get("/billing/test-payment/100")
    def ozon_test_payment_100():
        """External hosted checkout, not a real acquiring API integration.

        No success status or access grant is emitted from this redirect. Bank
        payment link contains its OWN amount; verify that it is 100 ₽ before
        setting the Render environment value.
        """
        url=_bank_checkout_url()
        if not url:
            reply=make_response(
                "<!doctype html><html lang='ru'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<body style='background:#151217;color:#f5e6e9;font:16px system-ui;padding:30px'>"
                "<h1>Ссылка оплаты ещё не подключена</h1>"
                "<p>В Ozon Банке создай платёжную ссылку на 100 ₽ и помести "
                "её в Render → Environment → OZON_PAY_TEST_100_URL.</p>"
                "<p>API-ключи в браузер и GitHub не вставляй.</p>"
                "<a style='color:#efaeb4' href='/billing/demo'>Вернуться</a></body></html>",
                503
            )
        else:
            reply=redirect(url,code=303)
        reply.headers["Cache-Control"]="private,no-store"
        reply.headers["Referrer-Policy"]="no-referrer"
        reply.headers["X-Robots-Tag"]="noindex,nofollow,noarchive"
        return reply

    @app.get("/billing/return/success")
    def ozon_return_success():
        response=make_response(_payment_return_page(True))
        response.headers["Cache-Control"]="private,no-store"
        response.headers["X-Robots-Tag"]="noindex,nofollow,noarchive"
        return response

    @app.get("/billing/return/fail")
    def ozon_return_fail():
        response=make_response(_payment_return_page(False))
        response.headers["Cache-Control"]="private,no-store"
        response.headers["X-Robots-Tag"]="noindex,nofollow,noarchive"
        return response
