from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps

import psycopg
import requests
from flask import Flask, flash, jsonify, redirect, render_template_string, request, session, url_for
from psycopg.rows import dict_row
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from waitress import serve

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(name)s | %(message)s')
log = logging.getLogger('sovpali')

TOKEN = os.environ['BOT_TOKEN'].strip()
DATABASE_URL = os.environ['DATABASE_URL'].strip()
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', '').strip().rstrip('/')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '').strip()
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ['ADMIN_PASSWORD']
FLASK_SECRET = os.environ['FLASK_SECRET']
PORT = int(os.getenv('PORT', '10000'))

app = Flask(__name__)
app.secret_key = FLASK_SECRET

def now(): return datetime.now(timezone.utc)

@contextmanager
def db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn; conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def one(sql, params=()):
    with db() as c, c.cursor() as cur: cur.execute(sql, params); return cur.fetchone()
def many(sql, params=()):
    with db() as c, c.cursor() as cur: cur.execute(sql, params); return cur.fetchall()
def execute(sql, params=()):
    with db() as c, c.cursor() as cur: cur.execute(sql, params)

def init_db():
    statements=[
        '''CREATE TABLE IF NOT EXISTS users (id BIGSERIAL PRIMARY KEY,tg_id BIGINT UNIQUE NOT NULL,username TEXT,first_name TEXT,is_banned BOOLEAN NOT NULL DEFAULT FALSE,created_at TIMESTAMPTZ NOT NULL,last_seen_at TIMESTAMPTZ NOT NULL,state TEXT,draft JSONB NOT NULL DEFAULT '{}'::jsonb)''',
        '''CREATE TABLE IF NOT EXISTS profiles (id BIGSERIAL PRIMARY KEY,user_id BIGINT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,gender TEXT NOT NULL,looking_for TEXT NOT NULL,birth_date TEXT NOT NULL,city TEXT NOT NULL,goal TEXT NOT NULL,family_priority INTEGER NOT NULL,love_priority INTEGER NOT NULL,sex_priority INTEGER NOT NULL,values_priority INTEGER NOT NULL,about TEXT NOT NULL,photo_file_id TEXT,contact_consent BOOLEAN NOT NULL DEFAULT FALSE,completed_at TIMESTAMPTZ NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS payments (id BIGSERIAL PRIMARY KEY,buyer_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,candidate_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,amount INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TIMESTAMPTZ NOT NULL,submitted_at TIMESTAMPTZ,paid_at TIMESTAMPTZ)''',
        '''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)'''
    ]
    with db() as c,c.cursor() as cur:
        for s in statements: cur.execute(s)
        defaults={'project_name':'Совпали','contact_price':'100','premium_price':'1200','payment_url':'','chat_url':'','support_username':'','welcome_text':'Подбираем людей по целям, ценностям и совместимости анкеты.'}
        for k,v in defaults.items(): cur.execute('INSERT INTO settings(key,value) VALUES (%s,%s) ON CONFLICT(key) DO NOTHING',(k,v))

def upsert_user(tg):
    t=now()
    with db() as c,c.cursor() as cur:
        cur.execute('''INSERT INTO users(tg_id,username,first_name,created_at,last_seen_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(tg_id) DO UPDATE SET username=EXCLUDED.username,first_name=EXCLUDED.first_name,last_seen_at=EXCLUDED.last_seen_at RETURNING *''',(tg.id,tg.username,tg.first_name,t,t)); return cur.fetchone()
def get_user(uid): return one('SELECT * FROM users WHERE id=%s',(uid,))
def get_profile(uid): return one('SELECT * FROM profiles WHERE user_id=%s',(uid,))
def get_setting(k,default=''):
    r=one('SELECT value FROM settings WHERE key=%s',(k,)); return r['value'] if r else default
