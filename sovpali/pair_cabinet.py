"""Authenticated presentation of existing matching, profiles and purchases.
No delivery scheduler, payment processor or matching rule is implemented here.
"""
import os
import re
import secrets
from datetime import datetime
from urllib.parse import urlsplit
import requests
from flask import abort, request, make_response, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pair_miniapp import validate_init_data
from pair_web import pair_link

GOALS=('Серьёзные отношения','Любовь и семья','Общение и знакомство','Пока присматриваюсь')
PRIORITIES=('Семья','Любовь','Ценности','Страсть','Опора')

def val(row,key,default=None):
    try: return row[key] if row[key] is not None else default
    except (TypeError,KeyError,IndexError): return default

def history_ids(ns,uid):
    # Only the recipient's existing deliveries/views and their own requests.
    # Never turn an outbound recommendation into an incoming one for its subject.
    rows=ns['many']('''SELECT candidate_user_id AS cid, sent_at AS at FROM match_pushes
        WHERE recipient_user_id=? AND status='sent'
        UNION ALL SELECT candidate_user_id AS cid, viewed_at AS at FROM match_push_views WHERE viewer_user_id=?
        UNION ALL SELECT target_user_id AS cid, created_at AS at FROM communication_requests WHERE requester_user_id=?
        UNION ALL SELECT subject_user_id AS cid, offered_at AS at FROM match_offers
          WHERE recipient_user_id=? AND status NOT IN ('send_failed','reserved')
        ORDER BY at DESC LIMIT 40''',(uid,uid,uid,uid))
    return list(dict.fromkeys(int(r['cid']) for r in rows))

def can_open(ns,uid,cid):
    if uid==cid:return False
    account=ns['user'](cid)
    a,b=ns['profile'](uid),ns['profile'](cid)
    if not account or val(account,'is_banned',0) or not a or not b or not ns['eligible'](a,b):return False
    engine=ns.get('MATCH_PUSH_ENGINE')
    if engine:
        owner=engine.pair_owner(uid,cid)
        if owner is not None and int(owner)!=uid:return False
    return True

def enrich_pair(data,ns,uid,cid):
    data=dict(data)
    data['candidate_id']=cid
    data['pair_key']=str(uid)+':'+str(cid)
    data['contact_url']=None
    data['price']=100
    token=pair_link('https://local',uid,cid,ns['FLASK_SECRET']).rsplit('/',1)[1]
    data['premium_path']='/s/app/api/checkout/premium' if ns.get('web_premium_live',lambda:False)() else None
    data['premium_active']=bool(ns.get('web_premium_active',lambda _:False)(uid))
    existing=ns['cr_between'](uid,cid)
    # Same initiator-only handoff as the bot. Target never receives the contact.
    accepted=bool(existing and val(existing,'status')=='accepted' and int(val(existing,'requester_user_id',0))==uid)
    legacy=ns['one']("SELECT status FROM match_offers WHERE recipient_user_id=? AND subject_user_id=?",(uid,cid))
    if legacy and val(legacy,'status')=='accepted':accepted=True
    if accepted:
        data['request_status']='accepted'
        data['contact_url']=ns.get('ar_contact_url',lambda _:None)(cid)
    elif existing and val(existing,'status')=='accepted':
        data['request_status']='accepted_target'
    # Confirmed bank status only. Do not reconcile, create or retry a payment.
    order=ns['one']('''SELECT o.status,b.binding_status FROM web_purchase_bindings b
        JOIN billing_web_orders o ON o.order_id=b.billing_order_id
        WHERE b.buyer_user_id=? AND b.target_user_id=? AND b.sku='contact'
        AND o.status='paid' ORDER BY o.created_at DESC LIMIT 1''',(uid,cid))
    if data['request_status']=='ready' and order and val(order,'binding_status') in ('reserved','sending','retry'):
        data['request_status']='processing'
    return data

