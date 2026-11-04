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
from visuals import visual, as_file

TOKEN=os.environ['BOT_TOKEN'].strip()
BASE_URL=os.getenv('WEBHOOK_BASE_URL','').strip().rstrip('/')
WEBHOOK_SECRET=os.getenv('WEBHOOK_SECRET','').strip()
ADMIN_USER=os.getenv('ADMIN_USERNAME','admin')
ADMIN_PASSWORD=os.environ['ADMIN_PASSWORD']
FLASK_SECRET=os.environ['FLASK_SECRET']
PORT=int(os.getenv('PORT','10000'))
DB_PATH=os.getenv('DB_PATH','/tmp/sovpali_v3.db')

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
            'welcome_text':'Мы не ищем пару по одному признаку. «Совпали» сравнивает цели отношений, жизненные ценности, город, нумерологические и базовые астрологические параметры, чтобы среди случайных знакомств показать тех, с кем совпадение действительно сильнее.'
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
    vals=(uid,d['name'],d['gender'],d['looking_for'],d['birth_date'],None,d['birth_place'],d['city'],d['goal'],d['priority'],d.get('photo'),now())
    execute('''INSERT INTO profiles(user_id,name,gender,looking_for,birth_date,birth_time,birth_place,city,goal,priority,photo_file_id,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,gender=excluded.gender,looking_for=excluded.looking_for,birth_date=excluded.birth_date,birth_time=NULL,birth_place=excluded.birth_place,city=excluded.city,goal=excluded.goal,priority=excluded.priority,photo_file_id=excluded.photo_file_id,completed_at=excluded.completed_at''',vals)

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
    # Российская версия сервиса: подбор только мужчина ↔ женщина.
    if a['gender']==b['gender']: return False
    if a['gender']=='Мужчина' and b['gender']!='Женщина': return False
    if a['gender']=='Женщина' and b['gender']!='Мужчина': return False
    return True
def score(a,b):
    # Nationwide: location is only a small positive bonus, never a requirement.
    s=25
    if a['goal']==b['goal']: s+=25
    if a['priority']==b['priority']: s+=25
    if a['city'].strip().lower()==b['city'].strip().lower(): s+=5
    try:
        za,zb=zodiac(a['birth_date']),zodiac(b['birth_date'])
        s+=12 if ELEMENT[zb] in GOOD[ELEMENT[za]] else 5
        la,lb=lifepath(a['birth_date']),lifepath(b['birth_date'])
        s+=8 if la==lb or abs(la-lb) in (1,3) else 3
    except Exception: s+=5
    return min(98,s)
def reasons(a,b):
    r=[]
    if a['goal']==b['goal']: r.append('вы хотите похожего сценария отношений')
    if a['priority']==b['priority']: r.append('совпадает главный ориентир в отношениях')
    if a['city'].strip().lower()==b['city'].strip().lower(): r.append('вы живёте в одном городе — знакомство реально продолжить офлайн')
    try:
        za,zb=zodiac(a['birth_date']),zodiac(b['birth_date'])
        if ELEMENT[zb] in GOOD[ELEMENT[za]]: r.append('базовые астрологические элементы хорошо сочетаются')
        if lifepath(a['birth_date'])==lifepath(b['birth_date']): r.append('совпадает нумерологический ритм')
    except Exception: pass
    return r[:3] or ['система видит несколько совместимых параметров профиля']

MENU=ReplyKeyboardMarkup([
    [KeyboardButton('💖 Мои пары'),KeyboardButton('👤 Мой профиль')],
    [KeyboardButton('✨ Подбор'),KeyboardButton('💬 Чаты')],
    [KeyboardButton('⚙️ Ещё')]
],resize_keyboard=True,is_persistent=True)
def ik(rows): return InlineKeyboardMarkup([[InlineKeyboardButton(t,callback_data=d) for t,d in row] for row in rows])

async def send_card(message,theme,caption,reply_markup=None):
    try:
        await message.reply_photo(as_file(visual(theme),f'{theme}.jpg'),caption=caption,parse_mode=ParseMode.HTML,reply_markup=reply_markup)
    except Exception as e:
        print(f'[visual] {theme}: {e}',flush=True)
        await message.reply_text(caption,parse_mode=ParseMode.HTML,reply_markup=reply_markup)

