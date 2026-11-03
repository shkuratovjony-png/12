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

def _v(row,key,default=''):
    try:
        return row[key]
    except Exception:
        try: return row.get(key,default)
        except Exception: return default

def _age(v):
    try:
        d=datetime.strptime(str(v),'%d.%m.%Y'); t=datetime.now()
        return t.year-d.year-((t.month,t.day)<(d.month,d.day))
    except Exception: return None

def _factor_scores(a,b,zodiac_fn=None,lifepath_fn=None):
    goal=96 if str(_v(a,'goal',''))==str(_v(b,'goal','')) else 68
    priority=95 if str(_v(a,'priority',''))==str(_v(b,'priority','')) else 71
    astro=72; num=70
    try:
        za,zb=zodiac_fn(a['birth_date']),zodiac_fn(b['birth_date'])
        element={'ĞĞ²ĞµĞ½':'ĞĞ³Ğ¾Ğ½ÑŒ','Ğ›ĞµĞ²':'ĞĞ³Ğ¾Ğ½ÑŒ','Ğ¡Ñ‚Ñ€ĞµĞ»ĞµÑ†':'ĞĞ³Ğ¾Ğ½ÑŒ','Ğ¢ĞµĞ»ĞµÑ†':'Ğ—ĞµĞ¼Ğ»Ñ','Ğ”ĞµĞ²Ğ°':'Ğ—ĞµĞ¼Ğ»Ñ','ĞšĞ¾Ğ·ĞµÑ€Ğ¾Ğ³':'Ğ—ĞµĞ¼Ğ»Ñ','Ğ‘Ğ»Ğ¸Ğ·Ğ½ĞµÑ†Ñ‹':'Ğ’Ğ¾Ğ·Ğ´ÑƒÑ…','Ğ’ĞµÑÑ‹':'Ğ’Ğ¾Ğ·Ğ´ÑƒÑ…','Ğ’Ğ¾Ğ´Ğ¾Ğ»ĞµĞ¹':'Ğ’Ğ¾Ğ·Ğ´ÑƒÑ…','Ğ Ğ°Ğº':'Ğ’Ğ¾Ğ´Ğ°','Ğ¡ĞºĞ¾Ñ€Ğ¿Ğ¸Ğ¾Ğ½':'Ğ’Ğ¾Ğ´Ğ°','Ğ Ñ‹Ğ±Ñ‹':'Ğ’Ğ¾Ğ´Ğ°'}
        good={'ĞĞ³Ğ¾Ğ½ÑŒ':{'ĞĞ³Ğ¾Ğ½ÑŒ','Ğ’Ğ¾Ğ·Ğ´ÑƒÑ…'},'Ğ’Ğ¾Ğ·Ğ´ÑƒÑ…':{'Ğ’Ğ¾Ğ·Ğ´ÑƒÑ…','ĞĞ³Ğ¾Ğ½ÑŒ'},'Ğ—ĞµĞ¼Ğ»Ñ':{'Ğ—ĞµĞ¼Ğ»Ñ','Ğ’Ğ¾Ğ´Ğ°'},'Ğ’Ğ¾Ğ´Ğ°':{'Ğ’Ğ¾Ğ´Ğ°','Ğ—ĞµĞ¼Ğ»Ñ'}}
        astro=91 if element.get(zb) in good.get(element.get(za),set()) else 66
    except Exception: pass
    try:
        la,lb=lifepath_fn(a['birth_date']),lifepath_fn(b['birth_date'])
        num=92 if la==lb else (86 if abs(int(la)-int(lb)) in (1,3) else 67)
    except Exception: pass
    return goal,priority,astro,num


JS="""<script>document.addEventListener('DOMContentLoaded',function(){setTimeout(function(){var l=document.querySelector('.loader');if(l)l.classList.add('hide')},820);requestAnimationFrame(function(){document.querySelectorAll('.bar i').forEach(function(el){var v=Math.max(0,Math.min(100,parseInt(el.dataset.value||'0',10)));setTimeout(function(){el.style.width=v+'%'},180)})})});</script>"""

