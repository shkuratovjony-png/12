"""Single, truthful conversion reminder after an engaged compatibility view.

A visit alone never triggers a message. The frontend asks to register engagement
after the person scrolls into the detailed compatibility section. Thirty minutes
later, if no request/checkout/payment has started, one optional Telegram
reminder links directly to a compact checkout screen (not a second long report).

No fabricated 30-minute expiry, contact unlock, order, or artificial reservation.
"""
import asyncio
import html
import threading
from datetime import datetime, timedelta, timezone

class PairConversion:
    def __init__(self, ns):
        self.ns=ns
        self.ready=False
        self.db_lock=threading.Lock()

    def fn(self, key, *args, **kwargs):
        return self.ns[key](*args,**kwargs)

    @staticmethod
    def timestamp(dt=None):
        if dt is None:dt=datetime.now(timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    def now(self):
        return datetime.now(timezone.utc)

    def ensure(self):
        if self.ready:return
        with self.db_lock:
            if self.ready:return
            with self.fn("db") as db:
                if self.ns["USE_POSTGRES"]:
                    db.executescript("""
                    CREATE TABLE IF NOT EXISTS pair_read_followups(
                        viewer_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        candidate_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        engaged_at TEXT NOT NULL,
                        due_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        sent_at TEXT,
                        PRIMARY KEY(viewer_user_id,candidate_user_id)
                    );
                    """)
                else:
                    db.executescript("""
                    CREATE TABLE IF NOT EXISTS pair_read_followups(
                        viewer_user_id INTEGER NOT NULL,
                        candidate_user_id INTEGER NOT NULL,
                        engaged_at TEXT NOT NULL,
                        due_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        sent_at TEXT,
                        PRIMARY KEY(viewer_user_id,candidate_user_id)
                    );
                    """)
                db.executescript("""
                CREATE INDEX IF NOT EXISTS idx_pair_followups_due
                    ON pair_read_followups(status,due_at);
                CREATE INDEX IF NOT EXISTS idx_pair_followups_daily
                    ON pair_read_followups(viewer_user_id,status,sent_at);
                """)
            self.ready=True

    def optout(self, uid):
        try:
            result=self.fn("one","SELECT promo_enabled FROM lifecycle_prefs WHERE user_id=?",(int(uid),))
            return bool(result and int(result["promo_enabled"] or 0)==0)
        except Exception:return False

    def already_started(self,uid,cid):
        """Suppress upsells when a contact request, reservation, or payment exists."""
        uid,cid=int(uid),int(cid)
        lo,hi=sorted((uid,cid))
        try:
            if self.fn("one","""SELECT 1 FROM communication_requests
                WHERE requester_user_id=? AND target_user_id=?
                AND status IN ('pending','accepted') LIMIT 1""",(uid,cid)):
                return True
        except Exception:pass
        try:
            if self.fn("one","""SELECT 1 FROM intro_orders
                WHERE pair_low=? AND pair_high=?
                  AND status IN ('reserved','payment_pending','paid','awaiting_response','accepted')
                LIMIT 1""",(lo,hi)):
                return True
        except Exception:pass
        try:
            if self.fn("one","""SELECT 1 FROM match_offers
                WHERE pair_low=? AND pair_high=?
                  AND status IN ('interested','accepted')
                LIMIT 1""",(lo,hi)):
                return True
        except Exception:pass
        return False

    def record(self,uid,cid):
        self.ensure()
        uid,cid=int(uid),int(cid)
        if uid==cid:return False
        a=self.fn("profile",uid);b=self.fn("profile",cid)
        if not a or not b or not self.fn("eligible",a,b):
            return False
        if self.optout(uid) or self.already_started(uid,cid):
            return False
        stamp=self.timestamp(self.now())
        due=self.timestamp(self.now()+timedelta(minutes=30))
        self.fn("execute","""INSERT INTO pair_read_followups(
            viewer_user_id,candidate_user_id,engaged_at,due_at,status)
            VALUES(?,?,?,?,'pending')
            ON CONFLICT(viewer_user_id,candidate_user_id) DO NOTHING""",
            (uid,cid,stamp,due))
        return True

    def mark_checkout(self,uid,cid):
        self.ensure()
        self.fn("execute","""UPDATE pair_read_followups SET status='checkout_started'
           WHERE viewer_user_id=? AND candidate_user_id=?
             AND status IN ('pending','sending')""",(int(uid),int(cid)))

    def daily_allowed(self,uid):
        """Sharing the two/day proactive-message budget with new-pair alerts."""
        engine=self.ns.get("MATCH_PUSH_ENGINE")
        if not engine:return False
        clock,zone,start,end=engine.local_bounds(uid)
        if clock.hour<9 or clock.hour>=22:return False
        # Engine.daily_stats counts new pair alerts, legacy alerts and followups.
        _,count,_=engine.daily_stats(uid)
        if count>=2:return False
        try:
            row=self.fn("one","""SELECT COUNT(*) c FROM lifecycle_sends
                  WHERE user_id=? AND created_at>=? AND created_at<?""",
                  (int(uid),start,end))
            if row and count+int(row["c"] or 0)>=2:return False
        except Exception:pass
        return True

    async def process(self,bot_api, at=None):
        self.ensure()
        now=self.timestamp(at or self.now())
        rows=self.fn("many","""SELECT viewer_user_id,candidate_user_id,engaged_at
              FROM pair_read_followups WHERE status='pending' AND due_at<=?
              ORDER BY due_at ASC LIMIT 100""",(now,))
        delivered=0
        for record in rows:
            uid,cid=int(record["viewer_user_id"]),int(record["candidate_user_id"])
            try:
                engaged=datetime.fromisoformat(str(record["engaged_at"])).replace(tzinfo=timezone.utc)
                if self.now()-engaged>timedelta(hours=36):
                    self.fn("execute","""UPDATE pair_read_followups SET status='expired'
                      WHERE viewer_user_id=? AND candidate_user_id=? AND status='pending'""",(uid,cid))
                    continue
            except (ValueError,TypeError):pass
            if self.optout(uid):
                self.fn("execute","""UPDATE pair_read_followups SET status='opted_out'
                  WHERE viewer_user_id=? AND candidate_user_id=? AND status='pending'""",(uid,cid))
                continue
            viewer=self.fn("profile",uid);candidate=self.fn("profile",cid);tg=self.fn("user",uid)
            if not viewer or not candidate or not tg or int(tg["is_banned"] or 0) or not self.fn("eligible",viewer,candidate):
                self.fn("execute","""UPDATE pair_read_followups SET status='unavailable'
                   WHERE viewer_user_id=? AND candidate_user_id=? AND status='pending'""",(uid,cid))
                continue
            if self.already_started(uid,cid):
                self.fn("execute","""UPDATE pair_read_followups SET status='already_started'
                  WHERE viewer_user_id=? AND candidate_user_id=? AND status='pending'""",(uid,cid))
                continue
            if not self.daily_allowed(uid):
                continue  # wait until local daylight and a fresh daily allowance
            # Guard against concurrent workers sending duplicate messages.
            with self.fn("db") as conn:
                result=conn.execute("""UPDATE pair_read_followups SET status='sending'
                  WHERE viewer_user_id=? AND candidate_user_id=?
                    AND status='pending' RETURNING viewer_user_id""",(uid,cid)).fetchone()
            if not result:continue
            try:
                from telegram import InlineKeyboardMarkup,InlineKeyboardButton
                base=self.ns.get("PAIR_WEB_BASE_URL")
                token_url=self.fn("pair_link",base,uid,cid,self.ns["FLASK_SECRET"])
                if not token_url:raise ValueError("missing pair link")
                name=html.escape(str(candidate["name"]))
                text=(
                    f"💌 <b>А если это начало вашей истории?</b>\n\n"
                    f"Ты уже посмотрел(а) совместимость с <b>{name}</b>. "
                    "Если этот человек тебе откликнулся, можно сделать первый шаг.\n\n"
                    "Знакомство начнётся только при взаимном согласии. "
                    "Контакт другого человека не раскрывается автоматически."
                )
                kb=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💞 Вернуться к совместимости и предложить общение",url=token_url)],
                    [InlineKeyboardButton("🔕 Больше не напоминать",callback_data="lf:optout")]
                ])
                await bot_api.send_message(tg["tg_id"],text,parse_mode="HTML",
                                           reply_markup=kb,disable_web_page_preview=True)
                self.fn("execute","""UPDATE pair_read_followups
                   SET status='sent',sent_at=? WHERE viewer_user_id=?
                   AND candidate_user_id=? AND status='sending'""",
                   (self.timestamp(self.now()),uid,cid))
                delivered+=1
                await asyncio.sleep(.12)
            except Exception as exc:
                self.fn("execute","""UPDATE pair_read_followups SET status='pending'
                  WHERE viewer_user_id=? AND candidate_user_id=? AND status='sending'""",(uid,cid))
                print("[pair-followup] send failed "+type(exc).__name__,flush=True)
        return delivered

    async def maintain(self,bot_api):
        await asyncio.sleep(17)
        print("[pair-followup] scheduler started; engaged view + 30m, opt-out, max 2/day",flush=True)
        while True:
            try:
                total=await self.process(bot_api)
                if total:print("[pair-followup] sent="+str(total),flush=True)
            except Exception as exc:
                print("[pair-followup] scheduler "+type(exc).__name__+": "+str(exc)[:140],flush=True)
            await asyncio.sleep(60)