def set_setting(k,v): execute('INSERT INTO settings(key,value) VALUES (%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value',(k,v))
def all_settings(): return {r['key']:r['value'] for r in many('SELECT * FROM settings')}
def set_state(uid,state,draft=None): execute('UPDATE users SET state=%s,draft=%s::jsonb WHERE id=%s',(state,json.dumps(draft or {},ensure_ascii=False),uid))
def clear_state(uid): execute("UPDATE users SET state=NULL,draft='{}'::jsonb WHERE id=%s",(uid,))
def save_profile(uid,d):
    vals=(uid,d['name'],d['gender'],d['looking_for'],d['birth_date'],d['city'],d['goal'],int(d['family_priority']),int(d['love_priority']),int(d['sex_priority']),int(d['values_priority']),d['about'],d.get('photo_file_id'),True,now())
    execute('''INSERT INTO profiles(user_id,name,gender,looking_for,birth_date,city,goal,family_priority,love_priority,sex_priority,values_priority,about,photo_file_id,contact_consent,completed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET name=EXCLUDED.name,gender=EXCLUDED.gender,looking_for=EXCLUDED.looking_for,birth_date=EXCLUDED.birth_date,city=EXCLUDED.city,goal=EXCLUDED.goal,family_priority=EXCLUDED.family_priority,love_priority=EXCLUDED.love_priority,sex_priority=EXCLUDED.sex_priority,values_priority=EXCLUDED.values_priority,about=EXCLUDED.about,photo_file_id=EXCLUDED.photo_file_id,contact_consent=TRUE,completed_at=EXCLUDED.completed_at''',vals)
def candidates(uid): return many('''SELECT p.*,u.tg_id,u.username FROM profiles p JOIN users u ON u.id=p.user_id WHERE p.user_id<>%s AND p.contact_consent=TRUE AND u.is_banned=FALSE''',(uid,))
def payment_paid(buyer,cand): return bool(one("SELECT 1 FROM payments WHERE buyer_user_id=%s AND candidate_user_id=%s AND status='paid' LIMIT 1",(buyer,cand)))
def get_payment(pid): return one('SELECT * FROM payments WHERE id=%s',(pid,))
def payment_for(buyer,cand,amount):
    r=one("SELECT * FROM payments WHERE buyer_user_id=%s AND candidate_user_id=%s AND status IN ('pending','submitted','paid') ORDER BY id DESC LIMIT 1",(buyer,cand))
    if r:return r
    with db() as c,c.cursor() as cur: cur.execute("INSERT INTO payments(buyer_user_id,candidate_user_id,amount,status,created_at) VALUES (%s,%s,%s,'pending',%s) RETURNING *",(buyer,cand,amount,now())); return cur.fetchone()

ZODIAC=[((1,20),'Козерог'),((2,19),'Водолей'),((3,21),'Рыбы'),((4,20),'Овен'),((5,21),'Телец'),((6,22),'Близнецы'),((7,23),'Рак'),((8,23),'Лев'),((9,23),'Дева'),((10,23),'Весы'),((11,22),'Скорпион'),((12,22),'Стрелец'),((12,32),'Козерог')]
ELEMENT={'Овен':'Огонь','Лев':'Огонь','Стрелец':'Огонь','Телец':'Земля','Дева':'Земля','Козерог':'Земля','Близнецы':'Воздух','Весы':'Воздух','Водолей':'Воздух','Рак':'Вода','Скорпион':'Вода','Рыбы':'Вода'}
COMP={'Огонь':{'Огонь','Воздух'},'Воздух':{'Воздух','Огонь'},'Земля':{'Земля','Вода'},'Вода':{'Вода','Земля'}}
def zodiac(s):
    dt=datetime.strptime(s,'%d.%m.%Y');md=(dt.month,dt.day)
    for x,sign in ZODIAC:
        if md<x:return sign
    return 'Козерог'
def eligible(a,b):
    if a['looking_for']!='Неважно':
        wanted='Мужчина' if a['looking_for']=='Мужчину' else 'Женщина'
        if b['gender']!=wanted:return False
    lf=b['looking_for'];return lf=='Неважно' or (lf=='Мужчину' and a['gender']=='Мужчина') or (lf=='Женщину' and a['gender']=='Женщина')
def score(a,b):
    s=30 if a['goal']==b['goal'] else 10
    for f in ('family_priority','love_priority','sex_priority','values_priority'):s+=max(0,10-abs(int(a[f])-int(b[f]))*2)
    if a['city'].strip().lower()==b['city'].strip().lower():s+=15
    try:
        za,zb=zodiac(a['birth_date']),zodiac(b['birth_date']);s+=15 if ELEMENT[zb] in COMP[ELEMENT[za]] else 5
    except Exception:s+=5
    return min(100,s)

