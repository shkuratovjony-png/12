from __future__ import annotations
import asyncio, html, os, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime
from functools import wraps

from flask import Flask, redirect, request, session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from waitress import serve
from visuals import visual, animation, as_file

TOKEN=os.environ['BOT_TOKEN'].strip()
BASE_URL=os.getenv('WEBHOOK_BASE_URL','').strip().rstrip('/')
WEBHOOK_SECRET=os.getenv('WEBHOOK_SECRET','').strip()
ADMIN_USER=os.getenv('ADMIN_USERNAME','admin')
ADMIN_PASSWORD=os.environ['ADMIN_PASSWORD']
FLASK_SECRET=os.environ['FLASK_SECRET']
PORT=int(os.getenv('PORT','10000'))
DB_PATH=os.getenv('DB_PATH','/tmp/sovpali_v2.db')

app=Flask(__name__); app.secret_key=FLASK_SECRET

@contextmanager
def db():
    c=sqlite3.connect(DB_PATH,timeout=30,check_same_thread=False); c.row_factory=sqlite3.Row
    try: yield c; c.commit()
    finally: c.close()

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,tg_id INTEGER UNIQUE NOT NULL,username TEXT,first_name TEXT,is_banned INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,last_seen_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS profiles(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE NOT NULL,name TEXT NOT NULL,gender TEXT NOT NULL,looking_for TEXT NOT NULL,birth_date TEXT NOT NULL,birth_time TEXT,birth_place TEXT NOT NULL,city TEXT NOT NULL,goal TEXT NOT NULL,priority TEXT NOT NULL,photo_file_id TEXT,completed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')
        defaults={
            'project_name':'Совпали',
            'chat_url':'',
            'support_username':'',
            'welcome_text':'Мы помогаем найти максимально совместимого человека по ценностям, семье, отношениям, нумерологии и астрологическим параметрам. Ответьте на несколько коротких вопросов — остальное сделает система.'
        }
        for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))

def now(): return datetime.now().isoformat(timespec='seconds')
def one(sql,p=()):
    with db() as c: return c.execute(sql,p).fetchone()
def many(sql,p=()):
    with db() as c: return c.execute(sql,p).fetchall()
def execute(sql,p=()):
    with db() as c: c.execute(sql,p)
def setting(k,default=''):
    r=one('SELECT value FROM settings WHERE key=?',(k,)); return r['value'] if r else default
def set_setting(k,v): execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
def upsert_user(tg):
    t=now()
    with db() as c:
        c.execute('''INSERT INTO users(tg_id,username,first_name,created_at,last_seen_at) VALUES(?,?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_seen_at=excluded.last_seen_at''',(tg.id,tg.username,tg.first_name,t,t))
        return c.execute('SELECT * FROM users WHERE tg_id=?',(tg.id,)).fetchone()
def profile(uid): return one('SELECT * FROM profiles WHERE user_id=?',(uid,))
def user(uid): return one('SELECT * FROM users WHERE id=?',(uid,))
def save_profile(uid,d):
    vals=(uid,d['name'],d['gender'],d['looking_for'],d['birth_date'],d.get('birth_time'),d['birth_place'],d['city'],d['goal'],d['priority'],d.get('photo'),now())
    execute('''INSERT INTO profiles(user_id,name,gender,looking_for,birth_date,birth_time,birth_place,city,goal,priority,photo_file_id,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,gender=excluded.gender,looking_for=excluded.looking_for,birth_date=excluded.birth_date,birth_time=excluded.birth_time,birth_place=excluded.birth_place,city=excluded.city,goal=excluded.goal,priority=excluded.priority,photo_file_id=excluded.photo_file_id,completed_at=excluded.completed_at''',vals)

ZODIAC=[((1,20),'Козерог'),((2,19),'Водолей'),((3,21),'Рыбы'),((4,20),'Овен'),((5,21),'Телец'),((6,22),'Близнецы'),((7,23),'Рак'),((8,23),'Лев'),((9,23),'Дева'),((10,23),'Весы'),((11,22),'Скорпион'),((12,22),'Стрелец'),((12,32),'Козерог')]
ELEMENT={'Овен':'Огонь','Лев':'Огонь','Стрелец':'Огонь','Телец':'Земля','Дева':'Земля','Козерог':'Земля','Близнецы':'Воздух','Весы':'Воздух','Водолей':'Воздух','Рак':'Вода','Скорпион':'Вода','Рыбы':'Вода'}
GOOD={'Огонь':{'Огонь','Воздух'},'Воздух':{'Воздух','Огонь'},'Земля':{'Земля','Вода'},'Вода':{'Вода','Земля'}}
def zodiac(s):
    d=datetime.strptime(s,'%d.%m.%Y'); md=(d.month,d.day)
    for x,sign in ZODIAC:
        if md<x: return sign
    return 'Козерог'
