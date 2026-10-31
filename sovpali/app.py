from __future__ import annotations
import asyncio, html, os, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime
from functools import wraps

from flask import Flask, redirect, request, session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from waitress import serve

TOKEN = os.environ["BOT_TOKEN"].strip()
BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "/tmp/sovpali.db")

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET"]

@contextmanager
def db():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,tg_id INTEGER UNIQUE NOT NULL,username TEXT,first_name TEXT,is_banned INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,last_seen_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS profiles(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,gender TEXT NOT NULL,looking_for TEXT NOT NULL,birth_date TEXT NOT NULL,city TEXT NOT NULL,goal TEXT NOT NULL,family_priority INTEGER NOT NULL,love_priority INTEGER NOT NULL,sex_priority INTEGER NOT NULL,values_priority INTEGER NOT NULL,about TEXT NOT NULL,photo_file_id TEXT,contact_consent INTEGER NOT NULL DEFAULT 1,completed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,buyer_user_id INTEGER NOT NULL,candidate_user_id INTEGER NOT NULL,amount INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        defaults={"project_name":"Совпали","contact_price":"100","premium_price":"1200","payment_url":"","chat_url":"","welcome_text":"Подбираем людей по целям, ценностям и совместимости анкеты."}
        for k,v in defaults.items(): c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))

def now(): return datetime.now().isoformat(timespec="seconds")
def one(sql,p=()):
    with db() as c: return c.execute(sql,p).fetchone()
def many(sql,p=()):
    with db() as c: return c.execute(sql,p).fetchall()
def execute(sql,p=()):
    with db() as c: c.execute(sql,p)
def setting(k,default=""):
    r=one("SELECT value FROM settings WHERE key=?",(k,)); return r["value"] if r else default
def set_setting(k,v): execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,v))
def upsert_user(tg):
    t=now()
    with db() as c:
        c.execute("""INSERT INTO users(tg_id,username,first_name,created_at,last_seen_at) VALUES(?,?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_seen_at=excluded.last_seen_at""",(tg.id,tg.username,tg.first_name,t,t))
        return c.execute("SELECT * FROM users WHERE tg_id=?",(tg.id,)).fetchone()
def profile(uid): return one("SELECT * FROM profiles WHERE user_id=?",(uid,))
def user(uid): return one("SELECT * FROM users WHERE id=?",(uid,))
def save_profile(uid,d):
    vals=(uid,d["name"],d["gender"],d["looking_for"],d["birth_date"],d["city"],d["goal"],d["family"],d["love"],d["sex"],d["values"],d["about"],d.get("photo"),1,now())
    execute("""INSERT INTO profiles(user_id,name,gender,looking_for,birth_date,city,goal,family_priority,love_priority,sex_priority,values_priority,about,photo_file_id,contact_consent,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,gender=excluded.gender,looking_for=excluded.looking_for,birth_date=excluded.birth_date,city=excluded.city,goal=excluded.goal,family_priority=excluded.family_priority,love_priority=excluded.love_priority,sex_priority=excluded.sex_priority,values_priority=excluded.values_priority,about=excluded.about,photo_file_id=excluded.photo_file_id,contact_consent=1,completed_at=excluded.completed_at""",vals)
def eligible(a,b):
    if a["looking_for"]=="Мужчину" and b["gender"]!="Мужчина": return False
    if a["looking_for"]=="Женщину" and b["gender"]!="Женщина": return False
    if b["looking_for"]=="Мужчину" and a["gender"]!="Мужчина": return False
    if b["looking_for"]=="Женщину" and a["gender"]!="Женщина": return False
    return True
def match_score(a,b):
    s=30 if a["goal"]==b["goal"] else 12
    for f in ("family_priority","love_priority","sex_priority","values_priority"): s+=max(0,12-abs(int(a[f])-int(b[f]))*3)
    if a["city"].strip().lower()==b["city"].strip().lower(): s+=18
    return min(99,s)
