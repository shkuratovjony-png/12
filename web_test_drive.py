"""Public two-account test-drive guide and safe feature previews.

No fabricated Telegram users and no fake paid success callbacks.
Real charges are only created from authenticated pair/product checkout forms.
"""
import html
import os
from flask import make_response

def register_test_drive(app,ns):
    @app.get("/test-drive")
    def test_drive():
        contact=bool(callable(ns.get("web_contact_live")) and ns["web_contact_live"]())
        premium=bool(callable(ns.get("web_premium_live")) and ns["web_premium_live"]())
        coach=bool(callable(ns.get("web_coach_live")) and ns["web_coach_live"]())
        checks=[
            ("Сайт и анкеты",True,"Два Telegram-аккаунта с разными анкетами и совместимыми критериями"),
            ("Знакомство · 100 ₽",contact,"Настоящий банковский платёж только с персональной страницы пары"),
            ("Premium · 1 200 ₽",premium,"30 дней без автопродления; списание реальное, если продукт открыт"),
            ("AI-разбор · 900 ₽",coach,"Одна платная генерация после реального ответа; требуется ИИ-провайдер"),
            ("Эмулятор переписки",True,"Демо с вымышленными анкетами, без отправки сообщений и оплаты"),
        ]
        status="".join("<li class='status'><span>"+html.escape(name)+"<small>"+
            html.escape(description)+"</small></span><b class='"+("on" if ok else "off")+"'>"+
            ("Доступно" if ok else "Пока закрыто")+"</b></li>" for name,ok,description in checks)
        body="""<!doctype html><html lang='ru'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='robots' content='noindex,nofollow'><title>Тест-драйв · Совпали</title><style>
:root{--pink:#edb8bf;--bg:#171219}*{box-sizing:border-box}
body{margin:0;background:radial-gradient(ellipse at 20% 0%,#62394770,transparent 55%),var(--bg);color:#f9ecec;font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:20px 5%;border-bottom:1px solid #ffffff28;font-size:26px;font-weight:800}header span{color:var(--pink)}
main{max-width:1090px;margin:auto;padding:53px 5% 88px}.over{font-size:11px;color:var(--pink);letter-spacing:2.2px;font-weight:700}
h1{font-size:clamp(45px,7vw,86px);line-height:1.05;letter-spacing:-.065em;font-weight:620;margin:22px 0}h1 em{font:italic 1em Georgia,serif;color:var(--pink)}
.lead{max-width:670px;color:#c5b2be;font-size:17px;line-height:1.8}
.cols{display:grid;grid-template-columns:1.1fr .9fr;gap:28px;margin-top:48px}
section{border:1px solid #ffffff31;background:#ffffff08;padding:28px}h2{font-size:23px;letter-spacing:-.03em;margin:0 0 23px}
ol{padding-left:25px}ol li{padding:9px 0 16px;line-height:1.7}ol strong{color:var(--pink)}small{display:block;color:#b6a6b1;font-size:12px}
.status{display:flex;justify-content:space-between;align-items:center;gap:15px;border-top:1px solid #ffffff24;padding:16px 0;list-style:none}
.status span{font-weight:600}.status b{font-size:11px;white-space:nowrap;font-weight:650}
.on{color:#c2e4be}.off{color:#c0a3ae}ul{list-style:none;margin:0;padding:0}
.action{display:block;background:var(--pink);color:#271720;text-decoration:none;text-align:center;font-weight:800;padding:17px 15px;margin-top:13px}
.action.secondary{background:transparent;color:var(--pink);border:1px solid #e9b3bd75}
.warn{margin:22px 0;padding:16px 20px;border-left:2px solid #e3b0bc;background:#ffffff0b;color:#d2c3ca;font-size:13px}
@media(max-width:740px){.cols{grid-template-columns:1fr}section{padding:21px}main{padding-top:35px}}
</style></head><body><header>♡ совпали<span>.</span></header><main><div class='over'>ПРОВЕРКА РЕАЛЬНОГО ПРОДУКТА / 2 АККАУНТА</div>
<h1>Проверь,<br><em>как совпали.</em></h1>
<p class='lead'>Это тест-драйв уже работающего сайта и Telegram-бота. Два человека — две анкеты, одно согласие и один реальный платёж на сайте. Эмулятор диалога можно смотреть без оплаты.</p>
<div class='cols'><section><h2>Сценарий для двух аккаунтов</h2><ol>
<li><strong>Аккаунт А:</strong> открой Telegram-бота «Совпали», заполни анкету. Если анкета уже есть, используй её.</li>
<li><strong>Аккаунт Б:</strong> зарегистрируй вторую анкету с совместимыми критериями. Убедись, что бот доступен обоим.</li>
<li><strong>Аккаунт А:</strong> найди аккаунт Б в ТОП-3 и открой персональный разбор совместимости <b>на сайте</b>.</li>
<li><strong>Аккаунт А:</strong> на сайте нажми «Открыть оплату · 100 ₽», получи код в Telegram, введи его, выбери карту или СБП. <b>Это настоящие 100 ₽.</b></li>
<li><strong>Аккаунт Б:</strong> после подтверждения банком должно прийти предложение познакомиться. Нажми «Да, хочу общаться».</li>
<li><strong>Аккаунт А:</strong> проверь уведомление и доступ к контакту. После взаимного согласия открой бесплатный конструктор общения.</li>
<li><strong>Дополнительно:</strong> повтори сценарий с другой подходящей парой и отказом, чтобы проверить бесплатный повторный запрос. Не оплачивай второй раз, если первый платёж не подтверждён.</li>
</ol><div class='warn'>Важно: старая кнопка «Предложить общение» внутри Telegram может использовать бесплатный маршрут. Для проверки покупки 100 ₽ начинай именно с персональной страницы пары на сайте.</div></section>
<section><h2>Что открыто</h2><ul>""" + status + """</ul>
<a class='action' href='/s/m/demo'>Смотреть пример совместимости</a>
<a class='action secondary' href='/coach/demo'>Открыть эмулятор диалога</a>
<a class='action secondary' href='/billing/pay?new=1'>Проверить банк отдельно · 100 ₽</a>
<div class='warn'>Демо не списывает деньги и не открывает настоящий контакт. Для реальной покупки используй персональную ссылку из своего бота.</div>
</section></div></main></body></html>"""
        resp=make_response(body)
        resp.headers["Cache-Control"]="no-store"
        resp.headers["X-Robots-Tag"]="noindex,nofollow"
        resp.headers["X-Content-Type-Options"]="nosniff"
        return resp

    @app.get("/test-drive/status")
    def test_drive_status():
        from ozon_web_checkout import _ready
        return {"bank_ready":_ready(),
                "contacts_open":bool(callable(ns.get("web_contact_live")) and ns["web_contact_live"]()),
                "premium_open":bool(callable(ns.get("web_premium_live")) and ns["web_premium_live"]()),
                "ai_coach_open":bool(callable(ns.get("web_coach_live")) and ns["web_coach_live"]()),
                "demo_available":True}