def lifepath(s):
    n=sum(int(ch) for ch in s if ch.isdigit())
    while n>9 and n not in (11,22,33): n=sum(int(ch) for ch in str(n))
    return n
def eligible(a,b):
    if a['looking_for']=='Мужчину' and b['gender']!='Мужчина': return False
    if a['looking_for']=='Женщину' and b['gender']!='Женщина': return False
    if b['looking_for']=='Мужчину' and a['gender']!='Мужчина': return False
    if b['looking_for']=='Женщину' and a['gender']!='Женщина': return False
    return True
def score(a,b):
    s=18
    if a['goal']==b['goal']: s+=24
    if a['priority']==b['priority']: s+=20
    if a['city'].strip().lower()==b['city'].strip().lower(): s+=12
    try:
        za,zb=zodiac(a['birth_date']),zodiac(b['birth_date'])
        s+=16 if ELEMENT[zb] in GOOD[ELEMENT[za]] else 7
        la,lb=lifepath(a['birth_date']),lifepath(b['birth_date'])
        s+=14 if la==lb or abs(la-lb) in (1,3) else 7
    except Exception: s+=10
    return min(98,s)
def reasons(a,b):
    r=[]
    if a['goal']==b['goal']: r.append('одинаково смотрите на формат отношений')
    if a['priority']==b['priority']: r.append('совпадает главный приоритет в отношениях')
    if a['city'].strip().lower()==b['city'].strip().lower(): r.append('вы из одного города')
    try:
        za,zb=zodiac(a['birth_date']),zodiac(b['birth_date'])
        if ELEMENT[zb] in GOOD[ELEMENT[za]]: r.append('астрологические элементы хорошо сочетаются')
        if lifepath(a['birth_date'])==lifepath(b['birth_date']): r.append('совпадает нумерологический ритм')
    except Exception: pass
    return r[:3] or ['есть несколько совместимых параметров профиля']

MENU=ReplyKeyboardMarkup([
    [KeyboardButton('💖 Мои пары'),KeyboardButton('👤 Мой профиль')],
    [KeyboardButton('✨ Подбор'),KeyboardButton('💬 Чаты')],
    [KeyboardButton('⚙️ Ещё')]
],resize_keyboard=True,is_persistent=True)
def ik(rows): return InlineKeyboardMarkup([[InlineKeyboardButton(t,callback_data=d) for t,d in row] for row in rows])

async def send_card(message,theme,caption,reply_markup=None,animated=False):
    if animated:
        await message.reply_animation(as_file(animation(theme),f'{theme}.gif'),caption=caption,parse_mode=ParseMode.HTML,reply_markup=reply_markup)
    else:
        await message.reply_photo(as_file(visual(theme),f'{theme}.jpg'),caption=caption,parse_mode=ParseMode.HTML,reply_markup=reply_markup)

AGE,GENDER,LOOKING,BIRTH,TIME_CHOICE,TIME_TEXT,BIRTH_PLACE,CITY,GOAL,PRIORITY,PHOTO=range(11)

async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    u=upsert_user(update.effective_user)
    if u['is_banned']:
        await update.effective_message.reply_text('Профиль временно недоступен.'); return ConversationHandler.END
    p=profile(u['id'])
    if p:
        await send_card(update.effective_message,'welcome',f"✨ <b>С возвращением в «Совпали»</b>\n\n{html.escape(p['name'])}, твой профиль готов. Открой «Мои пары» или запусти новый подбор.",MENU,True)
        return ConversationHandler.END
    ctx.user_data['p']={'name':update.effective_user.first_name or 'Пользователь'}
    text=("✨ <b>Совпали</b>\n\n"+html.escape(setting('welcome_text'))+
          "\n\nДанные рождения помогают учитывать астрологические и нумерологические параметры. Никаких длинных анкет — только несколько коротких шагов.\n\n<b>Тебе уже исполнилось 18 лет?</b>")
    await send_card(update.effective_message,'welcome',text,ik([[('Да, мне 18+','age:y')],[('Нет','age:n')]]),True)
    return AGE