def kb(rows): return InlineKeyboardMarkup([[InlineKeyboardButton(t,callback_data=d) for t,d in row] for row in rows])
def menu():
    markup=[[InlineKeyboardButton('💘 Найти пару',callback_data='menu:find')],[InlineKeyboardButton('👤 Моя анкета',callback_data='menu:profile'),InlineKeyboardButton('✏️ Заполнить заново',callback_data='menu:reset')]]
    chat=get_setting('chat_url').strip()
    if chat:markup.append([InlineKeyboardButton('💬 Войти в городской чат',url=chat)])
    markup.append([InlineKeyboardButton('ℹ️ Как это работает',callback_data='menu:about')]);return InlineKeyboardMarkup(markup)
def scale(prefix):return kb([[(str(i),f'{prefix}:{i}') for i in range(1,6)]])

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    u=upsert_user(update.effective_user)
    if u['is_banned']:await update.effective_message.reply_text('Ваш профиль заблокирован.');return
    p=get_profile(u['id'])
    if p:await update.effective_message.reply_text(f"❤️ <b>{html.escape(get_setting('project_name','Совпали'))}</b>\n\nВыберите действие:",parse_mode=ParseMode.HTML,reply_markup=menu());return
    clear_state(u['id']);set_state(u['id'],'age',{})
    await update.effective_message.reply_text(f"❤️ <b>Совпали</b>\n\n{html.escape(get_setting('welcome_text'))}\n\nСервис только 18+. Вам уже исполнилось 18 лет?",parse_mode=ParseMode.HTML,reply_markup=kb([[('Да, мне 18+','age:yes')],[('Нет','age:no')]]))

