from datetime import datetime
import html
from urllib.parse import quote
from flask import abort
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

TTL=60*60*24*30

def _ser(secret):
    return URLSafeTimedSerializer(secret,salt='sovpali-pair-web-v1')

def pair_link(base_url,viewer_uid,candidate_uid,secret):
    base=(base_url or '').strip().rstrip('/')
    if not base: return ''
    token=_ser(secret).dumps({'v':int(viewer_uid),'c':int(candidate_uid)})
    return f'{base}/s/p/{token}'

def _load(token,secret):
    try:
        d=_ser(secret).loads(token,max_age=TTL)
        return int(d['v']),int(d['c'])
    except (BadSignature,SignatureExpired,KeyError,TypeError,ValueError):
        abort(404)

def _e(v): return html.escape(str(v or ''))

def _age(v):
    try:
        d=datetime.strptime(str(v),'%d.%m.%Y'); t=datetime.now()
        return t.year-d.year-((t.month,t.day)<(d.month,d.day))
    except Exception: return None

CSS='''*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#fff9fa,#fff1f5);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial;color:#281b22}.w{max-width:650px;margin:auto;padding:16px 12px 60px}.brand{font-size:26px;font-weight:900;margin:4px 2px 16px}.brand b{color:#ff5b87}.c{background:#fff;border:1px solid #f2dce3;border-radius:24px;padding:20px;margin-top:14px;box-shadow:0 16px 40px #4a22300d}.hero{padding:0;overflow:hidden}.pic{height:320px;background:radial-gradient(circle at 30% 20%,#ffe9ef,#ffc8d7 45%,#ffafc6);display:flex;align-items:center;justify-content:center;font-size:82px;position:relative}.score{position:absolute;left:15px;bottom:15px;background:#251a20e8;color:#fff;border-radius:16px;padding:10px 13px}.score b{font-size:24px}.pad{padding:20px}.name{font-size:29px;font-weight:900}.muted{color:#806b74;line-height:1.5}.tags{display:flex;gap:7px;flex-wrap:wrap;margin-top:13px}.tag{background:#fff0f4;color:#744452;padding:8px 10px;border-radius:12px;font-size:13px;font-weight:700}h2{font-size:19px;margin:0 0 12px}.r{display:flex;gap:10px;border-top:1px solid #f8e8ed;padding:10px 0}.r:first-of-type{border-top:0}.ok{width:25px;height:25px;border-radius:50%;background:#e8f8f2;color:#168b68;display:flex;align-items:center;justify-content:center;font-weight:900;flex:0 0 25px}.r p{margin:2px 0;line-height:1.45}.rich{line-height:1.55;color:#4d3942}.cta{display:block;text-decoration:none;text-align:center;margin-top:15px;padding:15px;border-radius:16px;background:linear-gradient(135deg,#ff5b87,#ff789a);color:#fff;font-weight:900}.dark{background:#2d2026}.off{background:#d9cbd0;color:#806e75}.note{text-align:center;color:#9b838d;font-size:12px;line-height:1.45;margin-top:11px}.demo{background:#2d2026;color:#fff;border-radius:12px;padding:10px 12px;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.m{background:#fff5f8;border:1px solid #fae1e8;border-radius:15px;padding:13px}.m small{display:block;color:#806b74;margin-bottom:5px}.footer{text-align:center;color:#aa929b;font-size:12px;margin-top:22px}'''

def page(title,body):
    return f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title><style>{CSS}</style><body><div class="w"><div class="brand">💞 <b>Совпали</b></div>{body}<div class="footer">Совпали · знакомства по совместимости</div></div></body></html>'