async def age(update,ctx):
    q=update.callback_query; await q.answer()
    if q.data=='age:n':
        await q.message.reply_text('Сервис доступен только пользователям 18+.'); return ConversationHandler.END
    await send_card(q.message,'gender','👤 <b>Шаг 1 из 8</b>\n\nКто ты?',ik([[('Мужчина','g:Мужчина'),('Женщина','g:Женщина')]]))
    return GENDER
async def gender(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['p']['gender']=q.data[2:]
    await send_card(q.message,'looking','💫 <b>Шаг 2 из 8</b>\n\nКого ты хочешь встретить?',ik([[('Мужчину','l:Мужчину'),('Женщину','l:Женщину')],[('Неважно','l:Неважно')]]))
    return LOOKING
async def looking(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['p']['looking_for']=q.data[2:]
    await send_card(q.message,'birth','♒ <b>Шаг 3 из 8</b>\n\nНапиши дату рождения в формате <b>ДД.ММ.ГГГГ</b>.\nНапример: 05.01.1990')
    return BIRTH
async def birth(update,ctx):
    s=update.message.text.strip()
    try:
        d=datetime.strptime(s,'%d.%m.%Y'); t=datetime.now(); a=t.year-d.year-((t.month,t.day)<(d.month,d.day))
        if not 18<=a<=100: raise ValueError
    except Exception:
        await update.message.reply_text('Нужна дата в формате ДД.ММ.ГГГГ, например 05.01.1990'); return BIRTH
    ctx.user_data['p']['birth_date']=s
    await send_card(update.message,'time','🕰 <b>Шаг 4 из 8</b>\n\nЗнаешь время рождения? Оно может сделать астрологический профиль точнее.',ik([[('Да, знаю','time:know')],[('Не знаю — пропустить','time:skip')]]))
    return TIME_CHOICE
async def time_choice(update,ctx):
    q=update.callback_query; await q.answer()
    if q.data=='time:skip':
        ctx.user_data['p']['birth_time']=None
        await send_card(q.message,'place','📍 <b>Шаг 5 из 8</b>\n\nГде ты родился? Напиши город рождения.'); return BIRTH_PLACE
    await q.message.reply_text('Напиши время рождения, например 14:35'); return TIME_TEXT
async def time_text(update,ctx):
    s=update.message.text.strip()
    try: datetime.strptime(s,'%H:%M')
    except Exception:
        await update.message.reply_text('Напиши время в формате ЧЧ:ММ, например 14:35'); return TIME_TEXT
    ctx.user_data['p']['birth_time']=s
    await send_card(update.message,'place','📍 <b>Шаг 5 из 8</b>\n\nГде ты родился? Напиши город рождения.')
    return BIRTH_PLACE
async def birth_place(update,ctx):
    ctx.user_data['p']['birth_place']=update.message.text.strip()[:90]
    await send_card(update.message,'city','🌃 <b>Шаг 6 из 8</b>\n\nВ каком городе ты живёшь сейчас?')
    return CITY
async def city(update,ctx):
    ctx.user_data['p']['city']=update.message.text.strip()[:90]
    await send_card(update.message,'goal','💍 <b>Шаг 7 из 8</b>\n\nЧто ты ищешь сейчас?',ik([[('Серьёзные отношения','goal:Серьёзные отношения')],[('Любовь и семья','goal:Любовь и семья')],[('Общение и знакомство','goal:Общение и знакомство')],[('Пока присматриваюсь','goal:Пока присматриваюсь')]]))
    return GOAL
async def goal(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['p']['goal']=q.data.split(':',1)[1]
    await send_card(q.message,'priority','💎 <b>Шаг 8 из 8</b>\n\nЧто для тебя важнее всего в отношениях?',ik([[('👨‍👩‍👧 Семья','prio:Семья'),('❤️ Любовь','prio:Любовь')],[('🧭 Общие ценности','prio:Ценности'),('🔥 Страсть','prio:Страсть')],[('🤝 Спокойствие и опора','prio:Опора')]]))
    return PRIORITY
async def priority(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['p']['priority']=q.data.split(':',1)[1]
    await send_card(q.message,'photo','📸 <b>Почти готово</b>\n\nДобавь одну фотографию — так будущие совпадения будут выглядеть живее. Можно пропустить и добавить позже.',ik([[('Пропустить пока','photo:skip')]]))
    return PHOTO
async def photo(update,ctx):
    if update.message and update.message.photo:
        ctx.user_data['p']['photo']=update.message.photo[-1].file_id
        return await finish_profile(update,ctx,update.message)
    return PHOTO
async def photo_skip(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['p']['photo']=None
    return await finish_profile(update,ctx,q.message)
async def finish_profile(update,ctx,message):
    u=upsert_user(update.effective_user); save_profile(u['id'],ctx.user_data['p'])
    await send_card(message,'matching','✨ <b>Профиль создан</b>\n\nТеперь «Совпали» может сравнивать твои данные с другими анкетами: цель отношений, главный приоритет, город, нумерологический ритм и астрологические параметры.\n\nОткрой <b>«Мои пары»</b> в нижнем меню.',MENU,True)
    return ConversationHandler.END

async def pairs_view(message,u,p,animated=False):
    if animated:
        await send_card(message,'matching','✨ Анализирую совместимость и ищу самые сильные совпадения…',None,True)
    cs=many('SELECT p.*,u.username,u.tg_id FROM profiles p JOIN users u ON u.id=p.user_id WHERE p.user_id<>? AND u.is_banned=0',(u['id'],))
    found=sorted([(score(p,c),c) for c in cs if eligible(p,c)],key=lambda x:x[0],reverse=True)[:3]
    if not found:
        await send_card(message,'pairs','💖 <b>Твои пары</b>\n\nПока недостаточно анкет для качественного подбора. Когда появятся подходящие люди, они будут здесь автоматически.',MENU)
        return
    rows=[]; lines=['💖 <b>Твои лучшие совпадения</b>','']
    for i,(s,c) in enumerate(found,1):
        lines.append(f"{i}. <b>{html.escape(c['name'])}</b> — {s}%")
        rows.append([(f'{i}. {c["name"]} · {s}%',f'cand:{c["user_id"]}:{s}')])
    await send_card(message,'pairs','\n'.join(lines),ik(rows))

async def cabinet(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message; text=(msg.text or '').strip(); u=upsert_user(update.effective_user); p=profile(u['id'])
    if not p:
        await msg.reply_text('Сначала создай профиль — нажми /start',reply_markup=ReplyKeyboardRemove()); return
    if text=='💖 Мои пары':
        await pairs_view(msg,u,p)
    elif text=='✨ Подбор':
        await pairs_view(msg,u,p,True)
    elif text=='👤 Мой профиль':
        bt=p['birth_time'] or 'не указано'
        cap=(f"👤 <b>{html.escape(p['name'])}</b>\n\n"
             f"Город: {html.escape(p['city'])}\n"
             f"Ищу: {html.escape(p['looking_for'])}\n"
             f"Цель: {html.escape(p['goal'])}\n"
             f"Главное: {html.escape(p['priority'])}\n"
             f"Дата рождения: {html.escape(p['birth_date'])}\n"
             f"Время рождения: {html.escape(bt)}\n"
             f"Место рождения: {html.escape(p['birth_place'])}")
        await send_card(msg,'profile',cap,ik([[('🔄 Обновить профиль','profile:reset')]]))
    elif text=='💬 Чаты':
        url=setting('chat_url').strip()
        if url:
            await send_card(msg,'chats','💬 <b>Чаты «Совпали»</b>\n\nЗдесь можно перейти в городской чат и познакомиться с участниками напрямую.',InlineKeyboardMarkup([[InlineKeyboardButton('Открыть городской чат',url=url)]]))
        else:
            await send_card(msg,'chats','💬 <b>Чаты «Совпали»</b>\n\nГородской чат скоро появится здесь. Пока сосредоточимся на персональном подборе.',MENU)
    elif text=='⚙️ Ещё':
        support=setting('support_username').strip().lstrip('@')
        rows=[[('✨ Как работает подбор','more:about')],[('🔄 Заполнить профиль заново','profile:reset')]]
        if support: rows.append([('💬 Поддержка','more:support')])
        await send_card(msg,'more','⚙️ <b>Ещё</b>\n\nНастройки профиля и информация о сервисе.',ik(rows))

async def inline(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); u=upsert_user(update.effective_user); p=profile(u['id']); data=q.data
    if data=='profile:reset':
        execute('DELETE FROM profiles WHERE user_id=?',(u['id'],)); ctx.user_data.clear(); await q.message.reply_text('Профиль очищен. Нажми /start и создай его заново.',reply_markup=ReplyKeyboardRemove()); return
    if data=='more:about':
        await q.message.reply_text('«Совпали» сравнивает цели знакомства, ценности и жизненные приоритеты, а также использует дату рождения для нумерологических и базовых астрологических параметров. Процент совместимости — ориентир для знакомства, а не гарантия отношений.',reply_markup=MENU); return
    if data=='more:support':
        s=setting('support_username').strip().lstrip('@'); await q.message.reply_text(f'Поддержка: @{html.escape(s)}',reply_markup=MENU); return
    if data.startswith('cand:') and p:
        _,cid,s=data.split(':'); c=profile(int(cid)); uu=user(int(cid))
        if not c or not uu: return
        rs='\n'.join('• '+html.escape(x) for x in reasons(p,c))
        cap=(f"💖 <b>{html.escape(c['name'])}</b> · {s}%\n"
             f"Город: {html.escape(c['city'])}\n"
             f"Цель: {html.escape(c['goal'])}\n"
             f"Главное: {html.escape(c['priority'])}\n\n"
             f"<b>Почему вы совпали:</b>\n{rs}")
        if c['photo_file_id']:
            await q.message.reply_photo(c['photo_file_id'],caption=cap,parse_mode=ParseMode.HTML)
        else:
            await send_card(q.message,'pairs',cap)

bot=Application.builder().token(TOKEN).build()
conv=ConversationHandler(
    entry_points=[CommandHandler('start',start)],
    states={
        AGE:[CallbackQueryHandler(age,pattern=r'^age:')],
        GENDER:[CallbackQueryHandler(gender,pattern=r'^g:')],
        LOOKING:[CallbackQueryHandler(looking,pattern=r'^l:')],
        BIRTH:[MessageHandler(filters.TEXT & ~filters.COMMAND,birth)],
        TIME_CHOICE:[CallbackQueryHandler(time_choice,pattern=r'^time:')],
        TIME_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND,time_text)],
        BIRTH_PLACE:[MessageHandler(filters.TEXT & ~filters.COMMAND,birth_place)],
        CITY:[MessageHandler(filters.TEXT & ~filters.COMMAND,city)],
        GOAL:[CallbackQueryHandler(goal,pattern=r'^goal:')],
        PRIORITY:[CallbackQueryHandler(priority,pattern=r'^prio:')],
        PHOTO:[MessageHandler(filters.PHOTO,photo),CallbackQueryHandler(photo_skip,pattern=r'^photo:skip$')],
    },fallbacks=[CommandHandler('start',start)],allow_reentry=True
)
bot.add_handler(conv)
bot.add_handler(CallbackQueryHandler(inline,pattern=r'^(cand:|profile:|more:)'))
bot.add_handler(MessageHandler(filters.Regex(r'^(💖 Мои пары|👤 Мой профиль|✨ Подбор|💬 Чаты|⚙️ Ещё)$'),cabinet))

loop=asyncio.new_event_loop(); ready=threading.Event()
async def start_bot():
    await bot.initialize(); await bot.start()
    if BASE_URL:
        kw={'url':BASE_URL+'/telegram/webhook','drop_pending_updates':False}
        if WEBHOOK_SECRET: kw['secret_token']=WEBHOOK_SECRET
        await bot.bot.set_webhook(**kw)
    ready.set()
def bot_thread(): asyncio.set_event_loop(loop); loop.run_until_complete(start_bot()); loop.run_forever()

BASE='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Совпали — админка</title><style>body{font-family:Arial;background:#f5f5f7;margin:0;color:#18181b}nav{background:#17121f;color:white;padding:14px}nav a{color:white;margin-right:18px;text-decoration:none}.w{max-width:1000px;margin:25px auto;padding:0 15px}.c{background:white;padding:18px;border-radius:14px;margin:12px 0;box-shadow:0 3px 15px #0001}input,textarea{width:100%;box-sizing:border-box;padding:11px;margin:5px 0 15px;border:1px solid #ddd;border-radius:8px}button{padding:10px 15px;background:#17121f;color:#fff;border:0;border-radius:8px}table{width:100%;background:#fff;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #eee;text-align:left}.m{font-size:30px;font-weight:700}</style>{nav}<div class="w">{body}</div></html>'''
def page(body): return BASE.format(nav=("<nav>❤️ <b>Совпали</b> &nbsp; <a href='/admin'>Главная</a><a href='/admin/users'>Пользователи</a><a href='/admin/settings'>Настройки</a><a href='/admin/logout'>Выйти</a></nav>" if session.get('a') else ''),body=body)
def need(fn):
    @wraps(fn)
    def w(*a,**k): return redirect('/admin/login') if not session.get('a') else fn(*a,**k)
    return w
@app.get('/')
def root(): return redirect('/admin')
@app.route('/admin/login',methods=['GET','POST'])
def login():
    msg=''
    if request.method=='POST':
        if request.form.get('u')==ADMIN_USER and request.form.get('p')==ADMIN_PASSWORD: session['a']=1; return redirect('/admin')
        msg='<p>Неверный логин или пароль</p>'
    return page(f"<div class='c' style='max-width:420px;margin:70px auto'><h2>Вход</h2>{msg}<form method='post'><input name='u' placeholder='Логин'><input name='p' type='password' placeholder='Пароль'><button>Войти</button></form></div>")
@app.get('/admin/logout')
def logout(): session.clear(); return redirect('/admin/login')
@app.get('/admin')
@need
def dash():
    uc=one('SELECT COUNT(*) c FROM users')['c']; pc=one('SELECT COUNT(*) c FROM profiles')['c']
    return page(f"<h1>Главная</h1><div class='c'><div>Пользователи</div><div class='m'>{uc}</div></div><div class='c'><div>Готовые анкеты</div><div class='m'>{pc}</div></div>")
@app.get('/admin/users')
@need
def users():
    rs=many('SELECT u.*,p.name,p.city,p.goal,p.priority FROM users u LEFT JOIN profiles p ON p.user_id=u.id ORDER BY u.id DESC')
    rows=''.join(f"<tr><td>{r['id']}</td><td>{html.escape(r['name'] or '—')}</td><td>{html.escape('@'+r['username'] if r['username'] else str(r['tg_id']))}</td><td>{html.escape(r['city'] or '—')}</td><td>{html.escape(r['goal'] or '—')}</td><td>{html.escape(r['priority'] or '—')}</td></tr>" for r in rs)
    return page('<h1>Пользователи</h1><table><tr><th>ID</th><th>Имя</th><th>Telegram</th><th>Город</th><th>Цель</th><th>Главное</th></tr>'+rows+'</table>')
@app.route('/admin/settings',methods=['GET','POST'])
@need
def settings():
    keys=['welcome_text','chat_url','support_username']
    if request.method=='POST':
        for k in keys: set_setting(k,request.form.get(k,'').strip())
        return redirect('/admin/settings')
    labels={'welcome_text':'Приветственный текст','chat_url':'Ссылка на городской чат','support_username':'Telegram поддержки'}; fields=''
    for k in keys:
        v=html.escape(setting(k)); fields+=f"<label>{labels[k]}</label>"+(f"<textarea name='{k}' rows='6'>{v}</textarea>" if k=='welcome_text' else f"<input name='{k}' value='{v}'>")
    return page("<h1>Настройки</h1><div class='c'><form method='post'>"+fields+"<button>Сохранить</button></form></div>")
@app.get('/health')
def health(): return {'ok':True,'bot':ready.is_set(),'version':'2.0'}
@app.post('/telegram/webhook')
def webhook():
    if WEBHOOK_SECRET and request.headers.get('X-Telegram-Bot-Api-Secret-Token','')!=WEBHOOK_SECRET: return ('forbidden',403)
    if not ready.wait(15): return ('not ready',503)
    u=Update.de_json(request.get_json(force=True),bot.bot); asyncio.run_coroutine_threadsafe(bot.process_update(u),loop); return ('ok',200)

if __name__=='__main__':
    init_db(); threading.Thread(target=bot_thread,daemon=True).start(); serve(app,host='0.0.0.0',port=PORT,threads=8)