async def callback(update:Update,context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query;await q.answer();u=upsert_user(update.effective_user);data=q.data;state=u['state'];draft=dict(u['draft'] or {})
    if data=='age:no':clear_state(u['id']);await q.edit_message_text('Сервис доступен только пользователям 18+.');return
    if data=='age:yes' and state=='age':set_state(u['id'],'name',draft);await q.edit_message_text('Как вас зовут? Напишите имя.');return
    if data.startswith('gender:') and state=='gender':draft['gender']=data.split(':',1)[1];set_state(u['id'],'looking',draft);await q.edit_message_text('Кого хотите найти?',reply_markup=kb([[('Мужчину','looking:Мужчину'),('Женщину','looking:Женщину')],[('Неважно','looking:Неважно')]]));return
    if data.startswith('looking:') and state=='looking':draft['looking_for']=data.split(':',1)[1];set_state(u['id'],'birth',draft);await q.edit_message_text('Дата рождения? Например: 05.01.1990');return
    if data.startswith('goal:') and state=='goal':draft['goal']=data.split(':',1)[1];set_state(u['id'],'family',draft);await q.edit_message_text('Насколько важна семья? 1 — не принципиально, 5 — очень важно',reply_markup=scale('family'));return
    if data.startswith('family:') and state=='family':draft['family_priority']=int(data.split(':')[1]);set_state(u['id'],'love',draft);await q.edit_message_text('Насколько важны любовь и эмоциональная близость?',reply_markup=scale('love'));return
    if data.startswith('love:') and state=='love':draft['love_priority']=int(data.split(':')[1]);set_state(u['id'],'sex',draft);await q.edit_message_text('Насколько важна сексуальная совместимость?',reply_markup=scale('sex'));return
    if data.startswith('sex:') and state=='sex':draft['sex_priority']=int(data.split(':')[1]);set_state(u['id'],'values',draft);await q.edit_message_text('Насколько важны общие ценности?',reply_markup=scale('values'));return
    if data.startswith('values:') and state=='values':draft['values_priority']=int(data.split(':')[1]);set_state(u['id'],'about',draft);await q.edit_message_text('Коротко расскажите о себе — 1–3 предложения.');return
    if data=='photo:skip' and state=='photo':draft['photo_file_id']=None;set_state(u['id'],'consent',draft);await q.edit_message_text('Разрешаете открыть ваш Telegram-контакт пользователю, который выбрал анкету и оплатил контакт?',reply_markup=kb([[('Да, разрешаю','consent:yes')],[('Нет','consent:no')]]));return
    if data.startswith('consent:') and state=='consent':
        if data=='consent:no':clear_state(u['id']);await q.edit_message_text('Без согласия анкета не участвует в подборе. /start — начать заново.');return
        save_profile(u['id'],draft);clear_state(u['id']);await q.edit_message_text('✅ Анкета готова! Теперь можно искать совпадения.',reply_markup=menu());return
    if data.startswith('menu:'):
        p=get_profile(u['id']);action=data.split(':',1)[1]
        if not p:await q.edit_message_text('Сначала заполните анкету: /start');return
        if action=='profile':await q.edit_message_text(f"👤 <b>{html.escape(p['name'])}</b>\nГород: {html.escape(p['city'])}\nИщу: {html.escape(p['looking_for'])}\nЦель: {html.escape(p['goal'])}\n\nО себе: {html.escape(p['about'])}",parse_mode=ParseMode.HTML,reply_markup=menu());return
        if action=='reset':execute('DELETE FROM profiles WHERE user_id=%s',(u['id'],));clear_state(u['id']);await q.edit_message_text('Анкета удалена. Нажмите /start.');return
        if action=='about':await q.edit_message_text('Подбор учитывает цель знакомства, город, четыре приоритета и дополнительный фактор по дате рождения. Процент — ориентир, не гарантия отношений.',reply_markup=menu());return
        if action=='find':
            found=sorted([(score(p,c),c) for c in candidates(u['id']) if eligible(p,c)],key=lambda x:x[0],reverse=True)[:3]
            if not found:await q.edit_message_text('Пока подходящих анкет недостаточно. Попробуйте позже.',reply_markup=menu());return
            rows=[];lines=['💘 <b>Ваши лучшие совпадения:</b>','']
            for i,(s,c) in enumerate(found,1):lines.append(f"{i}. <b>{html.escape(c['name'])}</b> — {s}%");rows.append([(f"{i}. {c['name']} — {s}%",f"candidate:{c['user_id']}:{s}")])
            await q.edit_message_text('\n'.join(lines),parse_mode=ParseMode.HTML,reply_markup=kb(rows+[[('⬅️ Меню','menu:profile')]]));return
    if data.startswith('candidate:'):
        _,cid,s=data.split(':');cid=int(cid);c=get_profile(cid)
        if not c:await q.message.reply_text('Анкета недоступна.');return
        price=int(get_setting('contact_price','100'));text=f"💘 <b>{html.escape(c['name'])}</b> — совпадение {s}%\nГород: {html.escape(c['city'])}\nЦель: {html.escape(c['goal'])}\n\n{html.escape(c['about'])}";buttons=kb([[(f'🔓 Открыть контакт — {price} ₽',f'buy:{cid}')]])
        if c['photo_file_id']:await q.message.reply_photo(c['photo_file_id'],caption=text,parse_mode=ParseMode.HTML,reply_markup=buttons)
        else:await q.message.reply_text(text,parse_mode=ParseMode.HTML,reply_markup=buttons)
        return
    if data.startswith('buy:'):
        cid=int(data.split(':')[1]);price=int(get_setting('contact_price','100'))
        if payment_paid(u['id'],cid):await send_contact(update.effective_chat.id,cid,context);return
        pay=payment_for(u['id'],cid,price);url=get_setting('payment_url').strip()
        if not url:await q.message.reply_text('Оплата пока не подключена.');return
        await q.message.reply_text(f'Стоимость контакта: <b>{price} ₽</b>. После оплаты вернитесь и нажмите «Я оплатил».',parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('💳 Оплатить',url=url)],[InlineKeyboardButton('✅ Я оплатил',callback_data=f"paid:{pay['id']}")],[InlineKeyboardButton('🔄 Проверить',callback_data=f"check:{pay['id']}")]]));return
    if data.startswith('paid:'):
        pid=int(data.split(':')[1]);p=get_payment(pid)
        if p and p['buyer_user_id']==u['id']:
            if p['status']=='paid':await send_contact(update.effective_chat.id,p['candidate_user_id'],context)
            else:execute("UPDATE payments SET status='submitted',submitted_at=%s WHERE id=%s",(now(),pid));await q.message.reply_text('✅ Отметил. Администратор увидит заявку и подтвердит платёж.')
        return
    if data.startswith('check:'):
        p=get_payment(int(data.split(':')[1]))
        if p and p['buyer_user_id']==u['id'] and p['status']=='paid':await send_contact(update.effective_chat.id,p['candidate_user_id'],context)
        else:await q.message.reply_text('Пока оплата не подтверждена.')

