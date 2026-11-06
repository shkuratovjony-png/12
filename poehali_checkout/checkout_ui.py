"""Premium responsive email-only checkout for the Poekhali course.

Only the presentation lives here. Form action, short-lived signed tokens,
server-side validation, bank API, receipt issuing, and course delivery remain
owned by app.py.
"""
from html import escape


def checkout_document(*, enabled, csrf, form_token, seller, price_label="1 ₽"):
    csrf_value = escape(csrf, quote=True)
    token_value = escape(form_token, quote=True)
    seller_value = escape(seller, quote=True)
    price_value = escape(price_label, quote=True)

    if enabled:
        form_markup = (
            '<form id="checkout-form" method="post" action="/checkout">'
            '<input type="hidden" name="csrf" value="' + csrf_value + '">'
            '<input type="hidden" name="form_token" value="' + token_value + '">'
            '<label class="field-label" for="buyer-email">Ваша электронная почта</label>'
            '<div class="input-wrap">'
            '<span class="input-icon" aria-hidden="true">'
            '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/></svg>'
            '</span>'
            '<input id="buyer-email" name="email" type="email" autocomplete="email" inputmode="email"'
            ' autocapitalize="off" spellcheck="false" maxlength="255"'
            ' placeholder="name@example.com" required aria-describedby="email-hint">'
            '</div>'
            '<p class="input-hint" id="email-hint">Отправим чек и информацию о доступе на эту почту.</p>'
            '<button id="pay-button" class="pay-button" type="submit">'
            '<span class="button-sheen" aria-hidden="true"></span>'
            '<span class="pay-text">Оплатить ' + price_value + '</span>'
            '<span class="button-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></span>'
            '</button>'
            '<p class="terms">Нажимая «Оплатить», вы принимаете <a href="/terms">оферту</a> и '
            '<a href="/refund">условия возврата</a>. Подробности обработки email — '
            'в <a href="/privacy">политике конфиденциальности</a>.</p>'
            '</form>'
        )
    else:
        form_markup = (
            '<div class="unavailable" role="status">'
            '<span aria-hidden="true">◌</span>'
            '<div><strong>Оформление временно недоступно</strong>'
            '<p>Пожалуйста, попробуйте открыть страницу позднее. '
            'Никаких списаний не было.</p></div></div>'
            '<a class="secondary-link" href="/checkout">Обновить страницу '
            '<span aria-hidden="true">↗</span></a>'
        )

    page = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="robots" content="noindex,nofollow">
  <meta name="theme-color" content="#edf2eb">
  <meta name="description" content="Оформление доступа к курсу «Поехали» — GPT, Telegram и автоматизация цифрового продукта.">
  <title>Оформление доступа — Поехали</title>
  <style>
    :root {
      color-scheme: light;
      --ink:#173831;
      --ink-soft:#596b64;
      --forest:#194a3d;
      --forest-dark:#12382e;
      --line:rgba(255,255,255,.78);
      --shadow:0 32px 90px rgba(31,69,51,.11),0 6px 22px rgba(44,72,58,.045);
      --ease:cubic-bezier(.2,.8,.2,1);
    }
    *,*::before,*::after{box-sizing:border-box}
    html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
    body{margin:0;min-width:320px;overflow-x:hidden;
      font-family:"Manrope","Inter",ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
      -webkit-font-smoothing:antialiased;color:var(--ink);
      background:linear-gradient(119deg,#f5f6f0 0%,#e8f1ec 49%,#eff0e7 100%);
      min-height:100vh;min-height:100svh}
    a{color:inherit;text-decoration:none}
    button,input{font:inherit}
    button{touch-action:manipulation}
    .background{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;isolation:isolate}
    .background::after{content:"";position:absolute;inset:0;opacity:.34;
      background-image:radial-gradient(rgba(23,56,49,.105) .55px,transparent .65px);
      background-size:7px 7px;mask-image:linear-gradient(115deg,transparent 4%,#000 45%,transparent 96%)}
    .orb{position:absolute;display:block;border-radius:50%;filter:blur(3px);
      animation:orbit-drift 20s ease-in-out infinite alternate;transform:translate3d(0,0,0)}
    .orb.one{width:min(62vw,820px);height:min(62vw,820px);left:-18%;top:-28%;
      background:radial-gradient(circle at 65% 60%,rgba(173,222,183,.7),rgba(170,220,187,.23) 46%,transparent 72%)}
    .orb.two{width:min(59vw,760px);height:min(59vw,760px);right:-17%;bottom:-39%;
      background:radial-gradient(circle,rgba(195,216,198,.54),rgba(201,221,203,.13) 48%,transparent 72%);
      animation-delay:-10s;animation-duration:24s}
    .orb.three{width:370px;height:370px;left:48%;top:2%;
      background:radial-gradient(circle,rgba(247,223,172,.36),transparent 72%);
      animation-delay:-5s;animation-duration:26s}
    .page{position:relative;z-index:1;min-height:100vh;min-height:100svh;
      max-width:1260px;margin:auto;padding:28px clamp(18px,4vw,60px) 23px;
      display:flex;flex-direction:column}
    .brandbar{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:48px}
    .brand{display:inline-flex;align-items:center;gap:12px;font-weight:800;letter-spacing:-.045em;font-size:22px}
    .brand-symbol{position:relative;display:grid;place-items:center;width:38px;height:38px;border-radius:13px;
      color:white;background:linear-gradient(140deg,#275c49,#143a31);
      box-shadow:0 7px 22px rgba(24,79,56,.2);font-size:23px;font-weight:500;line-height:1}
    .brand-symbol::after{content:"";position:absolute;inset:1px;border-radius:12px;
      border:1px solid rgba(255,255,255,.26)}
    .brand-note{display:flex;align-items:center;gap:9px;font-size:11px;font-weight:750;
      letter-spacing:.15em;color:#527366;text-transform:uppercase}
    .brand-note .tiny{width:7px;height:7px;border-radius:50%;background:#75a886;
      box-shadow:0 0 0 5px rgba(87,155,105,.11)}
    .main{flex:1;display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr);
      align-items:center;gap:clamp(35px,6vw,94px);padding:clamp(34px,6vh,74px) 0}
    .story{min-width:0;animation:reveal .85s var(--ease) both}
    .eyebrow{display:inline-flex;align-items:center;gap:10px;
      font-size:11px;text-transform:uppercase;font-weight:800;letter-spacing:.18em;color:#487866;margin-bottom:25px}
    .eyebrow::before{content:"";display:block;width:19px;height:1px;background:currentColor}
    .story h1{font-size:clamp(48px,5.65vw,80px);line-height:1.05;font-weight:770;
      letter-spacing:-.071em;margin:0 0 24px;max-width:720px}
    .story h1 span{display:block}
    .story h1 .light{font-weight:480;color:#6d9580}
    .story-lead{max-width:440px;margin:0;color:#566960;
      font-size:clamp(16px,1.35vw,19px);line-height:1.77;letter-spacing:-.017em}
    .flow-line{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:39px}
    .flow-chip{display:inline-flex;align-items:center;gap:9px;white-space:nowrap;
      padding:11px 14px;font-size:12px;font-weight:750;letter-spacing:-.01em;
      border-radius:12px;background:rgba(255,255,255,.35);
      border:1px solid rgba(255,255,255,.72);box-shadow:0 5px 22px rgba(33,76,52,.045);
      backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
    .flow-chip .mini{font-size:14px;color:#608a6d}
    .flow-arrow{color:#95ad9c;font-size:16px}
    .visual{width:min(470px,100%);height:126px;position:relative;margin-top:30px;opacity:.9}
    .visual::before{content:"";position:absolute;left:18px;right:40px;top:54px;height:1px;
      background:linear-gradient(90deg,rgba(50,115,78,.03),rgba(60,122,91,.4),rgba(75,130,91,.04))}
    .visual-card{position:absolute;display:flex;align-items:center;justify-content:center;gap:10px;
      height:60px;border:1px solid rgba(255,255,255,.72);border-radius:17px;
      background:rgba(255,255,255,.4);box-shadow:0 9px 22px rgba(51,82,65,.08);
      backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
      font-size:12px;letter-spacing:-.02em;font-weight:750;color:#385c4b;
      animation:float 6s ease-in-out infinite}
    .visual-card:nth-child(1){width:150px;left:13px;top:13px;transform:rotate(-5deg)}
    .visual-card:nth-child(2){width:157px;left:144px;top:47px;animation-delay:-2s;z-index:2}
    .visual-card:nth-child(3){width:150px;left:291px;top:5px;animation-delay:-4s;z-index:1}
    .visual-card .vicon{display:grid;place-items:center;border-radius:9px;width:31px;height:31px;
      background:rgba(86,135,97,.11);font-size:16px;font-weight:800}
    .panel-shell{position:relative;min-width:0;animation:reveal .95s .13s var(--ease) both}
    .panel-shell::before{content:"";position:absolute;inset:-2px;border-radius:35px;
      background:linear-gradient(135deg,rgba(255,255,255,.98),rgba(255,255,255,.12),rgba(203,225,209,.48));
      filter:blur(3px);opacity:.72}
    .panel{position:relative;border:1px solid rgba(255,255,255,.78);border-radius:33px;
      padding:clamp(26px,3.5vw,47px);overflow:hidden;isolation:isolate;
      background:linear-gradient(155deg,rgba(255,255,255,.76),rgba(255,255,255,.38) 65%,rgba(247,252,248,.63));
      backdrop-filter:blur(26px) saturate(130%);-webkit-backdrop-filter:blur(26px) saturate(130%);
      box-shadow:var(--shadow)}
    .panel::before{content:"";position:absolute;inset:0 0 auto 0;height:90px;
      background:linear-gradient(180deg,rgba(255,255,255,.57),transparent);
      pointer-events:none;z-index:-1}
    .panel::after{content:"";position:absolute;width:230px;height:230px;right:-130px;top:-150px;
      border-radius:50%;background:#fff;filter:blur(75px);opacity:.65;z-index:-1}
    .panel-top{display:flex;align-items:center;justify-content:space-between;gap:12px;
      font-size:10px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#668679}
    .stage{font-variant-numeric:tabular-nums;color:#89a296;font-weight:800;letter-spacing:.1em}
    .panel h2{font-size:clamp(29px,2.7vw,39px);line-height:1.15;
      letter-spacing:-.052em;font-weight:730;margin:30px 0 10px}
    .panel-intro{color:#63746b;font-size:14px;line-height:1.7;margin:0 0 29px;max-width:350px}
    .price-box{display:flex;align-items:center;justify-content:space-between;gap:14px;
      padding:20px 0 23px;border-top:1px solid rgba(81,125,97,.14);
      border-bottom:1px solid rgba(81,125,97,.14);margin-bottom:24px}
    .price-caption{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#82958a;font-weight:800}
    .price{display:block;font-size:clamp(37px,3.2vw,47px);font-weight:760;letter-spacing:-.065em;
      line-height:1.2;color:var(--ink)}
    .one-time{color:#5e806d;font-size:11px;font-weight:760;padding:9px 12px;border-radius:40px;
      border:1px solid rgba(67,115,84,.15);background:rgba(227,240,228,.55);white-space:nowrap}
    .field-label{display:block;font-weight:730;font-size:12px;letter-spacing:.005em;margin-bottom:10px}
    .input-wrap{position:relative}
    .input-icon{position:absolute;left:17px;top:50%;transform:translateY(-50%);
      display:flex;align-items:center;justify-content:center;color:#7e9b8a;pointer-events:none}
    input[type=email]{width:100%;height:60px;border-radius:15px;
      padding:0 18px 0 49px;border:1px solid rgba(60,104,72,.18);
      outline:0;color:#193c31;background:rgba(255,255,255,.77);
      font-size:16px;letter-spacing:-.02em;box-shadow:inset 0 1px 2px rgba(21,50,32,.035);
      transition:border-color .2s,box-shadow .2s,background .2s}
    input[type=email]::placeholder{color:#9aaca2}
    input[type=email]:focus{border-color:#6c9c81;background:#fff;
      box-shadow:0 0 0 4px rgba(88,147,109,.12),0 10px 25px rgba(25,70,45,.055)}
    .input-hint{font-size:11px;color:#83958c;line-height:1.55;margin:9px 0 23px}
    .pay-button{position:relative;display:flex;align-items:center;justify-content:space-between;
      gap:18px;width:100%;min-height:62px;padding:11px 11px 11px 23px;
      border:1px solid rgba(255,255,255,.12);border-radius:17px;
      background:linear-gradient(125deg,#245f4e,#154636 68%,#103c31);
      box-shadow:0 12px 29px rgba(26,91,64,.18),inset 0 1px rgba(255,255,255,.13);
      color:white;font-size:16px;font-weight:740;letter-spacing:-.015em;
      text-align:left;cursor:pointer;overflow:hidden;isolation:isolate;
      transition:transform .25s var(--ease),box-shadow .25s var(--ease),filter .2s}
    .pay-button:hover{transform:translateY(-2px);
      box-shadow:0 17px 34px rgba(24,83,54,.26),inset 0 1px rgba(255,255,255,.13)}
    .pay-button:active{transform:translateY(0)}
    .pay-button:focus-visible{outline:3px solid #8ec5a1;outline-offset:4px}
    .pay-button:disabled{opacity:.78;cursor:progress;transform:none}
    .button-sheen{position:absolute;z-index:0;inset:-40% auto -40% -80%;width:58%;
      transform:skewX(-19deg);background:linear-gradient(90deg,transparent,rgba(255,255,255,.11),transparent);
      animation:button-gloss 8s 2s ease-in-out infinite;pointer-events:none}
    .pay-text,.button-icon{position:relative;z-index:1}
    .button-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:11px;
      background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.12)}
    .terms{font-size:11px;line-height:1.75;color:#85958d;margin:20px 0 0}
    .terms a{text-decoration:underline;text-decoration-color:#a2b7aa;text-underline-offset:3px;
      color:#557362;transition:color .2s}
    .terms a:hover{color:#164e3a}
    .terms a:focus-visible,.footer a:focus-visible,.brand:focus-visible{outline:2px solid #41885c;outline-offset:3px;border-radius:3px}
    .security{display:flex;align-items:center;justify-content:center;gap:8px;margin:20px 0 0;
      color:#789286;font-size:11px;font-weight:690;letter-spacing:.004em}
    .security svg{color:#729c83}
    .unavailable{display:flex;gap:12px;border:1px solid rgba(161,103,54,.14);
      background:rgba(255,248,231,.55);padding:19px;border-radius:16px}
    .unavailable>span{font-size:25px;color:#996c48}
    .unavailable strong{font-size:14px}
    .unavailable p{font-size:12px;color:#786e61;line-height:1.55;margin:6px 0 0}
    .secondary-link{margin:20px 0 0;display:inline-flex;gap:8px;color:#426c55;font-size:13px;font-weight:740}
    .footer{display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap;
      padding:16px 0 0;color:#7a9084;font-size:11px;border-top:1px solid rgba(94,137,111,.11)}
    .footer-links{display:flex;align-items:center;flex-wrap:wrap;gap:8px 17px}
    .footer a{transition:color .18s}
    .footer a:hover{color:#245f4c}
    @keyframes orbit-drift{from{transform:translate3d(-24px,14px,0) scale(.99)}
      to{transform:translate3d(33px,-32px,0) scale(1.13)}}
    @keyframes float{0%,100%{translate:0 0}50%{translate:0 -9px}}
    @keyframes button-gloss{0%,44%,100%{left:-85%}60%{left:145%}}
    @keyframes reveal{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
    @media (max-width:1030px){
      .main{gap:36px;grid-template-columns:minmax(0,.95fr) minmax(0,1.05fr)}
      .visual{display:none}.flow-line{gap:7px}.flow-chip{padding:9px 10px;font-size:11px}
      .story h1{font-size:clamp(44px,5vw,60px)}
    }
    @media (max-width:760px){
      .page{padding:20px 18px 16px;max-width:580px}
      .brand{font-size:19px;gap:9px}.brand-symbol{width:33px;height:33px;border-radius:10px}
      .brand-note{font-size:9px;letter-spacing:.09em}
      .main{display:flex;flex-direction:column;align-items:stretch;gap:24px;
        padding:34px 0 28px}
      .story h1{font-size:clamp(37px,10vw,54px);letter-spacing:-.06em;line-height:1.09;
        margin-bottom:13px}
      .story h1 span{display:inline}
      .story-lead{font-size:14px;line-height:1.65;max-width:480px}
      .eyebrow{margin-bottom:15px;font-size:10px}
      .flow-line{display:none}
      .panel{padding:26px 23px 25px;border-radius:27px}
      .panel-shell::before{border-radius:28px}
      .panel h2{font-size:30px;margin:23px 0 9px}
      .panel-intro{margin-bottom:21px}
      .price-box{padding:16px 0 18px;margin-bottom:20px}
      .input-hint{margin-bottom:20px}
      .footer{font-size:10px}
    }
    @media(max-width:390px){
      .page{padding:17px 14px 15px}
      .story h1{font-size:37px}
      .panel{padding:22px 19px;border-radius:24px}
      .panel h2{font-size:28px}
      .brand-note{display:none}
      .main{padding-top:30px;gap:19px}
      .one-time{font-size:10px;padding:7px 9px}
    }
    @media(prefers-reduced-motion:reduce){
      *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;
        transition-duration:.01ms!important;scroll-behavior:auto!important}
    }
    @supports not (backdrop-filter:blur(1px)){
      .panel{background:#f8fcf9}
      .flow-chip,.visual-card{background:#f8faf6}
    }
  </style>
</head>
<body>
  <div class="background" aria-hidden="true">
    <div class="orb one"></div><div class="orb two"></div><div class="orb three"></div>
  </div>
  <div class="page">
    <header class="brandbar">
      <a class="brand" href="https://poehali-lead-board.onrender.com/" aria-label="Поехали — к презентации">
        <span class="brand-symbol" aria-hidden="true">↗</span><span>поехали<span style="color:#5c9473">.</span></span>
      </a>
      <div class="brand-note"><span class="tiny"></span> DIGITAL SKILL / КУРС</div>
    </header>

    <main class="main">
      <section class="story" aria-label="О курсе">
        <div class="eyebrow">GPT × TELEGRAM × АВТОМАТИЗАЦИЯ</div>
        <h1><span>Один шаг</span> <span class="light">до своей</span> системы.</h1>
        <p class="story-lead">От идеи до цифрового продукта: создайте Telegram-бота, настройте оплату и автоматическую выдачу материалов. Всё по шагам, в одном курсе.</p>
        <div class="flow-line" aria-hidden="true">
          <span class="flow-chip"><span class="mini">✦</span> GPT</span>
          <span class="flow-arrow">→</span>
          <span class="flow-chip"><span class="mini">◇</span> Telegram</span>
          <span class="flow-arrow">→</span>
          <span class="flow-chip"><span class="mini">↗</span> Автопродажи</span>
        </div>
        <div class="visual" aria-hidden="true">
          <div class="visual-card"><span class="vicon">✦</span> Ваша идея</div>
          <div class="visual-card"><span class="vicon">◉</span> Бот</div>
          <div class="visual-card"><span class="vicon">✓</span> Результат</div>
        </div>
      </section>

      <div class="panel-shell">
        <section class="panel" aria-labelledby="panel-heading">
          <div class="panel-top"><span>ДОСТУП К МАТЕРИАЛАМ</span><span class="stage">01 / 01</span></div>
          <h2 id="panel-heading">Всё готово.<br>Остался один шаг.</h2>
          <p class="panel-intro">Укажите почту, чтобы получить чек и информацию о доступе к курсу.</p>
          <div class="price-box">
            <div><div class="price-caption">СТОИМОСТЬ ДОСТУПА</div><strong class="price">%%PRICE%%</strong></div>
            <span class="one-time">Без подписки</span>
          </div>
          %%FORM%%
          <div class="security">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2.5"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
            Защищённая оплата · Чек на электронную почту
          </div>
        </section>
      </div>
    </main>
    <footer class="footer">
      <span>%%SELLER%%</span>
      <nav class="footer-links" aria-label="Информация и условия">
        <a href="/terms">Оферта</a>
        <a href="/privacy">Конфиденциальность</a>
        <a href="/refund">Возвраты</a>
        <a href="/contacts">Реквизиты</a>
      </nav>
    </footer>
  </div>
  <script>
    (function () {
      var form = document.getElementById('checkout-form');
      if (!form) return;
      var button = document.getElementById('pay-button');
      var label = button.querySelector('.pay-text');
      var original = label.textContent;
      window.addEventListener('pageshow', function () {
        button.disabled = false;
        button.removeAttribute('aria-busy');
        label.textContent = original;
      });
      form.addEventListener('submit', function (event) {
        if (!form.checkValidity()) {
          event.preventDefault();
          form.reportValidity();
          return;
        }
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        label.textContent = 'Оформляем…';
      });
    }());
  </script>
</body>
</html>"""
    return (
        page.replace("%%FORM%%", form_markup)
        .replace("%%PRICE%%", price_value)
        .replace("%%SELLER%%", seller_value)
    )