def kb(rows): return InlineKeyboardMarkup([[InlineKeyboardButton(t,callback_data=d) for t,d in row] for row in rows])
def main_menu():
    markup=[[InlineKeyboardButton("💘 Найти пару",callback_data="menu:find")],[InlineKeyboardButton("👤 Моя анкета",callback_data="menu:profile"),InlineKeyboardButton("✏️ Заполнить заново",callback_data="menu:reset")]]
    chat=setting("chat_url").strip()
    if chat: markup.append([InlineKeyboardButton("💬 Войти в городской чат",url=chat)])
    markup.append([InlineKeyboardButton("ℹ️ Как это работает",callback_data="menu:about")]); return InlineKeyboardMarkup(markup)

AGE,NAME,GENDER,LOOKING,BIRTH,CITY,GOAL,FAMILY,LOVE,SEX,VALUES,ABOUT,PHOTO,CONSENT=range(14)
async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    u=upsert_user(update.effective_user)
    if u["is_banned"]: await update.effective_message.reply_text("Ваш профиль заблокирован."); return ConversationHandler.END
    if profile(u["id"]): await update.effective_message.reply_text("❤️ <b>Совпали</b>\n\nВыберите действие:",parse_mode=ParseMode.HTML,reply_markup=main_menu()); return ConversationHandler.END
    ctx.user_data["p"]={}
    await update.effective_message.reply_text("❤️ <b>Совпали</b>\n\n"+html.escape(setting("welcome_text"))+"\n\nСервис только 18+. Вам уже исполнилось 18 лет?",parse_mode=ParseMode.HTML,reply_markup=kb([[("Да, мне 18+","age:y")],[("Нет","age:n")]])); return AGE
async def age(update,ctx):
    q=update.callback_query; await q.answer()
    if q.data=="age:n": await q.edit_message_text("Сервис доступен только пользователям 18+."); return ConversationHandler.END
    await q.edit_message_text("Как вас зовут?"); return NAME
async def name(update,ctx):
    ctx.user_data["p"]["name"]=update.message.text.strip()[:60]; await update.message.reply_text("Ваш пол?",reply_markup=kb([[("Мужчина","g:Мужчина"),("Женщина","g:Женщина")]])); return GENDER