def register_cabinet(app,ns,render):
    from pair_motion import _response_headers, _data_for_pair, _age
    serial=URLSafeTimedSerializer(ns['FLASK_SECRET'],salt='sovpali-cabinet-photo-v1')
    def respond(data,status=200):return _response_headers(make_response(data,status))
    def auth():
        if (request.content_length or 0)>20000:abort(413)
        origin=request.headers.get('Origin')
        if origin and urlsplit(origin).netloc!=urlsplit(request.host_url).netloc:abort(403)
        try:tid=validate_init_data(request.headers.get('X-Telegram-Init-Data',''),ns.get('TOKEN') or os.getenv('BOT_TOKEN',''))
        except (ValueError,TypeError,KeyError):abort(401,description='Открой приложение заново из бота «Совпали».')
        u=ns['one']('SELECT * FROM users WHERE tg_id=?',(tid,))
        if not u:abort(respond({'message':'Сначала открой бот «Совпали» и нажми /start.'},403))
        if val(u,'is_banned',0):abort(respond({'message':'Профиль временно недоступен.'},403))
        return u,int(u['id'])
    def bot_url():
        name=ns.get('MINIAPP_BOT_USERNAME','')
        return 'https://t.me/'+name if re.fullmatch(r'[A-Za-z0-9_]+',name or '') else None
    def profile_data(u,uid):
        p=ns['profile'](uid)
        if not p:return None
        result={k:val(p,k,'') for k in ('name','gender','birth_date','birth_place','city','goal','priority')}
        result.update(age=_age(val(p,'birth_date')),username=val(u,'username',''),photo=None)
        if val(p,'photo_file_id'):result['photo']='/s/app/photo/'+serial.dumps({'uid':uid,'rev':secrets.token_hex(4)})
        return result
    def compact(uid,cid,new=False):
        if not can_open(ns,uid,cid):return None
        a,b=ns['profile'](uid),ns['profile'](cid)
        token=pair_link('https://local',uid,cid,ns['FLASK_SECRET']).rsplit('/',1)[1]
        existing=ns['cr_between'](uid,cid)
        status='ready'
        if existing:
            stage=val(existing,'status')
            if stage=='accepted':status='accepted' if int(val(existing,'requester_user_id',0))==uid else 'accepted_target'
            elif stage=='pending':status='pending' if int(val(existing,'requester_user_id',0))==uid else 'incoming'
        legacy=ns['one']("SELECT status FROM match_offers WHERE recipient_user_id=? AND subject_user_id=?",(uid,cid))
        if legacy and val(legacy,'status')=='accepted':status='accepted'
        person={k:val(b,k,'') for k in ('name','city','goal','priority')}
        person.update(age=_age(val(b,'birth_date')),photo='/s/m/photo/'+token+'/candidate' if val(b,'photo_file_id') else None)
        reasons=ns['reasons'](a,b)
        return {'id':cid,'person':person,'score':int(ns['score'](a,b)),
                'reason':str(reasons[0]).capitalize() if reasons else 'Откройте разбор вашей пары.',
                'status':status,'new':new,'token':token}


    @app.get('/s/app')
    def cabinet_shell():return render({'cabinet_auth_path':'/s/app/api/cabinet'})

    @app.post('/s/app/api/cabinet')
    def cabinet_data():
        u,uid=auth()
        profile=profile_data(u,uid)
        suggestions=[];history=[]
        if profile:
            # Use the exact existing Top-3 selector, including directional exclusion.
            for _,p in ns['mp_candidates'](uid,3):
                row=compact(uid,int(p['user_id']),True)
                if row:suggestions.append(row)
            for cid in history_ids(ns,uid):
                row=compact(uid,cid)
                if row:history.append(row)
        from web_product_access import premium_expires
        expiry=premium_expires(ns['db'],uid)
        purchases=ns['many']('''SELECT b.sku,o.amount_kopecks,o.status,o.created_at
             FROM web_purchase_bindings b JOIN billing_web_orders o ON o.order_id=b.billing_order_id
             WHERE b.buyer_user_id=? ORDER BY o.created_at DESC LIMIT 30''',(uid,))
        credits=ns['one']('SELECT COUNT(*) AS n FROM web_intro_credits WHERE buyer_user_id=? AND redeemed_for_order IS NULL',(uid,))
        support=str(ns.get('setting',lambda _: '')('support_username') or '').strip().lstrip('@')
        token=(suggestions+history)[0]['token'] if suggestions or history else None
        return respond({'profile':profile,'suggestions':suggestions,'history':history,
          'purchases':[dict(x) for x in purchases], 'premium_active':bool(ns['web_premium_active'](uid)),
          'premium_until':expiry,'credits':int(val(credits,'n',0)),
          'premium_path':'/s/app/api/checkout/premium' if ns.get('web_premium_live',lambda:False)() else None,
          'bot_url':bot_url(),'support_url':'https://t.me/'+support if re.fullmatch(r'[A-Za-z0-9_]{5,32}',support) else None,
          'goals':list(GOALS),'priorities':list(PRIORITIES)})

    @app.post('/s/app/api/pair')
    def cabinet_pair():
        u,uid=auth();body=request.get_json(silent=True)
        try:
            if not isinstance(body,dict) or type(body.get('candidate_id')) is not int:raise ValueError()
            cid=body['candidate_id']
        except (TypeError,ValueError):abort(400)
        ids={int(p['user_id']) for _,p in ns['mp_candidates'](uid,3)}|set(history_ids(ns,uid))
        if cid not in ids or not can_open(ns,uid,cid):abort(404)
        token=pair_link('https://local',uid,cid,ns['FLASK_SECRET']).rsplit('/',1)[1]
        data=enrich_pair(_data_for_pair(ns['profile'](uid),ns['profile'](cid),token,ns),ns,uid,cid)
        ns.get('mp_record_view',lambda *a:None)(uid,cid)
        ns.get('audit',lambda *a:None)(uid,'motion_pair_view',{'candidate_user_id':cid})
        return respond(data)

    @app.post('/s/app/api/profile')
    def cabinet_profile():
        u,uid=auth();old=ns['profile'](uid);body=request.get_json(silent=True)
        if not old:abort(409,description='Сначала заполни анкету в боте.')
        allowed={'name','birth_date','birth_place','city','goal','priority'}
        if not isinstance(body,dict) or set(body)!=allowed:abort(400)
        if any(not isinstance(v,str) or not v.strip() or len(v)>90 for v in body.values()):abort(400)
        body={k:v.strip() for k,v in body.items()}
        try:
            dt=datetime.strptime(body['birth_date'],'%d.%m.%Y')
            age=_age(body['birth_date'])
            if age is None or age<18 or age>120:raise ValueError()
        except ValueError:return respond({'message':'Укажи корректную дату рождения. Сервис доступен с 18 лет.'},400)
        if body['goal'] not in GOALS or body['priority'] not in PRIORITIES:abort(400)
        # Existing save_profile also preserves the existing city normalization.
        updated=dict(old);updated.update(body);updated['photo']=val(old,'photo_file_id')
        ns['save_profile'](uid,updated)
        ns.get('audit',lambda *a:None)(uid,'miniapp_profile_saved',{'fields':sorted(allowed)})
        return respond({'profile':profile_data(u,uid)})

    @app.get('/s/app/photo/<token>')
    def cabinet_photo(token):
        try:uid=int(serial.loads(token,max_age=3600)['uid'])
        except (BadSignature,SignatureExpired,KeyError,ValueError,TypeError):abort(404)
        u=ns['user'](uid);p=ns['profile'](uid)
        if not u or val(u,'is_banned',0) or not val(p,'photo_file_id'):abort(404)
        if val(p,'photo_file_id')=='local:portrait-v1':
            from photo_media import get_local
            photo=get_local(ns['db'],uid)
            if not photo:abort(404)
            body,mime=photo
            return _response_headers(Response(body,mimetype=mime))
        bot=ns.get('TOKEN') or os.getenv('BOT_TOKEN','')
        try:
            info=requests.get('https://api.telegram.org/bot'+bot+'/getFile',params={'file_id':p['photo_file_id']},timeout=7)
            info.raise_for_status();path=info.json().get('result',{}).get('file_path','')
            if not path or path.startswith('/') or '..' in path:abort(404)
            image=requests.get('https://api.telegram.org/file/bot'+bot+'/'+path,timeout=12);image.raise_for_status()
            if len(image.content)>8*1024*1024:abort(413)
            return _response_headers(Response(image.content,mimetype='image/png' if image.content.startswith(b'\x89PNG') else 'image/jpeg'))
        except requests.RequestException:abort(502)