def render_pair(token,c,sv,rs,zodiac_fn,lifepath_fn,astro,num,price,demo=False):
    age=_age(c['birth_date']); age_text=f', {age}' if age else ''
    try: sign=_e(zodiac_fn(c['birth_date'])) if zodiac_fn else '—'
    except Exception: sign='—'
    try: life=_e(lifepath_fn(c['birth_date'])) if lifepath_fn else '—'
    except Exception: life='—'
    reasons=''.join(f'<div class="r"><div class="ok">✓</div><p>{_e(x)}</p></div>' for x in rs)
    intro='<div class="demo">Демо. Реальные данные открываются только по персональной ссылке из Telegram.</div>' if demo else ''
    pay='#' if demo else f'/s/pay/{quote(token)}'; cls='cta off' if demo else 'cta'
    return page('Пара · Совпали',f'''{intro}<div class="c hero"><div class="pic">💞<div class="score"><b>{sv}%</b> совместимости</div></div><div class="pad"><div class="name">{_e(c['name'])}{age_text}</div><div class="muted">{_e(c['city'])}<br>Цель: {_e(c['goal'])}</div><div class="tags"><span class="tag">❤️ {_e(c['goal'])}</span><span class="tag">🧭 {_e(c['priority'])}</span><span class="tag">✨ {sign}</span><span class="tag">🔢 Путь {life}</span></div></div></div><div class="c"><h2>Почему вы подходите</h2>{reasons}</div>{('<div class="c"><h2>✨ Астрологический профиль</h2><div class="rich">'+astro+'</div></div>') if astro else ''}{('<div class="c"><h2>🔢 Нумерология пары</h2><div class="rich">'+num+'</div></div>') if num else ''}<div class="c"><h2>🔒 Контакт + старт переписки</h2><div class="muted">После оплаты второй стороне уйдёт запрос. Контакт откроется только после взаимного согласия.</div><a class="{cls}" href="{pay}">Открыть знакомство · {price} ₽</a><div class="note">Платит только инициатор. После взаимного «да» здесь появится контакт и персональный старт общения.</div></div>''')

def register_pair_web(app,ns):
    one,profile,score_fn,reasons_fn=ns['one'],ns['profile'],ns['score'],ns['reasons']
    setting=ns.get('setting'); secret=ns['FLASK_SECRET']; zodiac_fn=ns.get('zodiac'); lifepath_fn=ns.get('lifepath')
    @app.get('/s')
    def home():
        try: n=int(one('SELECT COUNT(*) c FROM profiles')['c'])
        except Exception: n=0
        return page('Совпали',f'<div class="c"><div style="color:#b26f84;font-size:13px;font-weight:800">ВЕБ-ВЕРСИЯ «СОВПАЛИ»</div><h1>Страница вашей пары</h1><div class="rich">Telegram остаётся местом подбора. Здесь — подробная совместимость, платные функции и инструменты общения.</div><div class="grid" style="margin-top:16px"><div class="m"><small>Анкет в базе</small><b>{n}</b></div><div class="m"><small>Формат</small><b>Мобильный</b></div></div><a class="cta" href="/s/demo">Посмотреть демо</a></div>')
    @app.get('/s/demo')
    def demo():
        c={'name':'Анна','birth_date':'14.05.1993','city':'Владивосток','goal':'Любовь и семья','priority':'Ценности'}
        price=int(setting('unlock_price_rub','100') or 100) if setting else 100
        return render_pair('',c,92,['Похожий сценарий отношений','Совпадает главный ориентир — общие ценности','Один город — знакомство реально продолжить офлайн'],zodiac_fn,lifepath_fn,'<b>Телец + земная стихия.</b><br>В реальной карточке здесь будет расчёт вашей пары.','<b>Числа жизненного пути и число пары.</b><br>Расчёт берётся из дат рождения.',price,True)
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
        return render_pair(token,b,sv,rs,zodiac_fn,lifepath_fn,astro,num,price,False)
    @app.get('/s/pay/<token>')
    def pay(token):
        v,cid=_load(token,secret); b=profile(cid)
        if not profile(v) or not b: abort(404)
        price=int(setting('unlock_price_rub','100') or 100) if setting else 100
        return page('Оплата · Совпали',f'<div class="c"><div style="color:#b26f84;font-size:13px;font-weight:800">ЗНАКОМСТВО С {_e(b["name"]).upper()}</div><h1>{price} ₽</h1><div class="rich">Экран уже готов под короткую оплату через СБП. Эквайринг пока не включён, поэтому деньги сейчас не списываются.</div><div class="c" style="box-shadow:none;background:#fff7f9"><b>После подключения:</b><br><br>1. СБП → выбрать банк.<br>2. Подтвердить платёж.<br>3. Второй стороне уйдёт запрос.<br>4. После взаимного «да» откроется контакт.</div><div class="cta off">СБП подключаем</div><a class="cta dark" href="/s/p/{quote(token)}">Вернуться к паре</a></div>')