AGE,GENDER,BIRTH,BIRTH_PLACE,CITY,GOAL,PRIORITY,PHOTO=range(8)

async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    u=upsert_user(update.effective_user)
    if u['is_banned']:
        await update.effective_message.reply_text('Профиль временно недоступен.'); return ConversationHandler.END
    p=profile(u['id'])
    if p:
        await send_card(update.effective_message,'welcome',f"✨ <b>С возвращением в «Совпали»</b>\n\n{html.escape(p['name'])}, твой профиль готов. Открой «Мои пары» или запусти новый подбор.",MENU)
        return ConversationHandler.END
    ctx.user_data['p']={'name':update.effective_user.first_name or 'Пользователь'}
    text=("✨ <b>Совпали</b>\n\n"+html.escape(setting('welcome_text'))+
          "\n\nТебе не придётся заполнять длинную анкету. Всего несколько коротких ответов — и каждый нужен для конкретной части подбора.\n\n<b>Тебе уже исполнилось 18 лет?</b>")
    await send_card(update.effective_message,'welcome',text,ik([[('Да, мне 18+','age:y')],[('Нет','age:n')]]))
    return AGE

async def age(update,ctx):
    q=update.callback_query; await q.answer()
    if q.data=='age:n':
        await q.message.reply_text('Сервис доступен только пользователям 18+.'); return ConversationHandler.END
    await send_card(q.message,'gender','👤 <b>Шаг 1 из 6</b>\n\n<b>Ты мужчина или женщина?</b>\n\nЭто нужно, чтобы сразу сформировать корректный круг потенциальных пар и не тратить твоё время на неподходящие анкеты.',ik([[('Мужчина','g:Мужчина'),('Женщина','g:Женщина')]]))
    return GENDER

async def gender(update,ctx):
    q=update.callback_query; await q.answer()
    gender=q.data[2:]
    ctx.user_data['p']['gender']=gender
    ctx.user_data['p']['looking_for']='Женщину' if gender=='Мужчина' else 'Мужчину'
    await send_card(q.message,'birth','✨ <b>Шаг 2 из 6</b>\n\n<b>Напиши дату рождения</b> в формате ДД.ММ.ГГГГ.\nНапример: 05.01.1990\n\nПочему спрашиваем: дата рождения добавляет в подбор нумерологический ритм и базовые астрологические параметры. Это ещё один слой совместимости поверх обычных анкет.')
    return BIRTH

async def birth(update,ctx):
    s=update.message.text.strip()
    try:
        d=datetime.strptime(s,'%d.%m.%Y'); t=datetime.now(); a=t.year-d.year-((t.month,t.day)<(d.month,d.day))
        if not 18<=a<=100: raise ValueError
    except Exception:
        await update.message.reply_text('Напиши дату в формате ДД.ММ.ГГГГ, например 05.01.1990'); return BIRTH
    ctx.user_data['p']['birth_date']=s
    await send_card(update.message,'place','📍 <b>Шаг 3 из 6</b>\n\n<b>В каком городе ты родился?</b>\n\nМы сохраняем место рождения для более глубокого астрологического профиля и расширенного анализа натальной карты. Точное время рождения сейчас не спрашиваем — его можно будет добавить позже, если понадобится.')
    return BIRTH_PLACE

async def birth_place(update,ctx):
    ctx.user_data['p']['birth_place']=update.message.text.strip()[:90]
    await send_card(update.message,'city','🌆 <b>Шаг 4 из 6</b>\n\n<b>В каком городе ты живёшь сейчас?</b>\n\nСовместимость должна работать не только на бумаге. Город помогает показывать людей, с которыми реально можно встретиться и продолжить знакомство офлайн.')
    return CITY

async def city(update,ctx):
    ctx.user_data['p']['city']=update.message.text.strip()[:90]
    await send_card(update.message,'goal','❤️ <b>Шаг 5 из 6</b>\n\n<b>Какие отношения тебе нужны сейчас?</b>\n\nДаже очень похожие люди не совпадут, если один ищет семью, а второй — только лёгкое общение. Поэтому сначала синхронизируем намерения.',ik([[('Серьёзные отношения','goal:Серьёзные отношения')],[('Любовь и семья','goal:Любовь и семья')],[('Общение и знакомство','goal:Общение и знакомство')],[('Пока присматриваюсь','goal:Пока присматриваюсь')]]))
    return GOAL