async def text_or_photo(update:Update,context:ContextTypes.DEFAULT_TYPE):
    u=upsert_user(update.effective_user);state=u['state'];draft=dict(u['draft'] or {})
    if not state:return
    if state=='name' and update.message.text:draft['name']=update.message.text.strip()[:60];set_state(u['id'],'gender',draft);await update.message.reply_text('Ваш пол?',reply_markup=kb([[('Мужчина','gender:Мужчина'),('Женщина','gender:Женщина')]]));return
    if state=='birth' and update.message.text:
        s=update.message.text.strip()
        try:dt=datetime.strptime(s,'%d.%m.%Y');today=datetime.now();age=today.year-dt.year-((today.month,today.day)<(dt.month,dt.day));assert 18<=age<=100
        except Exception:await update.message.reply_text('Введите дату, например 05.01.1990');return
        draft['birth_date']=s;set_state(u['id'],'city',draft);await update.message.reply_text('В каком городе вы сейчас живёте?');return
    if state=='city' and update.message.text:draft['city']=update.message.text.strip()[:80];set_state(u['id'],'goal',draft);await update.message.reply_text('Что вы ищете?',reply_markup=kb([[('Серьёзные отношения','goal:Серьёзные отношения')],[('Общение и знакомства','goal:Общение и знакомства')],[('Пока не определился(ась)','goal:Пока не определился(ась)')]]));return
    if state=='about' and update.message.text:draft['about']=update.message.text.strip()[:500];set_state(u['id'],'photo',draft);await update.message.reply_text('Пришлите одно фото или нажмите «Без фото».',reply_markup=kb([[('Без фото','photo:skip')]]));return
    if state=='photo' and update.message.photo:draft['photo_file_id']=update.message.photo[-1].file_id;set_state(u['id'],'consent',draft);await update.message.reply_text('Разрешаете открыть ваш Telegram-контакт пользователю, который выбрал анкету и оплатил контакт?',reply_markup=kb([[('Да, разрешаю','consent:yes')],[('Нет','consent:no')]]));return

async def send_contact(chat_id,cid,context):
    c=get_user(cid);p=get_profile(cid)
    if not c or not p:return
    contact='@'+html.escape(c['username']) if c['username'] else f'<a href="tg://user?id={c["tg_id"]}">Открыть Telegram-профиль</a>';await context.bot.send_message(chat_id,f"🔓 <b>Контакт открыт</b>\n\n{html.escape(p['name'])}: {contact}\n\nНапишите человеку уважительно.",parse_mode=ParseMode.HTML)

bot=Application.builder().token(TOKEN).build();bot.add_handler(CommandHandler('start',start));bot.add_handler(CommandHandler('menu',start));bot.add_handler(CallbackQueryHandler(callback));bot.add_handler(MessageHandler((filters.TEXT|filters.PHOTO)&~filters.COMMAND,text_or_photo))
bot_loop=asyncio.new_event_loop();bot_ready=threading.Event()
async def bot_start():
    await bot.initialize();await bot.start()
    if WEBHOOK_BASE_URL:
        kw={'url':WEBHOOK_BASE_URL+'/telegram/webhook','drop_pending_updates':False}
        if WEBHOOK_SECRET:kw['secret_token']=WEBHOOK_SECRET
        await bot.bot.set_webhook(**kw);log.info('Webhook set: %s',kw['url'])
    bot_ready.set()
def bot_thread():asyncio.set_event_loop(bot_loop);bot_loop.run_until_complete(bot_start());bot_loop.run_forever()