async def gender(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data["p"]["gender"]=q.data[2:]; await q.edit_message_text("Кого хотите найти?",reply_markup=kb([[("Мужчину","l:Мужчину"),("Женщину","l:Женщину")],[("Неважно","l:Неважно")]])); return LOOKING
async def looking(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data["p"]["looking_for"]=q.data[2:]; await q.edit_message_text("Дата рождения? Например: 05.01.1990"); return BIRTH
async def birth(update,ctx):
    s=update.message.text.strip()
    try:
        d=datetime.strptime(s,"%d.%m.%Y"); t=datetime.now(); a=t.year-d.year-((t.month,t.day)<(d.month,d.day))
        if not 18<=a<=100: raise ValueError
    except: await update.message.reply_text("Введите дату, например 05.01.1990"); return BIRTH
    ctx.user_data["p"]["birth_date"]=s; await update.message.reply_text("В каком городе вы живёте?"); return CITY
async def city(update,ctx):
    ctx.user_data["p"]["city"]=update.message.text.strip()[:80]; await update.message.reply_text("Что вы ищете?",reply_markup=kb([[("Серьёзные отношения","goal:Серьёзные отношения")],[("Общение и знакомства","goal:Общение и знакомства")],[("Пока не определился(ась)","goal:Пока не определился(ась)")]])); return GOAL
async def goal(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data["p"]["goal"]=q.data.split(":",1)[1]; await q.edit_message_text("Насколько важна семья? 1 — не очень, 5 — очень.",reply_markup=kb([[(str(i),f"family:{i}") for i in range(1,6)]])); return FAMILY
async def scale(update,ctx,key,next_state,text,prefix):
    q=update.callback_query; await q.answer(); ctx.user_data["p"][key]=int(q.data.split(":")[1]); await q.edit_message_text(text,reply_markup=kb([[(str(i),f"{prefix}:{i}") for i in range(1,6)]])); return next_state
async def family(update,ctx): return await scale(update,ctx,"family",LOVE,"Насколько важны любовь и эмоциональная близость?","love")
async def love(update,ctx): return await scale(update,ctx,"love",SEX,"Насколько важна сексуальная совместимость?","sex")
async def sex(update,ctx): return await scale(update,ctx,"sex",VALUES,"Насколько важны общие ценности?","values")
async def values(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data["p"]["values"]=int(q.data.split(":")[1]); await q.edit_message_text("Коротко расскажите о себе — 1–3 предложения."); return ABOUT
async def about(update,ctx):
    ctx.user_data["p"]["about"]=update.message.text.strip()[:500]; await update.message.reply_text("Пришлите одно фото или нажмите «Без фото».",reply_markup=kb([[("Без фото","photo:skip")]])); return PHOTO
async def photo(update,ctx):
    if update.message and update.message.photo:
        ctx.user_data["p"]["photo"]=update.message.photo[-1].file_id; await update.message.reply_text("Разрешаете открыть ваш Telegram-контакт пользователю, который выбрал вашу анкету и оплатил контакт?",reply_markup=kb([[("Да","consent:y")],[("Нет","consent:n")]])); return CONSENT
    return PHOTO
async def photo_skip(update,ctx):
    q=update.callback_query; await q.answer(); ctx.user_data["p"]["photo"]=None; await q.edit_message_text("Разрешаете открыть ваш Telegram-контакт пользователю, который выбрал вашу анкету и оплатил контакт?",reply_markup=kb([[("Да","consent:y")],[("Нет","consent:n")]])); return CONSENT
async def consent(update,ctx):
    q=update.callback_query; await q.answer()
    if q.data=="consent:n": await q.edit_message_text("Без согласия анкета не участвует в подборе. Нажмите /start, если передумаете."); return ConversationHandler.END
    u=upsert_user(update.effective_user); save_profile(u["id"],ctx.user_data["p"]); await q.edit_message_text("✅ Анкета готова!",reply_markup=main_menu()); return ConversationHandler.END
async def menu_handler(update,ctx):
    q=update.callback_query; await q.answer(); u=upsert_user(update.effective_user); p=profile(u["id"])
    if not p: await q.edit_message_text("Сначала заполните анкету: /start"); return
    a=q.data.split(":",1)[1]
    if a=="profile": await q.edit_message_text(f"👤 <b>{html.escape(p['name'])}</b>\nГород: {html.escape(p['city'])}\nИщу: {html.escape(p['looking_for'])}\nЦель: {html.escape(p['goal'])}\n\n{html.escape(p['about'])}",parse_mode=ParseMode.HTML,reply_markup=main_menu())
    elif a=="reset": execute("DELETE FROM profiles WHERE user_id=?",(u["id"],)); await q.edit_message_text("Анкета удалена. Нажмите /start.")
    elif a=="about": await q.edit_message_text("Подбор сравнивает цель знакомства, город и ваши приоритеты. Процент — ориентир для знакомства, а не гарантия отношений.",reply_markup=main_menu())
    elif a=="find":
        cs=many("SELECT p.*,u.username,u.tg_id FROM profiles p JOIN users u ON u.id=p.user_id WHERE p.user_id<>? AND u.is_banned=0",(u["id"],)); found=sorted([(match_score(p,c),c) for c in cs if eligible(p,c)],reverse=True,key=lambda x:x[0])[:3]
        if not found: await q.edit_message_text("Пока подходящих анкет нет. Для теста зарегистрируйте вторую анкету с другого Telegram-аккаунта.",reply_markup=main_menu()); return
        rows=[]; lines=["💘 <b>Лучшие совпадения:</b>",""]
        for i,(s,c) in enumerate(found,1): lines.append(f"{i}. <b>{html.escape(c['name'])}</b> — {s}%"); rows.append([(f"{i}. {c['name']} — {s}%",f"cand:{c['user_id']}:{s}")])
        await q.edit_message_text("\n".join(lines),parse_mode=ParseMode.HTML,reply_markup=kb(rows))
async def candidate(update,ctx):
    q=update.callback_query; await q.answer(); _,cid,s=q.data.split(":"); c=profile(int(cid))
    if not c: return
    price=int(setting("contact_price","100")); text=f"💘 <b>{html.escape(c['name'])}</b> — {s}%\nГород: {html.escape(c['city'])}\nЦель: {html.escape(c['goal'])}\n\n{html.escape(c['about'])}"; buttons=kb([[(f"🔓 Открыть контакт — {price} ₽",f"buy:{cid}")]])
    if c["photo_file_id"]: await q.message.reply_photo(c["photo_file_id"],caption=text,parse_mode=ParseMode.HTML,reply_markup=buttons)
    else: await q.message.reply_text(text,parse_mode=ParseMode.HTML,reply_markup=buttons)
async def buy(update,ctx):
    q=update.callback_query; await q.answer(); cid=int(q.data.split(":")[1]); u=upsert_user(update.effective_user); paid=one("SELECT * FROM payments WHERE buyer_user_id=? AND candidate_user_id=? AND status='paid' ORDER BY id DESC LIMIT 1",(u["id"],cid))
    if paid: return await send_contact(update.effective_chat.id,cid,ctx)
    price=int(setting("contact_price","100")); url=setting("payment_url").strip()
    if not url: await q.message.reply_text("Оплата пока не подключена. Её можно добавить в админке."); return
    execute("INSERT INTO payments(buyer_user_id,candidate_user_id,amount,status,created_at) VALUES(?,?,?,'submitted',?)",(u["id"],cid,price,now())); await q.message.reply_text(f"Стоимость контакта: <b>{price} ₽</b>.\nОплатите по кнопке и нажмите «Я оплатил».",parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Оплатить",url=url)],[InlineKeyboardButton("✅ Я оплатил",callback_data=f"paid:{cid}")]]))
async def paid(update,ctx):
    q=update.callback_query; await q.answer(); await q.message.reply_text("✅ Заявка на оплату отмечена. Администратор подтвердит её в панели.")
async def send_contact(chat_id,cid,ctx):
    u=user(cid); p=profile(cid)
    if not u or not p: return
    contact="@"+u["username"] if u["username"] else f'<a href="tg://user?id={u["tg_id"]}">Открыть Telegram-профиль</a>'; await ctx.bot.send_message(chat_id,f"🔓 <b>Контакт открыт</b>\n\n{html.escape(p['name'])}: {contact}",parse_mode=ParseMode.HTML)

bot=Application.builder().token(TOKEN).build()
conv=ConversationHandler(entry_points=[CommandHandler("start",start)],states={AGE:[CallbackQueryHandler(age,pattern=r"^age:")],NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND,name)],GENDER:[CallbackQueryHandler(gender,pattern=r"^g:")],LOOKING:[CallbackQueryHandler(looking,pattern=r"^l:")],BIRTH:[MessageHandler(filters.TEXT & ~filters.COMMAND,birth)],CITY:[MessageHandler(filters.TEXT & ~filters.COMMAND,city)],GOAL:[CallbackQueryHandler(goal,pattern=r"^goal:")],FAMILY:[CallbackQueryHandler(family,pattern=r"^family:")],LOVE:[CallbackQueryHandler(love,pattern=r"^love:")],SEX:[CallbackQueryHandler(sex,pattern=r"^sex:")],VALUES:[CallbackQueryHandler(values,pattern=r"^values:")],ABOUT:[MessageHandler(filters.TEXT & ~filters.COMMAND,about)],PHOTO:[MessageHandler(filters.PHOTO,photo),CallbackQueryHandler(photo_skip,pattern=r"^photo:skip$")],CONSENT:[CallbackQueryHandler(consent,pattern=r"^consent:")]},fallbacks=[CommandHandler("start",start)],allow_reentry=True)
bot.add_handler(conv); bot.add_handler(CallbackQueryHandler(menu_handler,pattern=r"^menu:")); bot.add_handler(CallbackQueryHandler(candidate,pattern=r"^cand:")); bot.add_handler(CallbackQueryHandler(buy,pattern=r"^buy:")); bot.add_handler(CallbackQueryHandler(paid,pattern=r"^paid:"))
loop=asyncio.new_event_loop(); ready=threading.Event()
async def start_bot():
    await bot.initialize(); await bot.start()
    if BASE_URL:
        kw={"url":BASE_URL+"/telegram/webhook","drop_pending_updates":False}
        if WEBHOOK_SECRET: kw["secret_token"]=WEBHOOK_SECRET
        await bot.bot.set_webhook(**kw)
    ready.set()
def bot_thread(): asyncio.set_event_loop(loop); loop.run_until_complete(start_bot()); loop.run_forever()

BASE="""<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Совпали — админка</title><style>body{font-family:Arial;background:#f5f5f7;margin:0}nav{background:#111;color:white;padding:14px}nav a{color:white;margin-right:18px}.w{max-width:1000px;margin:25px auto;padding:0 15px}.c{background:white;padding:18px;border-radius:12px;margin:12px 0}input,textarea{width:100%;box-sizing:border-box;padding:10px;margin:5px 0 15px}button{padding:10px 15px;background:#111;color:#fff;border:0;border-radius:8px}table{width:100%;background:#fff;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #eee;text-align:left}</style>{nav}<div class=w>{body}</div>"""
def page(body): return BASE.format(nav=("<nav>❤️ Совпали &nbsp; <a href=/admin>Главная</a><a href=/admin/users>Пользователи</a><a href=/admin/settings>Настройки</a><a href=/admin/logout>Выйти</a></nav>" if session.get("a") else ""),body=body)
def need(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get("a"): return redirect("/admin/login")
        return fn(*a,**k)
    return w
@app.get("/")
def root(): return redirect("/admin")
@app.route("/admin/login",methods=["GET","POST"])
def login():
    msg=""
    if request.method=="POST":
        if request.form.get("u")==ADMIN_USER and request.form.get("p")==ADMIN_PASSWORD: session["a"]=1; return redirect("/admin")
        msg="<p>Неверный логин или пароль</p>"
    return page(f"<div class=c style='max-width:400px;margin:70px auto'><h2>Вход</h2>{msg}<form method=post><input name=u placeholder=Логин><input name=p type=password placeholder=Пароль><button>Войти</button></form></div>")
@app.get("/admin/logout")
def logout(): session.clear(); return redirect("/admin/login")
@app.get("/admin")
@need
def dash():
    uc=one("SELECT COUNT(*) c FROM users")["c"]; pc=one("SELECT COUNT(*) c FROM profiles")["c"]; pay=one("SELECT COUNT(*) c FROM payments")["c"]; return page(f"<h1>Главная</h1><div class=c><h2>Пользователи: {uc}</h2><h2>Анкеты: {pc}</h2><h2>Заявки на оплату: {pay}</h2></div>")
@app.get("/admin/users")
@need
def users():
    rs=many("SELECT u.*,p.name,p.city FROM users u LEFT JOIN profiles p ON p.user_id=u.id ORDER BY u.id DESC"); rows="".join(f"<tr><td>{r['id']}</td><td>{html.escape(r['name'] or '—')}</td><td>{html.escape('@'+r['username'] if r['username'] else str(r['tg_id']))}</td><td>{html.escape(r['city'] or '—')}</td></tr>" for r in rs); return page("<h1>Пользователи</h1><table><tr><th>ID</th><th>Имя</th><th>Telegram</th><th>Город</th></tr>"+rows+"</table>")
@app.route("/admin/settings",methods=["GET","POST"])
@need
def settings():
    keys=["contact_price","premium_price","payment_url","chat_url","welcome_text"]
    if request.method=="POST":
        for k in keys: set_setting(k,request.form.get(k,"").strip())
        return redirect("/admin/settings")
    labels={"contact_price":"Цена контакта, ₽","premium_price":"Premium, ₽","payment_url":"Платёжная ссылка","chat_url":"Ссылка на городской чат","welcome_text":"Приветственный текст"}; fields=""
    for k in keys:
        v=html.escape(setting(k)); fields+=f"<label>{labels[k]}</label>"+(f"<textarea name={k}>{v}</textarea>" if k=="welcome_text" else f"<input name={k} value='{v}'>")
    return page("<h1>Настройки</h1><div class=c><form method=post>"+fields+"<button>Сохранить</button></form></div>")
@app.get("/health")
def health(): return {"ok":True,"bot":ready.is_set(),"db":"sqlite-test"}
@app.post("/telegram/webhook")
def webhook():
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token","")!=WEBHOOK_SECRET: return ("forbidden",403)
    if not ready.wait(15): return ("not ready",503)
    u=Update.de_json(request.get_json(force=True),bot.bot); asyncio.run_coroutine_threadsafe(bot.process_update(u),loop); return ("ok",200)
if __name__=="__main__": init_db(); threading.Thread(target=bot_thread,daemon=True).start(); serve(app,host="0.0.0.0",port=PORT,threads=8)