async def goal(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['p']['goal']=q.data.split(':',1)[1]
    await send_card(q.message,'priority','💎 <b>Шаг 6 из 6</b>\n\n<b>Что для тебя важнее всего в отношениях?</b>\n\nЭто один из самых сильных фильтров. Система должна понять, на чём вы двое обязаны совпасть в первую очередь: семья, чувства, ценности, страсть или надёжная опора.',ik([[('👨‍👩‍👧 Семья','prio:Семья'),('❤️ Любовь','prio:Любовь')],[('🧭 Общие ценности','prio:Ценности'),('🔥 Страсть','prio:Страсть')],[('🤝 Спокойствие и опора','prio:Опора')]]))
    return PRIORITY

async def priority(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['p']['priority']=q.data.split(':',1)[1]
    await send_card(q.message,'photo','📸 <b>Последний штрих</b>\n\nМожешь добавить одну фотографию. Она <b>не влияет на расчёт совместимости</b>, но помогает сильному совпадению превратиться в настоящее знакомство.\n\nЕсли не хочешь сейчас — просто пропусти.',ik([[('Пропустить пока','photo:skip')]]))
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
    await send_card(message,'matching','✨ <b>Профиль готов</b>\n\nТеперь «Совпали» сравнивает не один признак, а сразу несколько слоёв: намерение, главный ориентир в отношениях, город, нумерологию и базовую астрологическую совместимость.\n\nОткрой <b>«Мои пары»</b> в нижнем меню.',MENU)
    return ConversationHandler.END

async def pairs_view(message,u,p,show_intro=False):
    if show_intro:
        await send_card(message,'matching','✨ <b>Ищу сильные совпадения</b>\n\nСначала отсеиваю неподходящие анкеты по полу и цели отношений, затем сравниваю ценности, город, нумерологические и базовые астрологические параметры.')
    cs=many('SELECT p.*,u.username,u.tg_id FROM profiles p JOIN users u ON u.id=p.user_id WHERE p.user_id<>? AND u.is_banned=0',(u['id'],))
    found=sorted([(score(p,c),c) for c in cs if eligible(p,c)],key=lambda x:x[0],reverse=True)[:3]
    if not found:
        await send_card(message,'pairs','💖 <b>Твои пары</b>\n\nПока недостаточно подходящих анкет для качественного результата. Как только появятся совместимые люди противоположного пола, лучшие совпадения будут здесь.',MENU)
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
        cap=(f"👤 <b>{html.escape(p['name'])}</b>\n\n"
             f"Город: {html.escape(p['city'])}\n"
             f"Ищу: {html.escape(p['looking_for'])}\n"
             f"Цель: {html.escape(p['goal'])}\n"
             f"Главное: {html.escape(p['priority'])}\n"
             f"Дата рождения: {html.escape(p['birth_date'])}\n"
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
        await q.message.reply_text('«Совпали» сначала учитывает пол и цель знакомства, затем сравнивает жизненный приоритет, город, дату рождения, нумерологические и базовые астрологические параметры. Это инструмент подбора и ориентир для знакомства, а не гарантия отношений.',reply_markup=MENU); return
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
        BIRTH:[MessageHandler(filters.TEXT & ~filters.COMMAND,birth)],
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
def health(): return {'ok':True,'bot':ready.is_set(),'version':'3.0'}
@app.post('/telegram/webhook')
def webhook():
    if WEBHOOK_SECRET and request.headers.get('X-Telegram-Bot-Api-Secret-Token','')!=WEBHOOK_SECRET: return ('forbidden',403)
    if not ready.wait(15): return ('not ready',503)
    u=Update.de_json(request.get_json(force=True),bot.bot); asyncio.run_coroutine_threadsafe(bot.process_update(u),loop); return ('ok',200)

if __name__=='__main__':
    init_db(); threading.Thread(target=bot_thread,daemon=True).start(); serve(app,host='0.0.0.0',port=PORT,threads=8)
