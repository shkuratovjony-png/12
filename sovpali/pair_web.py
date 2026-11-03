from datetime import datetime
import html
from urllib.parse import quote
from flask import abort
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

TTL=60*60*24*30

def _ser(secret): return URLSafeTimedSerializer(secret,salt='sovpali-pair-web-v1')
def _e(v): return html.escape(str(v or ''))
def _v(row,key,default=''):
    try: return row[key]
    except Exception:
        try: return row.get(key,default)
        except Exception: return default

def pair_link(base_url,viewer_uid,candidate_uid,secret):
    base=(base_url or '').strip().rstrip('/')
    if not base: return ''
    token=_ser(secret).dumps({'v':int(viewer_uid),'c':int(candidate_uid)})
    return f'{base}/s/p/{token}'

def _load(token,secret):
    try:
        d=_ser(secret).loads(token,max_age=TTL)
        return int(d['v']),int(d['c'])
    except (BadSignature,SignatureExpired,KeyError,TypeError,ValueError): abort(404)

def _age(v):
    try:
        d=datetime.strptime(str(v),'%d.%m.%Y'); t=datetime.now()
        return t.year-d.year-((t.month,t.day)<(d.month,d.day))
    except Exception: return None

def _factors(a,b,zodiac_fn,lifepath_fn):
    goal=96 if _v(a,'goal')==_v(b,'goal') else 68
    priority=95 if _v(a,'priority')==_v(b,'priority') else 71
    astro=72; num=70
    try:
        za,zb=zodiac_fn(_v(a,'birth_date')),zodiac_fn(_v(b,'birth_date'))
        el={'Овен':'Огонь','Лев':'Огонь','Стрелец':'Огонь','Телец':'Земля','Дева':'Земля','Козерог':'Земля','Близнецы':'Воздух','Весы':'Воздух','Водолей':'Воздух','Рак':'Вода','Скорпион':'Вода','Рыбы':'Вода'}
        good={'Огонь':{'Огонь','Воздух'},'Воздух':{'Воздух','Огонь'},'Земля':{'Земля','Вода'},'Вода':{'Вода','Земля'}}
        astro=91 if el.get(zb) in good.get(el.get(za),set()) else 66
    except Exception: pass
    try:
        la,lb=lifepath_fn(_v(a,'birth_date')),lifepath_fn(_v(b,'birth_date'))
        num=92 if la==lb else (86 if abs(int(la)-int(lb)) in (1,3) else 67)
    except Exception: pass
    return goal,priority,astro,num

JS="""<script>document.addEventListener('DOMContentLoaded',()=>{setTimeout(()=>document.querySelector('.loader')?.classList.add('hide'),820);requestAnimationFrame(()=>document.querySelectorAll('.bar i').forEach((el,i)=>setTimeout(()=>el.style.width=(el.dataset.value||0)+'%',160+i*90)))})</script>"""

def page(title,body,loader=False):
    ld='' if not loader else '<div class="loader"><div class="loader-box"><div class="loader-heart">💗</div><div class="loader-title">Считаем ваше совпадение</div><div class="loader-sub">Сверяем цели, ценности и ритмы</div><div class="dots"><i></i><i></i><i></i></div></div></div>'
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#120b10"><title>{_e(title)}</title><link rel="stylesheet" href="/static/pair_web.css?v=3"></head><body>{ld}<div class="bg"></div><div class="noise"></div><div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div><main class="w"><div class="top"><div class="brand">💞 <b>Совпали</b></div><div class="live">СОВМЕСТИМОСТЬ</div></div>{body}<div class="footer">Совпали · знакомства, где важнее не свайп, а совпадение</div></main>{JS}</body></html>'''