BASE='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Совпали — админка</title><style>body{font-family:Arial;margin:0;background:#f5f6f8;color:#18181b}nav{background:#18181b;padding:14px;color:#fff}nav a{color:#fff;margin-right:18px;text-decoration:none}.wrap{max-width:1050px;margin:24px auto;padding:0 16px}.card{background:#fff;border-radius:14px;padding:18px;margin:14px 0;box-shadow:0 2px 12px #0001}input,textarea{width:100%;padding:10px;margin:5px 0 14px;box-sizing:border-box}button{background:#18181b;color:#fff;border:0;padding:10px 14px;border-radius:8px}table{width:100%;border-collapse:collapse;background:#fff}td,th{padding:10px;border-bottom:1px solid #eee;text-align:left}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.metric{font-size:30px;font-weight:700}</style>{nav}<div class="wrap">{body}</div></html>'''
def nav():return '<nav>❤️ <b>Совпали</b> &nbsp; <a href="/admin">Главная</a><a href="/admin/users">Пользователи</a><a href="/admin/payments">Оплаты</a><a href="/admin/settings">Настройки</a><a href="/admin/logout">Выйти</a></nav>' if session.get('admin') else ''
def page(body):return BASE.format(nav=nav(),body=body)
def login_required(fn):
    @wraps(fn)
    def w(*a,**kw):return redirect('/admin/login') if not session.get('admin') else fn(*a,**kw)
    return w

@app.get('/')
def root():return redirect('/admin')
@app.route('/admin/login',methods=['GET','POST'])
def login():
    msg=''
    if request.method=='POST':
        if request.form.get('username')==ADMIN_USERNAME and request.form.get('password')==ADMIN_PASSWORD:session['admin']=True;return redirect('/admin')
        msg='<p>Неверный логин или пароль</p>'
    return page(f'<div class="card" style="max-width:420px;margin:70px auto"><h2>Вход</h2>{msg}<form method="post"><input name="username" placeholder="Логин"><input type="password" name="password" placeholder="Пароль"><button>Войти</button></form></div>')