def page(title,body,loader=False):
    ld='' if not loader else '<div class="loader"><div class="loader-box"><div class="loader-heart">ğŸ’—</div><div class="loader-title">Ğ¡Ñ‡Ğ¸Ñ‚Ğ°ĞµĞ¼ Ğ²Ğ°ÑˆĞµ ÑĞ¾Ğ²Ğ¿Ğ°Ğ´ĞµĞ½Ğ¸Ğµ</div><div class="loader-sub">Ğ¡Ğ²ĞµÑ€ÑĞµĞ¼ Ñ†ĞµĞ»Ğ¸, Ñ†ĞµĞ½Ğ½Ğ¾ÑÑ‚Ğ¸ Ğ¸ Ñ€Ğ¸Ñ‚Ğ¼Ñ‹</div><div class="dots"><i></i><i></i><i></i></div></div></div>'
    return f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#120b10"><title>{_e(title)}</title><link rel="stylesheet" href="/static/pair_web.css?v=2"></head><body>{ld}<div class="bg"></div><div class="noise"></div><div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div><div class="w"><div class="top"><div class="brand">ğŸ’ <b>Ğ¡Ğ¾Ğ²Ğ¿Ğ°Ğ»Ğ¸</b></div><div class="live">Ğ¡ĞĞ’ĞœĞ•Ğ¡Ğ¢Ğ˜ĞœĞĞ¡Ğ¢Ğ¬</div></div>{body}<div class="footer">Ğ¡Ğ¾Ğ²Ğ¿Ğ°Ğ»Ğ¸ Â· Ğ·Ğ½Ğ°ĞºĞ¾Ğ¼ÑÑ‚Ğ²Ğ°, Ğ³Ğ´Ğµ Ğ²Ğ°Ğ¶Ğ½ĞµĞµ Ğ½Ğµ ÑĞ²Ğ°Ğ¹Ğ¿, Ğ° ÑĞ¾Ğ²Ğ¿Ğ°Ğ´ĞµĞ½Ğ¸Ğµ</div></div>{JS}</body></html>'