def render_pair(token,a,c,sv,rs,zodiac_fn,lifepath_fn,astro,num,price,demo=False):
    age=_age(_v(c,'birth_date')); age_text=f', {age}' if age else ''
    try: sign=_e(zodiac_fn(_v(c,'birth_date')))
    except Exception: sign='—'
    try: life=_e(lifepath_fn(_v(c,'birth_date')))
    except Exception: life='—'
    g,p,ast,nm=_factors(a,c,zodiac_fn,lifepath_fn)
    reasons=''.join(f'<div class="reason"><div class="check">✓</div><p>{_e(x)}</p></div>' for x in rs) or '<div class="reason"><div class="check">✓</div><p>Система нашла несколько сильных пересечений в ваших профилях.</p></div>'
    intro='<div class="demo">Демо-режим · реальные данные доступны только по персональной ссылке из Telegram.</div>' if demo else ''
    pay='#' if demo else f'/s/pay/{quote(token)}'; cls='cta off' if demo else 'cta'
    astro_html=str(astro or '').replace('\n','<br>'); num_html=str(num or '').replace('\n','<br>')
    ai=_e(str(_v(a,'name','Ты')).strip()[:1].upper() or 'Я'); ci=_e(str(_v(c,'name','❤')).strip()[:1].upper() or '❤')
    factors=''.join(f'<div class="factor"><div class="factor-head"><span>{label}</span><b>{val}%</b></div><div class="bar"><i data-value="{val}"></i></div></div>' for label,val in [('Цель отношений',g),('Ценности и приоритет',p),('Астрологический ритм',ast),('Нумерологический ритм',nm)])
    rich=(f'<section class="glass card"><h2>✨ Астрологический профиль</h2><div class="insight">{astro_html}</div></section>' if astro_html else '')+(f'<section class="glass card"><h2>🔢 Нумерология пары</h2><div class="insight">{num_html}</div></section>' if num_html else '')
    body=f'''{intro}<section class="glass hero"><div class="kicker">Ваше сильное совпадение</div><div class="title">{_e(_v(c,'name'))}{age_text}</div><div class="sub">{_e(_v(c,'city'))} · {_e(_v(c,'goal'))}</div><div class="match-stage"><div class="avatar"><div class="initial">{ai}</div></div><div class="connect"><div class="heart">💗</div><div class="line"></div></div><div class="avatar"><div class="initial">{ci}</div></div></div><div class="chips"><span class="chip">❤️ {_e(_v(c,'goal'))}</span><span class="chip">🧭 {_e(_v(c,'priority'))}</span><span class="chip">✨ {sign}</span><span class="chip">🔢 Путь {life}</span></div><div class="score-wrap"><div class="ring" style="--score:{int(sv)}"><svg viewBox="0 0 112 112"><defs><linearGradient id="grad"><stop offset="0%" stop-color="#ff4e86"/><stop offset="55%" stop-color="#ff9a7b"/><stop offset="100%" stop-color="#ffd36c"/></linearGradient></defs><circle class="track" cx="56" cy="56" r="48"/><circle class="prog" cx="56" cy="56" r="48"/></svg><div class="ring-text"><b>{int(sv)}%</b><span>совместимости</span></div></div><div class="score-copy"><h2>Вы не случайная пара</h2><p>Совпадение складывается из нескольких слоёв — намерений, ценностей и ваших личных ритмов.</p></div></div></section><section class="glass card"><h2>Что держит ваше совпадение</h2>{factors}</section><section class="glass card"><h2>Почему вас свело именно сейчас</h2>{reasons}</section>{rich}<section class="glass card"><div class="kicker">Следующий шаг</div><h2 style="margin-top:7px">Не просто контакт — готовый старт знакомства</h2><div class="teaser"><div class="ico">💬</div><div><strong>Контакт после взаимного «да»</strong><small>Вторая сторона сначала подтверждает интерес.</small></div></div><div class="teaser"><div class="ico">✨</div><div><strong>Как начать переписку</strong><small>Персональный старт без банального «привет, как дела?»</small></div></div><div class="teaser"><div class="ico">🧠</div><div><strong>Что важно не испортить в начале</strong><small>Подсказки на основе вашего совпадения.</small></div></div><a class="{cls}" href="{pay}">💖 Открыть знакомство · {price} ₽</a><div class="note">Платит только инициатор. Контакт откроется только после взаимного интереса.</div><div class="trust"><span>🔒 защищённая ссылка</span><span>⚡ быстрый переход</span><span>💞 только при взаимности</span></div></section>'''
    return page('Ваша пара · Совпали',body,True)

