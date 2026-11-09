"""Additive admin console. Existing payment tables are SELECT-only.

Each deployment owns its data and Telegram token. The main console proxies the
second project's admin API with a separate server-only secret.
"""
import os, time, secrets, hmac, threading, uuid, re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import requests
from flask import request, session, redirect, jsonify, render_template, abort

PROJECTS = {'sovpali': 'Совпали', 'poehali': 'Поехали'}
STAGES = {
    'welcome':'Получил приветствие в боте',
    'landing':'Открыл бесплатную схему',
    'checkout_view':'Открыл страницу оплаты',
    'checkout_started':'Начал оплату — ждём подтверждения',
    'paid':'Оплата подтверждена',
    'subscribed':'Подписался на сообщения',
    'stopped':'Отказался от рассылки',
}
def stage_label(value):
    value=str(value or '').strip()
    return STAGES.get(value, value if re.search('[А-Яа-яЁё]',value) else 'Этап пока не определён')

SEGMENTS = {'all': 'Все доступные', 'unpaid': 'Без оплаты', 'checkout': 'Дошли до оплаты', 'paid': 'Оплатили'}

def register(app, connect, project, console=False):
    @contextmanager
    def connection():
        c = connect()
        try:
            # Admin queries must never hold database locks indefinitely.
            with c.cursor() as limits:
                limits.execute("SET LOCAL statement_timeout = 8000")
                limits.execute("SET LOCAL lock_timeout = 2000")
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    read_context = threading.local()
    def query(sql, args=()):
        def execute(c):
            with c.cursor() as cur:
                cur.execute(sql, args)
                if not cur.description:
                    return []
                names = [d[0] for d in cur.description]
                return [dict(r) if isinstance(r, dict) else dict(zip(names, r)) for r in cur.fetchall()]
        active = getattr(read_context, 'connection', None)
        if active is not None:
            return execute(active)
        with connection() as c:
            return execute(c)

    def cte():
        if project == 'poehali':
            return """WITH orders AS (
              SELECT id::text oid, funnel_ref owner, amount/100.0 amount, state status, created_at, paid_at
              FROM poehali_orders), people AS (
              SELECT l.chat_id::text uid, l.chat_id, COALESCE(NULLIF(i.first_name,''),NULLIF(i.username,''),'Имя пока не получено') name,
              i.username,COALESCE(i.loaded,FALSE) identity_loaded,
              CASE WHEN l.stage='welcome' AND l.step>0 THEN 'Получил сообщение '||l.step::text||' из 4'
                   WHEN l.stage='welcome' AND l.opted_in THEN 'Подписался на сообщения'
                   ELSE l.stage END stage,
              l.first_seen created_at, l.updated_at last_seen,
              (l.opted_in AND NOT l.stopped) eligible,
              EXISTS(SELECT 1 FROM orders o WHERE o.owner=l.ref AND o.status='paid') paid,
              EXISTS(SELECT 1 FROM orders o WHERE o.owner=l.ref) checkout,
              CASE WHEN EXISTS(SELECT 1 FROM orders o WHERE o.owner=l.ref AND o.status='paid') THEN 4
               WHEN EXISTS(SELECT 1 FROM orders o WHERE o.owner=l.ref) OR l.stage IN ('checkout_view','checkout_started') THEN 3
               WHEN l.stage='landing' OR EXISTS(SELECT 1 FROM funnel_events e WHERE e.chat_id=l.chat_id AND e.product=l.product AND e.kind='landing') THEN 2
               WHEN l.opted_in THEN 1 ELSE 0 END rank
              FROM funnel_leads l LEFT JOIN project_admin_identities i ON i.chat_id=l.chat_id AND i.project='poehali' WHERE l.product='poehali') """
        return """WITH orders AS (
          SELECT o.order_id oid,b.buyer_user_id::text owner,o.amount_kopecks/100.0 amount,
          o.status,o.created_at::timestamptz created_at,NULLIF(o.paid_at,'')::timestamptz paid_at
          FROM billing_web_orders o LEFT JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id),
          people AS (
          SELECT u.id::text uid,u.tg_id chat_id,COALESCE(NULLIF(u.first_name,''),u.username,'Имя не указано') name,u.username,TRUE identity_loaded,
          COALESCE(f.current_step,'Старт') stage,u.created_at::timestamptz created_at,
          NULLIF(u.last_seen_at,'')::timestamptz last_seen,(COALESCE(u.is_banned,0)=0 AND NOT EXISTS(SELECT 1 FROM lifecycle_prefs lp WHERE lp.user_id=u.id AND lp.promo_enabled=0)) eligible,
          EXISTS(SELECT 1 FROM orders o WHERE o.owner=u.id::text AND o.status='paid') paid,
          EXISTS(SELECT 1 FROM orders o WHERE o.owner=u.id::text) checkout,
          CASE WHEN EXISTS(SELECT 1 FROM orders o WHERE o.owner=u.id::text AND o.status='paid') THEN 4
           WHEN EXISTS(SELECT 1 FROM orders o WHERE o.owner=u.id::text) THEN 3
           WHEN COALESCE(f.max_rank,0)>=10 THEN 2
           WHEN p.completed_at IS NOT NULL THEN 1 ELSE 0 END rank
          FROM users u LEFT JOIN profiles p ON p.user_id=u.id LEFT JOIN funnel_state f ON f.user_id=u.id) """

    def filters(data):
        segment = data.get('segment', 'all')
        if segment not in SEGMENTS:
            abort(400)
        try:
            days = int(data.get('days', 30))
        except (TypeError, ValueError):
            abort(400)
        if days not in (0,7,30,90):
            abort(400)
        since = datetime(2000,1,1,tzinfo=timezone.utc) if days == 0 else datetime.now(timezone.utc)-timedelta(days=days)
        condition = {'all':'TRUE','unpaid':'NOT paid','paid':'paid','checkout':'checkout AND NOT paid'}[segment]
        return since, condition

    def _stats(data):
        since, cond = filters(data)
        base = cte()
        summary = query(base+"""SELECT COUNT(*) total,COUNT(*) FILTER(WHERE paid) paid,
          COUNT(*) FILTER(WHERE checkout AND NOT paid) abandoned,
          COUNT(*) FILTER(WHERE eligible) available,
          COUNT(*) FILTER(WHERE rank>=1) r1,COUNT(*) FILTER(WHERE rank>=2) r2,
          COUNT(*) FILTER(WHERE rank>=3) r3,COUNT(*) FILTER(WHERE rank>=4) r4
          FROM people WHERE created_at>=%s""", (since,))[0]
        money = query(base+"""SELECT COALESCE(SUM(amount) FILTER(WHERE status='paid'),0) revenue,
          COUNT(*) FILTER(WHERE status='paid') paid_orders,
          COUNT(*) FILTER(WHERE status!='paid') unpaid_orders
          FROM orders WHERE created_at>=%s""",(since,))[0]
        try:
            page = max(1, min(100000,int(data.get('page',1))))
        except (ValueError,TypeError):
            abort(400)
        search = str(data.get('search',''))[:100]
        where = "created_at>=%s AND "+cond+" AND (name ILIKE %s OR COALESCE(username,'') ILIKE %s OR chat_id::text LIKE %s)"
        args = (since,'%'+search+'%','%'+search.lstrip('@')+'%','%'+search+'%')
        people = query(base+'SELECT * FROM people WHERE '+where+' ORDER BY created_at DESC,uid LIMIT 50 OFFSET %s',args+((page-1)*50,))
        total = query(base+'SELECT COUNT(*) n FROM people WHERE '+where,args)[0]['n']
        series = query(base+"SELECT created_at::date::text AS day,COUNT(*) n FROM people WHERE created_at>=%s GROUP BY 1 ORDER BY 1",(since,))
        stages = query(base+"SELECT stage,COUNT(*) n FROM people WHERE created_at>=%s GROUP BY stage ORDER BY n DESC",(since,))
        for person in people:
            person['stage']=stage_label(person['stage'])
        grouped={}
        for row in stages:
            label=stage_label(row['stage'])
            grouped[label]=grouped.get(label,0)+row['n']
        stages=[{'stage':label,'n':count} for label,count in grouped.items()]
        return dict(summary=summary,money=money,people=people,total=total,page=page,series=series,stages=stages,
                    project=project,labels=['Запустили бота','Анкета готова' if project=='sovpali' else 'Подписались',
                    'Открыли подбор' if project=='sovpali' else 'Открыли схему','Начали оплату','Оплатили'])

    def stats(data):
        filters(data)
        schema()
        # One connection for a whole snapshot; payment records are read-only.
        with connection() as c:
            with c.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
            read_context.connection = c
            try:
                return _stats(data)
            finally:
                del read_context.connection

    def insights(data):
        if project != 'sovpali':
            abort(404)
        since, _ = filters(data)
        import admin_insights
        # Analytics stays read-only and isolated from Ozon/matching services.
        with connection() as c:
            with c.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
            read_context.connection = c
            try:
                return admin_insights.snapshot(query, since, data)
            finally:
                del read_context.connection

    def affiliate_ledger():
        if project != 'sovpali':
            abort(404)
        import admin_insights
        with connection() as c:
            with c.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
            read_context.connection = c
            try:
                return admin_insights.ledger(query)
            finally:
                del read_context.connection

    def verify_insights():
        if project != 'sovpali':
            return
        try:
            overview = insights({'days':30,'insights_page':1})
            print('[admin] Insights verified: users=%s deliveries=%s orders=%s' %
                  (overview['users']['total'],
                   overview['deliveries']['delivered'],
                   overview['payments']['orders']), flush=True)
        except Exception as exc:
            app.logger.warning('Admin insights unavailable: %s: %s',
                               type(exc).__name__, str(exc)[:240])

    def verify_stats():
        try:
            snapshot=stats({'days':30})
            print('[admin] Statistics ready: project=%s users=%s' % (project,snapshot['summary']['total']),flush=True)
        except Exception as err:
            print('[admin] Statistics verification failed: project=%s error=%s' % (project,type(err).__name__),flush=True)

    schema_ready = threading.Event()
    schema_lock = threading.Lock()
    def schema():
        if schema_ready.is_set(): return
        with schema_lock:
            if schema_ready.is_set(): return
            query('''CREATE TABLE IF NOT EXISTS project_admin_campaigns (
              id TEXT PRIMARY KEY,project TEXT NOT NULL,body TEXT NOT NULL,segment TEXT NOT NULL,
              created_at TIMESTAMPTZ DEFAULT now(),cancelled BOOLEAN DEFAULT FALSE)''')
            query('''CREATE TABLE IF NOT EXISTS project_admin_deliveries (
              campaign TEXT REFERENCES project_admin_campaigns(id),chat_id BIGINT,
              state TEXT NOT NULL DEFAULT 'queued',updated_at TIMESTAMPTZ DEFAULT now(),
              next_at TIMESTAMPTZ DEFAULT now(),detail TEXT,PRIMARY KEY(campaign,chat_id))''')
            query('''CREATE TABLE IF NOT EXISTS project_admin_identities (
              project TEXT NOT NULL,chat_id BIGINT NOT NULL,username TEXT,first_name TEXT,
              loaded BOOLEAN DEFAULT FALSE,checked_at TIMESTAMPTZ DEFAULT now(),
              PRIMARY KEY(project,chat_id))''')
            schema_ready.set()

    def audience(data):
        since, cond = filters(data)
        schema()
        return query(cte()+'SELECT DISTINCT chat_id FROM people WHERE eligible AND created_at>=%s AND '+cond,(since,))

    def campaign(data):
        schema()
        body=str(data.get('body','')).strip()
        key=str(data.get('id',''))
        try: uuid.UUID(key)
        except (ValueError,TypeError): abort(400)
        if not body or len(body.encode('utf-16-le'))//2>4096: abort(400)
        recipients=audience(data)
        if len(recipients)>100000: abort(400)
        with connection() as c:
            with c.cursor() as cur:
                cur.execute('INSERT INTO project_admin_campaigns(id,project,body,segment) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id',(key,project,body,data.get('segment','all')))
                if cur.fetchone():
                    cur.executemany('INSERT INTO project_admin_deliveries(campaign,chat_id) VALUES(%s,%s)',[(key,r['chat_id']) for r in recipients])
        return {'id':key}

    def history():
        schema()
        return query('''SELECT c.id,c.body,c.segment,c.created_at,c.cancelled,
          COUNT(d.chat_id) total,COUNT(*) FILTER(WHERE d.state='sent') sent,
          COUNT(*) FILTER(WHERE d.state='queued') queued,
          COUNT(*) FILTER(WHERE d.state='failed') failed,
          COUNT(*) FILTER(WHERE d.state='skipped') skipped,
          COUNT(*) FILTER(WHERE d.state IN ('sending','unknown')) uncertain
          FROM project_admin_campaigns c LEFT JOIN project_admin_deliveries d ON d.campaign=c.id
          WHERE c.project=%s GROUP BY c.id ORDER BY c.created_at DESC LIMIT 20''',(project,))

    def refresh_identity():
        """Read Telegram profiles for existing leads; never send a message."""
        if project != 'poehali': return
        schema()
        rows=query("""SELECT l.chat_id FROM funnel_leads l
          LEFT JOIN project_admin_identities i ON i.chat_id=l.chat_id AND i.project=%s
          WHERE l.product=%s AND (i.checked_at IS NULL OR
          i.checked_at<now()-CASE WHEN i.loaded THEN interval '1 day' ELSE interval '1 hour' END)
          ORDER BY i.checked_at NULLS FIRST LIMIT 1""",(project,project))
        if not rows: return
        chat_id=rows[0]['chat_id']
        token=os.getenv('TG_FUNNEL_BOT_TOKEN','')
        if not token: return
        result={}
        try:
            response=requests.post('https://api.telegram.org/bot'+token+'/getChat',
                json={'chat_id':chat_id},timeout=5)
            payload=response.json()
            if payload.get('ok') and payload.get('result',{}).get('id')==chat_id:
                result=payload['result']
        except Exception: pass
        query("""INSERT INTO project_admin_identities(project,chat_id,username,first_name,loaded)
          VALUES(%s,%s,%s,%s,%s) ON CONFLICT(project,chat_id) DO UPDATE SET
          username=CASE WHEN excluded.loaded THEN excluded.username ELSE project_admin_identities.username END,
          first_name=CASE WHEN excluded.loaded THEN excluded.first_name ELSE project_admin_identities.first_name END,
          loaded=project_admin_identities.loaded OR excluded.loaded,checked_at=now()""",
          (project,chat_id,result.get('username'),result.get('first_name'),bool(result)))
        print('[admin] Telegram profile refreshed: loaded=%s username_present=%s' % (bool(result),bool(result.get('username'))),flush=True)

    def identity_worker():
        while True:
            try: refresh_identity()
            except Exception: app.logger.warning('Admin Telegram profile refresh unavailable')
            time.sleep(10)

    def worker():
        while True:
            try:
                schema()
                # A crash/timeout cannot safely be retried: Telegram has no idempotency key.
                query("UPDATE project_admin_deliveries d SET state='unknown' FROM project_admin_campaigns c WHERE d.campaign=c.id AND c.project=%s AND d.state='sending' AND d.updated_at<now()-interval '5 minutes'",(project,))
                rows=query('''WITH picked AS (SELECT d.campaign,d.chat_id FROM project_admin_deliveries d
                  JOIN project_admin_campaigns c ON c.id=d.campaign
                  WHERE c.project=%s AND NOT c.cancelled AND d.state='queued' AND d.next_at<=now()
                  ORDER BY c.created_at FOR UPDATE OF d SKIP LOCKED LIMIT 1)
                  UPDATE project_admin_deliveries d SET state='sending',updated_at=now()
                  FROM picked p WHERE d.campaign=p.campaign AND d.chat_id=p.chat_id
                  RETURNING d.campaign,d.chat_id''',(project,))
                if not rows:
                    time.sleep(3); continue
                r=rows[0]
                eligible=query(cte()+'SELECT 1 FROM people WHERE chat_id=%s AND eligible',(r['chat_id'],))
                c=query('SELECT body,cancelled FROM project_admin_campaigns WHERE id=%s',(r['campaign'],))[0]
                state,detail,delay='skipped','',0
                if eligible and not c['cancelled']:
                    token=os.getenv('BOT_TOKEN' if project=='sovpali' else 'TG_FUNNEL_BOT_TOKEN','')
                    if not token:
                        state,detail='failed','Токен бота не настроен'
                    else:
                        try:
                            response=requests.post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':r['chat_id'],'text':c['body'], 'reply_markup':{'inline_keyboard':[[{'text':'Отключить рассылку','callback_data':'lf:optout' if project=='sovpali' else 'off:poehali'}]]}},timeout=20)
                            result=response.json()
                            if result.get('ok'): state='sent'
                            elif result.get('error_code')==429:
                                state='queued'; delay=max(1,min(3600,int(result.get('parameters',{}).get('retry_after',30))))
                            elif response.status_code>=500: state='unknown'
                            else: state='failed'; detail='Telegram: '+str(result.get('error_code','error'))
                        except Exception: state='unknown'; detail='Результат отправки не подтверждён'
                query("UPDATE project_admin_deliveries SET state=%s,detail=%s,updated_at=now(),next_at=now()+(%s * interval '1 second') WHERE campaign=%s AND chat_id=%s",(state,detail,delay,r['campaign'],r['chat_id']))
                time.sleep(.12)
            except Exception:
                app.logger.warning('Admin delivery worker unavailable (%s)',project)
                time.sleep(15)

    worker_started = threading.Event()
    worker_lock = threading.Lock()
    def start_worker():
        if worker_started.is_set(): return
        with worker_lock:
            if not worker_started.is_set():
                worker_started.set()
                threading.Thread(target=worker,daemon=True,name='admin-delivery-'+project).start()
                if project=='poehali':
                    threading.Thread(target=identity_worker,daemon=True,name='admin-identities').start()

    def run(action,data):
        start_worker()
        if action=='stats': return stats(data)
        if action=='insights': return insights(data)
        if action=='ledger': return affiliate_ledger()
        if action=='preview': return {'count':len(audience(data))}
        if action=='send': return campaign(data)
        if action=='history': return {'campaigns':history()}
        if action=='cancel':
            schema()
            query('UPDATE project_admin_campaigns SET cancelled=TRUE WHERE id=%s AND project=%s',(str(data.get('id','')),project))
            return {'ok':True}
        abort(404)

    @app.post('/internal/project-admin/<action>')
    def project_admin_internal(action):
        secret=os.getenv('PROJECT_ADMIN_SECRET','')
        if not secret or not hmac.compare_digest(request.headers.get('X-Project-Admin',''),secret): abort(403)
        try: return jsonify(run(action,request.get_json(silent=True) or {}))
        except Exception as err:
            from werkzeug.exceptions import HTTPException
            if isinstance(err,HTTPException): raise
            app.logger.warning('Project admin API unavailable (%s)',project)
            return jsonify(error='Не удалось получить данные проекта'),503

    @app.after_request
    def project_admin_no_cache(response):
        if request.path.startswith(('/admin/projects','/internal/project-admin')):
            response.headers['Cache-Control']='no-store'
        return response

    if console:
        @app.get('/admin/projects')
        def project_admin_page():
            if not session.get('a'): return redirect('/admin/login')
            session.setdefault('project_admin_csrf',secrets.token_urlsafe(32))
            return render_template('project_admin.html',csrf=session['project_admin_csrf'])

        @app.post('/admin/projects/api/<selected>/<action>')
        def project_admin_api(selected,action):
            if not session.get('a'): abort(401)
            if not session.get('project_admin_csrf') or not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['project_admin_csrf']): abort(403)
            if selected not in PROJECTS: abort(404)
            data=request.get_json(silent=True) or {}
            try:
                if selected==project: return jsonify(run(action,data))
                secret=os.getenv('PROJECT_ADMIN_SECRET','')
                if not secret: return jsonify(error='Подключение «Поехали» ещё не настроено'),503
                res=requests.post('https://poehali-checkout.onrender.com/internal/project-admin/'+action,
                    headers={'X-Project-Admin':secret},json=data,timeout=25)
                if res.status_code!=200: return jsonify(error='Проект временно недоступен'),503
                return jsonify(res.json())
            except Exception as err:
                from werkzeug.exceptions import HTTPException
                if isinstance(err,HTTPException): raise
                app.logger.warning('Admin query unavailable (%s)',selected)
                return jsonify(error='Не удалось загрузить данные. Повторите запрос.'),503

        @app.before_request
        def project_admin_home():
            if request.path=='/admin' and request.method=='GET' and session.get('a'):
                return redirect('/admin/projects')

    # Resume pending jobs after deployment; no recipients exist until an admin sends.
    start_worker()
    threading.Thread(target=verify_stats,daemon=True,name='admin-statistics-check').start()
    threading.Thread(target=verify_insights,daemon=True,name='admin-insights-check').start()