def render_pair(token,a,c,sv,rs,zodiac_fn,lifepath_fn,astro,num,price,demo=False):
    age=_age(c['birth_date']); age_text=f', {age}' if age else ''
    try: sign=_e(zodiac_fn(c['birth_date'])) if zodiac_fn else 'â€”'
    except Exception: sign='â€”'
    try: life=_e(lifepath_fn(c['birth_date'])) if lifepath_fn else 'â€”'
    except Exception: life='â€”'
    viewer_initial=_e(str(_v(a,'name','Ğ¢Ñ‹')).strip()[:1].upper() or 'Ğ¯')
    candidate_initial=_e(str(c['name']).strip()[:1].upper() or 'â¤')
    goal_s,priority_s,astro_s,num_s=_factor_scores(a,c,zodiac_fn,lifepath_fn)
    reasons=''.join(f'<div class="reason"><div class="check">âœ“</div><p>{_e(x)}</p></div>' for x in rs) or '<div class="reason"><div class="check">âœ“</div><p>Ğ¡Ğ¸ÑÑ‚ĞµĞ¼Ğ° Ğ½Ğ°ÑˆĞ»Ğ° Ğ½ĞµÑĞºĞ¾Ğ»ÑŒĞºĞ¾ ÑĞ¸Ğ»ÑŒĞ½Ñ‹Ñ… Ğ¿ĞµÑ€ĞµÑĞµÑ‡ĞµĞ½Ğ¸Ğ¹ Ğ² Ğ²Ğ°ÑˆĞ¸Ñ… Ğ¿Ñ€Ğ¾Ñ„Ğ¸Ğ»ÑÑ….</p></div>'
    intro='<div class="demo">Ğ”ĞµĞ¼Ğ¾-Ñ€ĞµĞ¶Ğ¸Ğ¼ Â· Ñ€ĞµĞ°Ğ»ÑŒĞ½Ñ‹Ğµ Ğ´Ğ°Ğ½Ğ½Ñ‹Ğµ Ğ´Ğ¾ÑÑ‚ÑƒĞ¿Ğ½Ñ‹ Ñ‚Ğ¾Ğ»ÑŒĞºĞ¾ Ğ¿Ğ¾ Ğ¿ĞµÑ€ÑĞ¾Ğ½Ğ°Ğ»ÑŒĞ½Ğ¾Ğ¹ ÑÑÑ‹Ğ»ĞºĞµ Ğ¸Ğ· Telegram.</div>' if demo else ''
    pay='#' if demo else f'/s/pay/{quote(token)}'; cls='cta off' if demo else 'cta'
    astro_html=str(astro or '').replace('\n','<br>'); num_html=str(num or '').replace('\n','<br>')
    return page('Ğ’Ğ°ÑˆĞ° Ğ¿Ğ°Ñ€Ğ° Â· Ğ¡Ğ¾Ğ²Ğ¿Ğ°Ğ»Ğ¸',f'''{intro}<section class="glass hero"><div class="kicker">Ğ’Ğ°ÑˆĞµ ÑĞ¸Ğ»ÑŒĞ½Ğ¾Ğµ ÑĞ¾Ğ²Ğ¿Ğ°Ğ´ĞµĞ½Ğ¸Ğµ</div><div class="title">{_e(c['name'])}{age_text}</div><div class="sub">{_e(c['city'])} Â· {_e(c['goal'])}</div><div class="match-stage"><div class="avatar"><div class="initial">{viewer_initial}</div></div><div class="connect"><div class="heart">ğŸ’—</div><div class="line"></div></div><div class="avatar"><div class="initial">{candidate_initial}</div></div></div><div class="chips"><span class="chip">â¤ï¸ {_e(c['goal'])}</span><span class="chip">ğŸ§­ {_e(c['priority'])}</span><span class="chip">âœ¨ {sign}</span><span class="chip">ğŸ”¢ ĞŸÑƒÑ‚ÑŒ {life}</span></div><div class="score-wrap"><div class="ring" style="--score:{int(sv)}"><svg viewBox="0 0 112 112"><defs><linearGradient id="grad"><stop offset="0%" stop-color="#ff4e86"/><stop offset="55%" stop-color="#ff9a7b"/><stop offset="100%" stop-color="#ffd36c"/></linearGradient></defs><circle class="track" cx="56" cy="56" r="48"/><circle class="prog" cx="56" cy="56" r="48"/></svg><div class="ring-text"><b>{int(sv)}%</b><span>ÑĞ¾Ğ²Ğ¼ĞµÑÑ‚Ğ¸Ğ¼Ğ¾ÑÑ‚Ğ¸</span></div></div><div class="score-copy"><h2>Ğ’Ñ‹ Ğ½Ğµ ÑĞ»ÑƒÑ‡Ğ°Ğ¹Ğ½Ğ°Ñ Ğ¿Ğ°Ñ€Ğ°</h2><p>Ğ¡Ğ¾Ğ²Ğ¿Ğ°Ğ´ĞµĞ½Ğ¸Ğµ ÑĞºĞ»Ğ°Ğ´Ñ‹Ğ²Ğ°ĞµÑ‚ÑÑ ÑÑ€Ğ°Ğ·Ñƒ Ğ¸Ğ· Ğ½ĞµÑĞºĞ¾Ğ»ÑŒĞºĞ¸Ñ… ÑĞ»Ğ¾Ñ‘Ğ². Ğ§ĞµĞ¼ Ğ±Ğ¾Ğ»ÑŒÑˆĞµ ÑĞ¸Ğ»ÑŒĞ½Ñ‹Ñ… Ğ¿ĞµÑ€ĞµÑĞµÑ‡ĞµĞ½Ğ¸Ğ¹, Ñ‚ĞµĞ¼ ĞµÑÑ‚ĞµÑÑ‚Ğ²ĞµĞ½Ğ½ĞµĞµ Ğ¾Ñ‰ÑƒÑ‰Ğ°ĞµÑ‚ÑÑ Ğ·Ğ½Ğ°ĞºĞ¾Ğ¼ÑÑ‚Ğ²Ğ¾.</p></div></div></section><section class="glass card"><h2>Ğ§Ñ‚Ğ¾ Ğ´ĞµÑ€Ğ¶Ğ¸Ñ‚ Ğ²Ğ°ÑˆĞµ ÑĞ¾Ğ²Ğ¿Ğ°Ğ´ĞµĞ½Ğ¸Ğµ</h2><div class="factor"><div class="factor-head"><span>Ğ¦ĞµĞ»ÑŒ Ğ¾Ñ‚Ğ½Ğ¾ÑˆĞµĞ½Ğ¸Ğ¹</span><b>{goal_s}%</b></div><div class="bar"><i data-value="{goal_s}"></i></div></div><div class="factor"><div class="factor-head"><span>Ğ¦ĞµĞ½Ğ½Ğ¾ÑÑ‚Ğ¸ Ğ¸ Ğ¿Ñ€Ğ¸Ğ¾Ñ€Ğ¸Ñ‚ĞµÑ‚</span><b>{priority_s}%</b></div><div class="bar"><i data-value="{priority_s}"></i></div></div><div class="factor"><div class="factor-head"><span>ĞÑÑ‚Ñ€Ğ¾Ğ»Ğ¾Ğ³Ğ¸Ñ‡ĞµÑĞºĞ¸Ğ¹ Ñ€Ğ¸Ñ‚Ğ¼</span><b>{astro_s}%</b></div><div class="bar"><i data-value="{astro_s}"></i></div></div><div class="factor"><div class="factor-head"><span>ĞÑƒĞ¼ĞµÑ€Ğ¾Ğ»Ğ¾Ğ³Ğ¸Ñ‡ĞµÑĞºĞ¸Ğ¹ Ñ€Ğ¸Ñ‚Ğ¼</span><b>{num_s}%</b></div><div class="bar"><i data-value="{num_s}"></i></div></div></section><section class="glass card"><h2>ĞŸĞ¾Ñ‡ĞµĞ¼Ñƒ Ğ²Ğ°Ñ ÑĞ²ĞµĞ»Ğ¾ Ğ¸Ğ¼ĞµĞ½Ğ½Ğ¾ ÑĞµĞ¹Ñ‡BÃFğ½ ÈùíÉ•…Í½¹Íôğ½Í•Ñ¥½¸ùì œñÍ•Ñ¥½¸±…ÍÌô‰±…ÍÌ…Éˆøñ ÈûŠr ƒBCFFFBûBïBûBÏBãFB×FBëBãBäƒBÿFBûFBãBïF0ğ½ Èøñ‘¥Ø±…ÍÌô‰¥¹Í¥¡Ğˆøœ­…ÍÑÉ½}¡Ñµ°¬œğ½‘¥Øøğ½Í•Ñ¥½¸øœ¤¥˜…ÍÑÉ½}¡Ñµ°•±Í”€œõì œñÍ•Ñ¥½¸±…ÍÌô‰±…ÍÌ…Éˆøñ ÈûÂ~RˆƒBwFBóB×FBûBïBûBÏBãF<ƒBÿBÃFF,ğ½ Èøñ‘¥Ø±…ÍÌô‰¥¹Í¥¡Ğˆøœ­¹Õµ}¡Ñµ°¬œğ½‘¥Øøğ½Í•Ñ¥½¸øœ¤¥˜¹Õµ}¡Ñµ°•±Í”€œôñÍ•Ñ¥½¸±…ÍÌô‰±…ÍÌ…Éˆøñ‘¥Ø±…ÍÌô‰­¥­•ÈˆûB‡BïB×BÓFF;F'BãBäƒF#BÃBÌğ½‘¥Øøñ ÈÍÑå±”ô‰µ…É¥¸µÑ½ÀèİÁàˆûBwBÔƒBÿFBûFFBøƒBëBûB÷FBÃBëFƒŠPƒBÏBûFBûBËF/BäƒFFBÃFFƒBßB÷BÃBëBûBóFFBËBÀğ½ Èøñ‘¥Ø±…ÍÌô‰Ñ•…Í•Èˆøñ‘¥Ø±…ÍÌô‰¥¼ˆûÂ~B¬ğ½‘¥Øøñ‘¥ØøñÍÑÉ½¹œûBkBûB÷FBÃBëFƒBÿBûFBïBÔƒBËBßBÃBãBóB÷BûBÏBøƒ
¯BÓBÃ
ìğ½ÍÑÉ½¹œøñÍµ…±°ûBKFBûFBÃF<ƒBÇF,ƒBÿBûBÓFBËB×FBÛBÓBÃBïBÀƒBãB÷FB×FB×F¸ğ½Íµ…±°øğ½‘¥Øøğ½‘¥Øøñ‘¥Ø±…ÍÌô‰Ñ•…Í•Èˆøñ‘¥Ø±…ÍÌô‰¥¼ˆûŠr ğ½‘¥Øøñ‘¥ØøñÍÑÉ½¹œûBkBÃBèƒB÷BÃFBÃFF0ƒBÿB×FB×BÿBãFBëFğ½ÍÑÉ½¹œøñÍµ…±°ûBB×FFBûB÷BÃBïF3B÷F/BäƒFFBÃFFƒBÇB×BÜƒBÇBÃB÷BÃBïF3B÷BûBÏBøƒ
¯BÿFBãBËB×F°ƒBëBÃBèƒBÓB×BïBÀÿ
ì¸ğ½Íµ…±°øğ½‘¥Øøğ½‘¥Øøñ‘¥Ø±…ÍÌô‰Ñ•…Í•Èˆøñ‘¥Ø±…ÍÌô‰¥¼ˆûÂ~‚€ğ½‘¥Øøñ‘¥ØøñÍÑÉ½¹œûBŸFBøƒBËBÃBÛB÷BøƒB÷BÔƒBãFBÿBûFFBãFF0ƒBÈƒB÷BÃFBÃBïBÔğ½ÍÑÉ½¹œøñÍµ…±°ûBBûBÓFBëBÃBßBëBàƒB÷BÀƒBûFB÷BûBËBÔƒBËBÃF#B×BÏBøƒFBûBËBÿBÃBÓB×B÷BãF<¸ğ½Íµ…±°øğ½‘¥Øøğ½‘¥Øøñ„±…ÍÌô‰í±Íôˆ¡É•˜ô‰íÁ…åôˆûÂ~JXƒB{FBëFF/FF0ƒBßB÷BÃBëBûBóFFBËBøƒ
ÜíÁÉ¥•ôƒBŠ
ôğ½„øñ‘¥Ø±…ÍÌô‰¹½Ñ”ˆûBBïBÃFBãFƒFBûBïF3BëBøƒBãB÷BãFBãBÃFBûF ¸ƒBWFBïBàƒBËBßBÃBãBóB÷BûBÏBøƒBãB÷FB×FB×FBÀƒB÷BÔƒBÇFBÓB×F°ƒBëBûB÷FBÃBëFƒB÷BÔƒFBÃFBëFF/BËBÃB×FFF<¸ğ½‘¥Øøñ‘¥Ø±…ÍÌô‰ÑÉÕÍĞˆøñÍÁ…¸ûÂ~RHƒBßBÃF'BãF'FGB÷B÷BÃF<ƒFFF/BïBëBÀğ½ÍÁ…¸øñÍÁ…¸ûŠj„ƒBÇF/FFFF/BäƒBÿB×FB×FBûBĞğ½ÍÁ…¸øñÍÁ…¸ûÂ~JxƒFBûBïF3BëBøƒBÿFBàƒBËBßBÃBãBóB÷BûFFBàğ½ÍÁ…¸øğ½‘¥Øøğ½Í•Ñ¥½¸øœœœ±±½…‘•ÈõQÉÕ”¤()‘•˜É•¥ÍÑ•É}Á…¥É}İ•ˆ¡…ÁÀ±¹Ì¤è(€€€½¹”±ÁÉ½™¥±”±Í½É•}™¸±É•…Í½¹Í}™¸õ¹Íl½¹”t±¹ÍlÁÉ½™¥±”t±¹ÍlÍ½É”t±¹ÍlÉ•…Í½¹Ìt(€€€Í•ÑÑ¥¹œõ¹Ì¹•Ğ Í•ÑÑ¥¹œœ¤ìÍ•É•Ğõ¹Íl1M-}MIPtìé½‘¥…}™¸õ¹Ì¹•Ğ é½‘¥…Œœ¤ì±¥™•Á…Ñ¡}™¸õ¹Ì¹•Ğ ±¥™•Á…Ñ œ¤(€€€…ÁÀ¹•Ğ œ½Ìœ¤(€€€‘•˜¡½µ” ¤è(€€€€€€€ÑÉäè¸õ¥¹Ğ¡½¹” M1P=U9P ¨¤ŒI=4ÁÉ½™¥±•Ìœ¥lŒt¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸è¸ôÀ(€€€€€€€É•ÑÕÉ¸Á…” ŸB‡BûBËBÿBÃBïBàœ±˜œñÍ•Ñ¥½¸±…ÍÌô‰±…ÍÌ¡½µ”µ¡•É¼ˆøñ‘¥Ø±…ÍÌô‰­¥­•ÈˆûB‡BûBËBÿBÃBïBàƒ
ÜƒBËB×BÄ·BËB×FFBãF<ğ½‘¥Øøñ ÄûB_B÷BÃBëBûBóFFBËBøƒB÷BÃFBãB÷BÃB×FFF<ƒB÷BÔƒFBøƒFBËBÃBçBÿBÀ¸ğ½ Äøñ‘¥Ø±…ÍÌô‰ÍÕˆˆûBsF,ƒFBûBÇBãFBÃB×BğƒFBãBÏB÷BÃBïF,ƒFBûBËBóB×FFBãBóBûFFBàƒBÈƒBûBÓBãBôƒBÿBûB÷F?FB÷F/BäƒFFB×B÷BÃFBãBäèƒBëFBøƒBÿB×FB×BĞƒFBûBÇBûBä°ƒBÿBûFB×BóFƒBËF,ƒFBûBËBÿBÃBïBàƒBàƒBëBÃBèƒFBÓB×BïBÃFF0ƒBÿB×FBËF/BäƒF#BÃBÌƒBÇB×BÜƒB÷B×BïBûBËBëBûFFBà¸ğ½‘¥Øøñ‘¥Ø±…ÍÌô‰¡½µ”µÍÑ…ÑÌˆøñ‘¥Ø±…ÍÌô‰ÍÑ…ĞˆøñÍµ…±°ûBCB÷BëB×FƒBÈƒBÿBûBÓBÇBûFBÔğ½Íµ…±°øñˆùí¹ôğ½ˆøğ½‘¥Øøñ‘¥Ø±…ÍÌô‰ÍÑ…ĞˆøñÍµ…±°ûBOBïBÃBËB÷BÃF<ƒBóB×FFBãBëBÀğ½Íµ…±°øñˆûB‡BûBËBÿBÃBÓB×B÷BãBÔğ½ˆøğ½‘¥Øøğ½‘¥Øøñ„±…ÍÌô‰Ñ„ˆ¡É•˜ôˆ½Ì½‘•µ¼ˆûÂ~J\ƒBBûFBóBûFFB×FF0ƒBÛBãBËBûBÔƒBÓB×BóBøğ½„øğ½Í•Ñ¥½¸øœ¤(€€€…ÁÀ¹•Ğ œ½Ì½‘•µ¼œ¤(€€€‘•˜‘•µ¼ ¤è(€€€€€€€„õì¹…µ”œèŸB‹F,œ°‰¥ÉÑ¡}‘…Ñ”œèœÀÔ¸ÀÄ¸ÄääÀœ°¥ÑäœèŸBKBïBÃBÓBãBËBûFFBûBèœ°½…°œèŸBoF;BÇBûBËF0ƒBàƒFB×BóF3F<œ°ÁÉ¥½É¥ÑäœèŸB›B×B÷B÷BûFFBàô(€€€€€€€Œõì¹…µ”œèŸBCB÷B÷BÀœ°‰¥ÉÑ¡}‘…Ñ”œèœÄĞ¸ÀÔ¸ÄääÌœ°¥ÑäœèŸBKBïBÃBÓBãBËBûFFBûBèœ°½…°œèŸBoF;BÇBûBËF0ƒBàƒFB×BóF3F<œ°ÁÉ¥½É¥ÑäœèŸB›B×B÷B÷BûFFBàô(€€€€€€€ÁÉ¥”õ¥¹Ğ¡Í•ÑÑ¥¹œ Õ¹±½­}ÁÉ¥•}ÉÕˆœ°œÄÀÀœ¤½È€ÄÀÀ¤¥˜Í•ÑÑ¥¹œ•±Í”€ÄÀÀ(€€€€€€€É•ÑÕÉ¸É•¹‘•É}Á…¥È œœ±„±Œ°äÈ±lŸBKF,ƒFBûFBãFBÔƒBÿBûFBûBÛB×BÏBøƒFFB×B÷BÃFBãF<ƒBûFB÷BûF#B×B÷BãBäœ°ŸB‡BûBËBÿBÃBÓBÃB×FƒBÏBïBÃBËB÷F/BäƒBûFBãB×B÷FBãF ƒŠPƒBûBÇF'BãBÔƒFB×B÷B÷BûFFBàœ°ŸB{BÓBãBôƒBÏBûFBûBĞƒŠPƒBßB÷BÃBëBûBóFFBËBøƒFB×BÃBïF3B÷BøƒBÿFBûBÓBûBïBÛBãFF0ƒBûFBïBÃBçBôt±é½‘¥…}™¸±±¥™•Á…Ñ¡}™¸°œñˆûB‹B×BïB×F€¬ƒBßB×BóB÷BÃF<ƒFFBãFBãF<¸ğ½ˆøñ‰ÈûB‹B×BóBÿB×FBÃBóB×B÷FF,ƒBïB×BÏFBÔƒFFBãFF/BËBÃF;FƒFBÿBûBëBûBçFFBËBãBÔƒBàƒFFFBûBçFBãBËBûFFF0ƒBÓFFBÌƒBÓFFBÏBÀ¸œ°œñˆûBŸBãFBïBÀƒBÛBãBßB÷B×B÷B÷BûBÏBøƒBÿFFBàƒFBûFBóBãFFF;FƒFBûBËBóB×FFB÷F/BäƒFBãFBğ¸ğ½ˆøñ‰ÈûBHƒFB×BÃBïF3B÷BûBäƒBëBÃFFBûFBëBÔƒFBÃFFFGFƒFFFBûBãFFF<ƒBÿBøƒBËBÃF#BãBğƒBÓBÃFBÃBğƒFBûBÛBÓB×B÷BãF<¸œ±ÁÉ¥”±QÉÕ”¤(€€€…ÁÀ¹•Ğ œ½Ì½À¼ñÑ½­•¸øœ¤(€€€‘•˜Á…¥È¡Ñ½­•¸¤è(€€€€€€€Ø±¥õ}±½…¡Ñ½­•¸±Í•É•Ğ¤ì„±ˆõÁÉ½™¥±”¡Ø¤±ÁÉ½™¥±”¡¥¤(€€€€€€€¥˜¹½Ğ„½È¹½Ğˆè…‰½ÉĞ ĞÀĞ¤(€€€€€€€ÑÉäèÍØõ¥¹Ğ¡Í½É•}™¸¡„±ˆ¤¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸èÍØôÀ(€€€€€€€ÑÉäèÉÌõ±¥ÍĞ¡É•…Í½¹Í}™¸¡„±ˆ¤¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸èÉÌõmt(€€€€€€€…ÍÑÉ¼õ¹Õ´ôœœ(€€€€€€€ÑÉäè(€€€€€€€€€€€¥˜¹Ì¹•Ğ Á}…ÍÑÉ½}½Áäœ¤è…ÍÑÉ¼õ¹ÍlÁ}…ÍÑÉ½}½Áät¡„±ˆ¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸èÁ…ÍÌ(€€€€€€€ÑÉäè(€€€€€€€€€€€¥˜¹Ì¹•Ğ Á}¹Õµ}½Áäœ¤è¹Õ´õ¹ÍlÁ}¹Õµ}½Áät¡„±ˆ¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸èÁ…ÍÌ(€€€€€€€ÑÉäè(€€€€€€€€€€€¥˜¹Ì¹•Ğ …Õ‘¥Ğœ¤è¹Íl…Õ‘¥Ğt¡Ø°İ•‰}Á…¥É}Ù¥•Üœ±ì…¹‘¥‘…Ñ•}ÕÍ•É}¥œé¥°Í½É”œéÍÙô¤(€€€€€€€•á•ÁĞá•ÁÑ¥½¸èÁ…ÍÌ(€€€€€€€ÁÉ¥”õ¥¹Ğ¡Í•ÑÑ¥¹œ Õ¹±½­}ÁÉ¥•}ÉÕˆœ°œÄÀÀœ¤½È€ÄÀÀ¤¥˜Í•ÑÑ¥¹œ•±Í”€ÄÀÀ(€€€€€€€É•ÑÕÉ¸É•¹‘•É}Á…¥È¡Ñ½­•¸±„±ˆ±ÍØ±ÉÌ±é½‘¥…}™¸±±¥™•Á…Ñ¡}™¸±…ÍÑÉ¼±¹Õ´±ÁÉ¥”±…±Í”¤(€€€…ÁÀ¹•Ğ œ½Ì½Á…ä¼ñÑ½­•¸øœ¤(€€€‘•˜Á…ä¡Ñ½­•¸¤è(€€€€€€€Ø±¥õ}±½…¡Ñ½­•¸±Í•É•Ğ¤ì„±ˆõÁÉ½™¥±”¡Ø¤±ÁÉ½™¥±”¡¥¤(€€€€€€€¥˜¹½Ğ„½È¹½Ğˆè…‰½ÉĞ ĞÀĞ¤(€€€€€€€ÁÉ¥”õ¥¹Ğ¡Í•ÑÑ¥¹œ Õ¹±½­}ÁÉ¥•}ÉÕˆœ°œÄÀÀœ¤½È€ÄÀÀ¤¥˜Í•ÑÑ¥¹œ•±Í”€ÄÀÀ(€€€€€€€É•ÑÕÉ¸Á…” ŸB{BÿBïBÃFBÀƒ
ÜƒB‡BûBËBÿBÃBïBàœ±˜œñÍ•Ñ¥½¸±…ÍÌô‰±…ÍÌ¡•É¼ˆøñ‘¥Ø±…ÍÌô‰­¥­•ÈˆûB_B÷BÃBëBûBóFFBËBøƒFí}”¡‰l‰¹…µ”‰t¥ôğ½‘¥Øøñ‘¥Ø±…ÍÌô‰Ñ¥Ñ±”ˆùíÁÉ¥•ôƒŠ
ôğ½‘¥Øøñ‘¥Ø±…ÍÌô‰ÍÕˆˆûB_BÓB×FF0ƒBÇFBÓB×FƒBëBûFBûFBëBÃF<ƒBûBÿBïBÃFBÀƒFB×FB×BÜƒB‡BGB|¸ƒBBûFBïBÔƒBÿBûBÓFBËB×FBÛBÓB×B÷BãF<ƒBËFBûFBûBäƒFFBûFBûB÷BÔƒBûFBÿFBÃBËBãFFF<ƒBßBÃBÿFBûFƒB÷BÀƒBßB÷BÃBëBûBóFFBËBø¸ğ½‘¥Øøğ½Í•Ñ¥½¸øñÍ•Ñ¥½¸±…ÍÌô‰±…ÍÌ…Éˆøñ ÈûBkBÃBèƒBÿFBûBçBÓFGFƒBûBÿBïBÃFBÀğ½ Èøñ‘¥Ø±…ÍÌô‰É•…Í½¸ˆøñ‘¥Ø±…ÍÌô‰¡•¬ˆøÄğ½‘¥ØøñÀûBwBÃBÛBãBóBÃB×F#F0ƒB‡BGB|ƒBàƒBËF/BÇBãFBÃB×F#F0ƒFBËBûBäƒBÇBÃB÷Bè¸ğ½Àøğ½‘¥Øøñ‘¥Ø±…ÍÌô‰É•…Í½¸ˆøñ‘¥Ø±…ÍÌô‰¡•¬ˆøÈğ½‘¥ØøñÀûBBûBÓFBËB×FBÛBÓBÃB×F#F0ƒBÿBïBÃFFGBØƒBÈƒBÿFBãBïBûBÛB×B÷BãBàƒBÇBÃB÷BëBÀ¸ğ½Àøğ½‘¥Øøñ‘¥Ø±…ÍÌô‰É•…Í½¸ˆøñ‘¥Ø±…ÍÌô‰¡•¬ˆøÌğ½‘¥ØøñÀûBsF,ƒBûFBÿFBÃBËBïF?B×BğƒBßBÃBÿFBûFƒBËFBûFBûBäƒFFBûFBûB÷BÔ¸ğ½Àøğ½‘¥Øøñ‘¥Ø±…ÍÌô‰É•…Í½¸ˆøñ‘¥Ø±…ÍÌô‰¡•¬ˆøĞğ½‘¥ØøñÀûBBûFBïBÔƒBËBßBÃBãBóB÷BûBÏBøƒ
¯BÓBÃ
ìƒBûFBëFF/BËBÃB×FFF<ƒBëBûB÷FBÃBëFƒBàƒFFBÃFFƒBûBÇF'B×B÷BãF<¸ğ½Àøğ½‘¥Øøñ‘¥Ø±…ÍÌô‰Ñ„½™˜ˆûŠj„ƒB‡BGB|ƒBÿBûBÓBëBïF;FBÃB×Bğğ½‘¥Øøñ„±…ÍÌô‰Ñ„ˆÍÑå±”ô‰‰…­É½Õ¹é±¥¹•…ÈµÉ…‘¥•¹Ğ ÄÌÕ‘•œ°™™™™™˜Äà°™™™™™˜Á¤í‰½àµÍ¡…‘½Üé¹½¹”ˆ¡É•˜ôˆ½Ì½À½íÅÕ½Ñ”¡Ñ½­•¸¥ôˆûŠ@ƒBKB×FB÷FFF3FF<ƒBèƒBÿBÃFBÔğ½„øñ‘¥Ø±…ÍÌô‰¹½Ñ”ˆûB‡B×BçFBÃFƒF7FBøƒBÓB×BóBûB÷FFFBÃFBãBûB÷B÷F/BäƒF7BëFBÃBôƒŠPƒBÓB×B÷F3BÏBàƒB÷BÔƒFBÿBãFF/BËBÃF;FFF<¸ğ½‘¥Øøğ½Í•Ñ¥½¸øœ¤(