def register_pair_web(app,ns):
    one,profile,score_fn,reasons_fn=ns['one'],ns['profile'],ns['score'],ns['reasons']; setting=ns.get('setting'); secret=ns['FLASK_SECRET']; zodiac_fn=ns.get('zodiac'); lifepath_fn=ns.get('lifepath')
    @app.get('/s')
    def home():
        try: n=int(one('SELECT COUNT(*) c FROM profiles')['c'])
        except Exception: n=0
        return page('Совпали',f'<section class="glass home-hero"><div class="kicker">Совпали · веб-версия</div><h1>Знакомство начинается не со свайпа.</h1><div class="sub">Мы собираем сигналы совместимости в один понятный сценарий: кто перед тобой, почему вы совпали и как сделать первый шаг без неловкости.</div><div class="home-stats"><div class="stat"><small>Анкет в подборе</small><b>{n}</b></div><div class="stat"><small>Главная метрика</small><b>Совпадение</b></div></div><a class="cta" href="/s/demo">💗 Посмотреть живое демо</a></section>')
    @app.get('/s/demo')
    def demo():
        a={'name':'Ты','birth_date':'05.01.1990','city':'Владивосток','goal':'Любовь и семья','priority':'Ценности'}; c={'name':'Анна','birth_date':'14.05.1993','city':'Владивосток','goal':'Любовь и семья','priority':'Ценности'}; price=int(setting('unlock_price_rub','100') or 100) if setting else 100
        return render_pair('',a,c,92,['Вы хотите похожего сценария отношений','Совпадает главный ориентир — общие ценности','Один город — знакомство реально продолжить офлайн'],zodiac_fn,lifepath_fn,'<b>Телец + земная стихия.</b><br>Темпераменты легче считывают спокойствие друг друга.','<b>Совместный ритм пары.</b><br>В реальной карточке расчёт строится по вашим датам рождения.',price,True)
    @app.get('/s/p/<token>')
    def pair(token):
        v,cid=_load(token,secret); a,b=profile(v),profile(cid)
        if not a or not b: abort(404)
        try: sv=int(score_fn(a,b))
        except Exception: sv=0
        try: rs=list(reasons_fn(a,b))
        except Exception: rs=[]
        astro=num=''
        try:
            if ns.get('pc_astro_copy'): astro=ns['pc_astro_copy'](a,b)
        except Exception: pass
        try:
            if ns.get('pc_num_copy'): num=ns['pc_num_copy'](a,b)
        except Exception: pass
        try:
            if ns.get('audit'): ns['audit'](v,'web_pair_view',{'candidate_user_id':cid,'score':sv})
        except Exception: pass
        price=int(setting('unlock_price_rub','100') or 100) if setting else 100
        return render_pair(token,a,b,sv,rs,zodiac_fn,lifepath_fn,astro,num,price,False)
    @app.get('/s/pay/<token>')
    def pay(token):
        v,cid=_load(token,secret); a,b=profile(v),profile(cid)
        if not a or not b: abort(404)
        price=int(setting('unlock_price_rub','100') or 100) if setting else 100
        body=f'<section class="glass hero"><div class="kicker">Знакомство с {_e(_v(b,"name"))}</div><div class="title">{price} ₽</div><div class="sub">Короткая оплата через СБП. После подтверждения второй стороне отправится запрос.</div></section><section class="glass card"><h2>Как пройдёт оплата</h2>'+''.join(f'<div class="reason"><div class="check">{i}</div><p>{t}</p></div>' for i,t in enumerate(['Выбираешь СБП и свой банк.','Подтверждаешь платёж в приложении банка.','Мы отправляем запрос второй стороне.','После взаимного «да» открывается контакт и старт общения.'],1))+f'<div class="cta off">⚡ СБП подключаем</div><a class="cta" style="background:linear-gradient(135deg,#ffffff18,#ffffff0d);box-shadow:none" href="/s/p/{quote(token)}">← Вернуться к паре</a><div class="note">Сейчас деньги не списываются.</div></section>'
        return page('Оплата · Совпали',body)
