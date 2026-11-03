"""Persistent offer dedupe and saved coach questionnaire.

Only sends an upsell AFTER accepted contact access. All optional sends fail
closed without impacting contact delivery. No user chats or third-party PII
are stored by the demo.
"""
import asyncio
import json
import threading
from datetime import datetime, timezone
from telegram import InlineKeyboardMarkup,InlineKeyboardButton
from coach_web import coach_link, _approved_pair

class CoachOffers:
    def __init__(self,ns):
        self.ns=ns
        self.ready=False
        self.lock=threading.Lock()
    def call(self,name,*args):
        return self.ns[name](*args)
    def now(self):
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    def init(self):
        if self.ready:return
        with self.lock:
            if self.ready:return
            with self.call("db") as conn:
                if self.ns["USE_POSTGRES"]:
                    conn.executescript("""
                      CREATE TABLE IF NOT EXISTS coach_offer_sends(
                        buyer_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        candidate_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        status TEXT NOT NULL DEFAULT 'reserved',
                        sent_at TEXT,
                        PRIMARY KEY(buyer_user_id,candidate_user_id)
                      );
                      CREATE TABLE IF NOT EXISTS coach_quizzes(
                        buyer_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        candidate_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        answers_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(buyer_user_id,candidate_user_id)
                      );
                    """)
                else:
                    conn.executescript("""
                      CREATE TABLE IF NOT EXISTS coach_offer_sends(
                        buyer_user_id INTEGER NOT NULL,
                        candidate_user_id INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'reserved',
                        sent_at TEXT,
                        PRIMARY KEY(buyer_user_id,candidate_user_id)
                      );
                      CREATE TABLE IF NOT EXISTS coach_quizzes(
                        buyer_user_id INTEGER NOT NULL,
                        candidate_user_id INTEGER NOT NULL,
                        answers_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(buyer_user_id,candidate_user_id)
                      );
                    """)
            self.ready=True
    def save(self,viewer,candidate,answers):
        self.init()
        self.call("execute","""INSERT INTO coach_quizzes(
          buyer_user_id,candidate_user_id,answers_json,updated_at) VALUES(?,?,?,?)
          ON CONFLICT(buyer_user_id,candidate_user_id)
          DO UPDATE SET answers_json=excluded.answers_json,updated_at=excluded.updated_at""",
          (int(viewer),int(candidate),json.dumps(answers,ensure_ascii=False),self.now()))

    def load(self,viewer,candidate):
        self.init()
        row=self.call("one","""SELECT answers_json FROM coach_quizzes
            WHERE buyer_user_id=? AND candidate_user_id=?""",(int(viewer),int(candidate)))
        if not row:return None
        try:
            answers=json.loads(row["answers_json"])
            return answers if isinstance(answers,dict) else None
        except (ValueError,TypeError):return None

    async def offer(self,bot,viewer,candidate):
        uid,cid=int(viewer),int(candidate)
        if uid==cid:return False
        self.init()
        if not _approved_pair(uid,cid,self.ns):
            print("[coach] upsell suppressed: pair not approved",flush=True)
            return False
        try:
            opt=self.call("one","SELECT promo_enabled FROM lifecycle_prefs WHERE user_id=?",(uid,))
            if opt and int(opt["promo_enabled"] or 0)==0:return False
        except Exception:pass
        target=self.call("profile",cid)
        u=self.call("user",uid)
        if not target or not u or int(u["is_banned"] or 0):return False
        base=self.ns.get("PAIR_WEB_BASE_URL","")
        link=coach_link(base,uid,cid,self.ns["FLASK_SECRET"])
        if not link:return False
        # A reserved primary key ensures one delivery per disclosed contact.
        try:
            with self.call("db") as conn:
                inserted=conn.execute("""INSERT INTO coach_offer_sends(
                  buyer_user_id,candidate_user_id,status) VALUES(?,?,'reserved')
                  ON CONFLICT(buyer_user_id,candidate_user_id) DO NOTHING
                  RETURNING buyer_user_id""",(uid,cid)).fetchone()
            if not inserted:return False
        except Exception as exc:
            print("[coach] offer dedupe "+type(exc).__name__,flush=True)
            return False
        import html
        name=html.escape(str(target["name"])[:90])
        text=(f"💌 <b>Не спеши писать {name} первое сообщение.</b>\n\n"
              "Мы уже сравнили ваши анкеты: цели знакомства, ценности и "
              "символические астрологические и нумерологические показатели. "
              "Это не чтение мыслей и не гарантия результата — но мы можем "
              "помочь начать разговор деликатно и по делу.\n\n"
              "✨ Ответь всего на <b>три вопроса</b>, и конструктор "
              "<b>бесплатно</b> подготовит первое сообщение лично для "
              f"{name}. Скопируй его и отправь в Telegram.\n\n"
              "Когда придёт реальный ответ, вернись сюда: "
              "сервис предложит помощь с продолжением переписки "
              "за <b>900 ₽</b>. Пока платная функция не подключена.")
        kb=InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Получить первое сообщение бесплатно",url=link)
        ]])
        try:
            await bot.send_message(u["tg_id"],text,parse_mode="HTML",
                                   reply_markup=kb,disable_web_page_preview=True)
            self.call("execute","""UPDATE coach_offer_sends SET status='sent',sent_at=?
               WHERE buyer_user_id=? AND candidate_user_id=? AND status='reserved'""",
               (self.now(),uid,cid))
            print("[coach] post-contact invitation delivered",flush=True)
            return True
        except Exception as exc:
            # Don't retry automatically; sending may have succeeded before a
            # connection error. Avoid duplicate post-contact messages.
            self.call("execute","""UPDATE coach_offer_sends SET status='uncertain'
               WHERE buyer_user_id=? AND candidate_user_id=?""",(uid,cid))
            print("[coach] delivery uncertain "+type(exc).__name__,flush=True)
            return False