@app.get('/admin/logout')
def logout():session.clear();return redirect('/admin/login')
@app.get('/admin')
@login_required
def dashboard():
    s={'users':one('SELECT COUNT(*) c FROM users')['c'],'profiles':one('SELECT COUNT(*) c FROM profiles')['c'],'submitted':one("SELECT COUNT(*) c FROM payments WHERE status='submitted'")['c'],'paid':one("SELECT COUNT(*) c FROM payments WHERE status='paid'")['c'],'revenue':one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE status='paid'")['s']};cards=''.join(f'<div class="card"><div>{k}</div><div class="metric">{v}</div></div>' for k,v in [('Пользователи',s['users']),('Анкеты',s['profiles']),('Ждут проверки',s['submitted']),('Оплачено',s['paid']),('Выручка ₽',s['revenue'])]);return page('<h1>Главная</h1><div class="grid">'+cards+'</div>')
@app.get('/admin/users')
@login_required
def users():
    rows=many('SELECT u.*,p.name,p.city,p.goal FROM users u LEFT JOIN profiles p ON p.user_id=u.id ORDER BY u.id DESC');trs=''.join(f"<tr><td><a href='/admin/users/{r['id']}'>#{r['id']}</a></td><td>{html.escape(r['name'] or 'Анкета не заполнена')}</td><td>{html.escape('@'+r['username'] if r['username'] else str(r['tg_id']))}</td><td>{html.escape(r['city'] or '—')}</td><td>{html.escape(r['goal'] or '—')}</td></tr>" for r in rows);return page('<h1>Пользователи</h1><table><tr><th>ID</th><th>Имя</th><th>Telegram</th><th>Город</th><th>Цель</th></tr>'+trs+'</table>')
@app.route('/admin/users/<int:uid>',methods=['GET','POST'])
@login_required
def user_detail(uid):
    if request.method=='POST':execute('UPDATE users SET is_banned=NOT is_banned WHERE id=%s',(uid,));return redirect(f'/admin/users/{uid}')
    r=one('SELECT u.*,p.name,p.city,p.goal,p.about FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id=%s',(uid,));return page('Не найден') if not r else page(f"<h1>Пользователь #{uid}</h1><div class='card'><p><b>Имя:</b> {html.escape(r['name'] or '—')}</p><p><b>Telegram:</b> {html.escape('@'+r['username'] if r['username'] else str(r['tg_id']))}</p><p><b>Город:</b> {html.escape(r['city'] or '—')}</p><p><b>Цель:</b> {html.escape(r['goal'] or '—')}</p><p><b>О себе:</b> {html.escape(r['about'] or '—')}</p><form method='post'><button>{'Разблокировать' if r['is_banned'] else 'Заблокировать'}</button></form></div>")
@app.get('/admin/payments')
@login_required
def payments():
    rows=many('SELECT pay.*,bp.name buyer_name,cp.name candidate_name FROM payments pay LEFT JOIN profiles bp ON bp.user_id=pay.buyer_user_id LEFT JOIN profiles cp ON cp.user_id=pay.candidate_user_id ORDER BY pay.id DESC');trs=''.join(f"<tr><td>#{r['id']}</td><td>{html.escape(r['buyer_name'] or '—')}</td><td>{html.escape(r['candidate_name'] or '—')}</td><td>{r['amount']} ₽</td><td>{r['status']}</td><td>{'' if r['status']=='paid' else f'''<form method='post' action='/admin/payments/{r['id']}/confirm'><button>Подтвердить</button></form>'''}</td></tr>" for r in rows);return page('<h1>Оплаты</h1><table><tr><th>ID</th><th>Покупатель</th><th>Контакт</th><th>Сумма</th><th>Статус</th><th></th></tr>'+trs+'</table>')
@app.post('/admin/payments/<int:pid>/confirm')
@login_required
def confirm_payment(pid):
    p=get_payment(pid)
    if p:
        execute("UPDATE payments SET status='paid',paid_at=%s WHERE id=%s",(now(),pid));buyer=get_user(p['buyer_user_id']);cand=get_user(p['candidate_user_id']);prof=get_profile(p['candidate_user_id'])
        if buyer and cand and prof:
            contact='@'+cand['username'] if cand['username'] else f'<a href="tg://user?id={cand["tg_id"]}">Открыть Telegram-профиль</a>';requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',json={'chat_id':buyer['tg_id'],'text':f"🔓 <b>Контакт открыт</b>\n\n{html.escape(prof['name'])}: {contact}",'parse_mode':'HTML'},timeout=10)
    return redirect('/admin/payments')
@app.route('/admin/settings',methods=['GET','POST'])
@login_required
def settings():
    keys=['project_name','contact_price','premium_price','payment_url','chat_url','support_username','welcome_text']
    if request.method=='POST':
        for k in keys:set_setting(k,request.form.get(k,'').strip())
        return redirect('/admin/settings')
    s=all_settings();labels={'project_name':'Название проекта','contact_price':'Цена контакта, ₽','premium_price':'Цена Premium, ₽','payment_url':'Платёжная ссылка','chat_url':'Ссылка на городской чат','support_username':'Telegram поддержки','welcome_text':'Приветственный текст'};fields=''
    for k in keys:
        if k=='welcome_text':fields+=f"<label>{labels[k]}</label><textarea name='{k}'>{html.escape(s.get(k,''))}</textarea>"
        else:fields+=f"<label>{labels[k]}</label><input name='{k}' value='{html.escape(s.get(k,''))}'>"
    return page("<h1>Настройки</h1><div class='card'><form method='post'>"+fields+"<button>Сохранить</button></form></div>")
@app.get('/health')
def health():return jsonify(ok=True,bot_ready=bot_ready.is_set())
@app.post('/telegram/webhook')
def webhook():
    if WEBHOOK_SECRET and request.headers.get('X-Telegram-Bot-Api-Secret-Token','')!=WEBHOOK_SECRET:return ('forbidden',403)
    if not bot_ready.wait(15):return ('not ready',503)
    upd=Update.de_json(request.get_json(force=True),bot.bot);asyncio.run_coroutine_threadsafe(bot.process_update(upd),bot_loop);return ('ok',200)

if __name__=='__main__':init_db();threading.Thread(target=bot_thread,daemon=True).start();serve(app,host='0.0.0.0',port=PORT,threads=8)
