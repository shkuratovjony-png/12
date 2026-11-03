"""Consent-respecting scheduled suggestions for Sovpali.

- One directed recipient for each unordered pair; never notify both sides about each other.
- First-ever compatible match => immediate notification, even outside local daytime.
- Only after that first contact, subsequent suggestions use local schedule and two/day cap.
- Telegram doesn't share a timezone; offline city mapping with /timezone override.
- Read-only suggestions never reserve an exclusive contact or payment order.
- The sent/visited log persists in PostgreSQL, prevents repeat pushes, and can
  be queried without exposing personal data in server logs.
"""
import asyncio
import html
import json
import threading
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from match_localtime import local_now, infer_zone

class MatchPushEngine:
    def __init__(self,ns):
        self.ns=ns
        self._initialized=False
        self._init_lock=threading.Lock()
        self._send_lock=threading.Lock()
        self._tick=0

    def call(self,name,*a,**k):
        return self.ns[name](*a,**k)

    def init_db(self):
        if self._initialized:return
        with self._init_lock:
            if self._initialized:return
            with self.call("db") as c:
                if self.ns["USE_POSTGRES"]:
                    c.executescript("""
                        CREATE TABLE IF NOT EXISTS match_pushes(
                          recipient_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                          candidate_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                          local_day TEXT NOT NULL,
                          slot TEXT NOT NULL,
                          status TEXT NOT NULL DEFAULT 'reserved',
                          created_at TEXT NOT NULL,
                          sent_at TEXT,
                          PRIMARY KEY (recipient_user_id,candidate_user_id)
                        );
                        CREATE TABLE IF NOT EXISTS match_push_views(
                          viewer_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                          candidate_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                          viewed_at TEXT NOT NULL,
                          PRIMARY KEY (viewer_user_id,candidate_user_id)
                        );
                        CREATE TABLE IF NOT EXISTS match_push_timezones(
                          user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                          timezone_name TEXT NOT NULL,
                          updated_at TEXT NOT NULL
                        );
                    """)
                else:
                    c.executescript("""
                        CREATE TABLE IF NOT EXISTS match_pushes(
                          recipient_user_id INTEGER NOT NULL,
                          candidate_user_id INTEGER NOT NULL,
                          local_day TEXT NOT NULL,
                          slot TEXT NOT NULL,
                          status TEXT NOT NULL DEFAULT 'reserved',
                          created_at TEXT NOT NULL,
                          sent_at TEXT,
                          PRIMARY KEY (recipient_user_id,candidate_user_id)
                        );
                        CREATE TABLE IF NOT EXISTS match_push_views(
                          viewer_user_id INTEGER NOT NULL,
                          candidate_user_id INTEGER NOT NULL,
                          viewed_at TEXT NOT NULL,
                          PRIMARY KEY (viewer_user_id,candidate_user_id)
                        );
                        CREATE TABLE IF NOT EXISTS match_push_timezones(
                          user_id INTEGER PRIMARY KEY,
                          timezone_name TEXT NOT NULL,
                          updated_at TEXT NOT NULL
                        );
                    """)
                c.executescript("""
                    CREATE INDEX IF NOT EXISTS idx_push_daily ON match_pushes(recipient_user_id,local_day,status);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_push_daily_slot
                       ON match_pushes(recipient_user_id,local_day,slot)
                       WHERE status IN ('reserved','sent');
                    CREATE INDEX IF NOT EXISTS idx_push_seen_viewer ON match_push_views(viewer_user_id);
                    CREATE TABLE IF NOT EXISTS match_pair_directions(
                      pair_low BIGINT NOT NULL,pair_high BIGINT NOT NULL,
                      recipient_user_id BIGINT NOT NULL,candidate_user_id BIGINT NOT NULL,
                      status TEXT NOT NULL,created_at TEXT NOT NULL,sent_at TEXT,
                      PRIMARY KEY(pair_low,pair_high));
                    CREATE INDEX IF NOT EXISTS idx_pair_dir_recipient
                      ON match_pair_directions(recipient_user_id);
                    -- Backfill historic sent pushes; preserve who received them.
                    INSERT INTO match_pair_directions(
                       pair_low,pair_high,recipient_user_id,candidate_user_id,
                       status,created_at,sent_at)
                    SELECT CASE WHEN recipient_user_id<candidate_user_id THEN recipient_user_id ELSE candidate_user_id END,
                           CASE WHEN recipient_user_id>candidate_user_id THEN recipient_user_id ELSE candidate_user_id END,
                           recipient_user_id,candidate_user_id,'sent',created_at,sent_at
                    FROM match_pushes WHERE status='sent' ORDER BY created_at ASC
                    ON CONFLICT(pair_low,pair_high) DO NOTHING;
                """)
            self._initialized=True

    def now(self):
        return datetime.now(timezone.utc)

    @staticmethod
    def naive_iso(t):
        return t.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    def zone(self,uid,profile=None,at=None):
        self.init_db()
        uid=int(uid)
        row=self.call("one","SELECT timezone_name FROM match_push_timezones WHERE user_id=?",(uid,))
        override=row["timezone_name"] if row else None
        if profile is None:profile=self.call("profile",uid)
        city=profile["city"] if profile else ""
        return local_now(city,override,at if at is not None else self.now())

    def set_timezone(self,uid,zone):
        if zone not in self.timezone_choices().values():return False
        self.init_db()
        self.call("execute","""INSERT INTO match_push_timezones(user_id,timezone_name,updated_at)
           VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET
           timezone_name=excluded.timezone_name,updated_at=excluded.updated_at""",
           (int(uid),zone,self.naive_iso(self.now())))
        return True

    @staticmethod
    def timezone_choices():
        return {
         "2":"Europe/Kaliningrad","3":"Europe/Moscow",
         "4":"Europe/Samara","5":"Asia/Yekaterinburg",
         "6":"Asia/Omsk","7":"Asia/Novosibirsk",
         "8":"Asia/Irkutsk","9":"Asia/Yakutsk",
         "10":"Asia/Vladivostok","11":"Asia/Sakhalin",
         "12":"Asia/Kamchatka",
        }

    def local_bounds(self,uid,at=None):
        clock,zone=self.zone(uid,at=at)
        start=datetime.combine(clock.date(),time.min,tzinfo=ZoneInfo(zone))
        end=datetime.combine(clock.date()+timedelta(days=1),time.min,tzinfo=ZoneInfo(zone))
        return clock,zone,self.naive_iso(start),self.naive_iso(end)

    def old_notifications(self,uid,start,end):
        # Include legacy exclusive offers in today's 2-message limit.
        try:
            return self.call("many","""SELECT offered_at FROM match_offers
               WHERE recipient_user_id=? AND offered_at>=? AND offered_at<?
                 AND status<>'send_failed' ORDER BY offered_at DESC""",
                 (int(uid),start,end))
        except Exception:return []

    def daily_stats(self,uid,at=None):
        self.init_db()
        clock,zone,start,end=self.local_bounds(uid,at)
        sent=self.call("many","""SELECT status,sent_at,created_at,slot FROM match_pushes
             WHERE recipient_user_id=? AND local_day=?
             AND status IN ('reserved','sent')""",(int(uid),clock.date().isoformat()))
        legacy=self.old_notifications(uid,start,end)
        # Conversion follow-ups share the same two-per-local-day proactive
        # notification limit. This table is initialized by PairConversion.
        followups=[]
        try:
            followups=self.call("many","""SELECT sent_at FROM pair_read_followups
                WHERE viewer_user_id=? AND status='sent'
                  AND sent_at>=? AND sent_at<?""",(int(uid),start,end))
        except Exception:pass
        timestamps=[]
        for r in sent:
            stamp=r["sent_at"] or r["created_at"]
            try:timestamps.append(datetime.fromisoformat(str(stamp).replace("Z","+00:00")).replace(tzinfo=timezone.utc))
            except (ValueError,TypeError):pass
        for r in legacy:
            try:timestamps.append(datetime.fromisoformat(str(r["offered_at"]).replace("Z","+00:00")).replace(tzinfo=timezone.utc))
            except (ValueError,TypeError):pass
        for r in followups:
            try:timestamps.append(datetime.fromisoformat(str(r["sent_at"]).replace("Z","+00:00")).replace(tzinfo=timezone.utc))
            except (ValueError,TypeError):pass
        return clock,len(sent)+len(legacy)+len(followups),max(timestamps) if timestamps else None

    def has_ever_seen_match(self,uid):
        """Return true only after an actual match delivery or personal pair view.

        The first automatic recommendation is not gated by local quiet hours.
        Historical match offers and signed-page views count as first contact,
        so old members do not suddenly get unscheduled nighttime pushes.
        A failed database history lookup must not send unplanned notifications.
        """
        self.init_db()
        uid=int(uid)
        try:
            if self.call("one","""SELECT 1 FROM match_pushes
                    WHERE recipient_user_id=? AND status='sent' LIMIT 1""",(uid,)):
                return True
            if self.call("one","""SELECT 1 FROM match_push_views
                    WHERE viewer_user_id=? LIMIT 1""",(uid,)):
                return True
            if self.call("one","""SELECT 1 FROM match_offers
                    WHERE recipient_user_id=? AND status NOT IN ('send_failed','reserved')
                    LIMIT 1""",(uid,)):
                return True
            return False
        except Exception as exc:
            print("[match-push] first contact history unavailable: "+type(exc).__name__,flush=True)
            return True

    def desired_slot(self,uid,at=None):
        clock,count,last=self.daily_stats(uid,at)
        # A person's very first compatible match must arrive immediately,
        # irrespective of local time. It still counts toward the 2/day cap.
        if count>=2:return None
        if not self.has_ever_seen_match(uid):
            return "first"
        hour=clock.hour
        # After first contact, keep the existing local-time notification rules.
        if hour<9 or hour>=22:return None
        if count==0:return "first"
        if hour<18:return None
        if last and (self.now() if at is None else at)-last < timedelta(hours=4):return None
        return "evening"

    def disabled(self,uid):
        try:
            r=self.call("one","SELECT promo_enabled FROM lifecycle_prefs WHERE user_id=?",(int(uid),))
            return bool(r and int(r["promo_enabled"] or 0)==0)
        except Exception:return False

    def pair_owner(self,uid,cid):
        """Permanent direction assigned to an unordered pair."""
        self.init_db()
        uid,cid=int(uid),int(cid)
        lo,hi=sorted((uid,cid))
        assigned=self.call("one","""SELECT recipient_user_id FROM match_pair_directions
                    WHERE pair_low=? AND pair_high=?""",(lo,hi))
        if assigned:
            return int(assigned["recipient_user_id"])
        try:
            previous=self.call("one","""SELECT recipient_user_id FROM match_offers
                        WHERE pair_low=? AND pair_high=?
                          AND status NOT IN ('send_failed','reserved')
                        ORDER BY offered_at ASC LIMIT 1""",(lo,hi))
            return int(previous["recipient_user_id"]) if previous else None
        except Exception:
            return None

    def viewed(self,uid,cid):
        self.init_db()
        if self.call("one","SELECT 1 FROM match_push_views WHERE viewer_user_id=? AND candidate_user_id=?",(int(uid),int(cid))):
            return True
        if self.call("one","SELECT 1 FROM match_pushes WHERE recipient_user_id=? AND candidate_user_id=?",(int(uid),int(cid))):
            return True
        if self.pair_owner(uid,cid) is not None:
            return True
        lo,hi=sorted((int(uid),int(cid)))
        # Old automatic matches were already shown to the recipient.
        try:
            if self.call("one","SELECT 1 FROM match_offers WHERE pair_low=? AND pair_high=?",(lo,hi)):
                return True
        except Exception:pass
        # Legacy messages and early web links are recorded in audit history.
        try:
            rows=self.call("many","""SELECT payload FROM audit_events WHERE user_id=?
                  AND event_type IN ('motion_pair_view','my_pair_candidate_open','legacy_pair_open')
                  ORDER BY id DESC LIMIT 120""",(int(uid),))
            for row in rows:
                data=row["payload"]
                if isinstance(data,str):data=json.loads(data)
                if isinstance(data,dict) and str(data.get("candidate_user_id",""))==str(cid):
                    return True
        except Exception:pass
        return False

    def mark_view(self,viewer,candidate):
        viewer,candidate=int(viewer),int(candidate)
        if viewer==candidate:return
        self.init_db()
        self.call("execute","""INSERT INTO match_push_views(viewer_user_id,candidate_user_id,viewed_at)
          VALUES(?,?,?) ON CONFLICT(viewer_user_id,candidate_user_id)
          DO UPDATE SET viewed_at=excluded.viewed_at""",
          (viewer,candidate,self.naive_iso(self.now())))

    def suitable(self,viewer,candidate):
        try:
            if not self.call("eligible",viewer,candidate):return None
            if viewer["goal"]!=candidate["goal"]:return None
            sv=int(self.call("score",viewer,candidate))
            minimum=self.call("sm_int","auto_match_min_score",86)
            if sv<int(minimum) and viewer["priority"]!=candidate["priority"]:
                return None
            return sv
        except Exception as exc:
            print("[match-push] compatibility error "+type(exc).__name__,flush=True)
            return None

    def candidates(self,uid,only_candidate=None,limit=150):
        viewer=self.call("profile",int(uid))
        if not viewer:return []
        if only_candidate is not None:
            c=self.call("profile",int(only_candidate))
            rows=[c] if c else []
        else:
            rows=self.call("many","""SELECT p.*,u.tg_id,u.is_banned FROM profiles p
                JOIN users u ON u.id=p.user_id
                WHERE p.user_id<>? AND u.is_banned=0
                ORDER BY p.completed_at DESC LIMIT ?""",(int(uid),int(limit)))
        out=[]
        for candidate in rows:
            if candidate is None:continue
            cid=int(candidate["user_id"])
            if cid==int(uid):continue
            sv=self.suitable(viewer,candidate)
            if sv is None:continue
            if self.viewed(uid,cid):continue
            out.append((sv,candidate))
        # Strong fit first; newest profiles win among equals.
        out.sort(key=lambda pair:(pair[0],str(pair[1]["completed_at"])),reverse=True)
        return out

    def reserve(self,uid,cid,slot):
        self.init_db()
        uid,cid=int(uid),int(cid)
        with self._send_lock:
            clock,count,last=self.daily_stats(uid)
            if count>=2 or self.desired_slot(uid)!=slot:return False
            try:
                with self.call("db") as conn:
                    if self.ns["USE_POSTGRES"]:
                        conn.execute("SELECT pg_advisory_xact_lock(?)",(uid,))
                    # Recheck inside the transaction, protecting concurrent workers.
                    day=clock.date().isoformat()
                    previous=conn.execute("""SELECT COUNT(*) n FROM match_pushes WHERE recipient_user_id=?
                       AND local_day=? AND status IN ('reserved','sent')""",(uid,day)).fetchone()
                    oldcount=len(self.old_notifications(uid,*self.local_bounds(uid)[2:]))
                    if int(previous["n"])+oldcount>=2:return False
                    if conn.execute("""SELECT 1 FROM match_pushes WHERE recipient_user_id=?
                         AND candidate_user_id=?""",(uid,cid)).fetchone():
                        return False
                    if conn.execute("""SELECT 1 FROM match_push_views WHERE viewer_user_id=?
                         AND candidate_user_id=?""",(uid,cid)).fetchone():
                        return False
                    lo,hi=sorted((uid,cid))
                    claimed=conn.execute("""INSERT INTO match_pair_directions(
                       pair_low,pair_high,recipient_user_id,candidate_user_id,
                       status,created_at)
                       VALUES(?,?,?,?,'reserved',?)
                       ON CONFLICT(pair_low,pair_high) DO NOTHING
                       RETURNING recipient_user_id""",
                       (lo,hi,uid,cid,self.naive_iso(self.now()))).fetchone()
                    if not claimed:return False
                    conn.execute("""INSERT INTO match_pushes(
                      recipient_user_id,candidate_user_id,local_day,slot,status,created_at)
                      VALUES(?,?,?,?,'reserved',?)""",(uid,cid,day,slot,self.naive_iso(self.now())))
                return True
            except Exception as exc:
                print("[match-push] reserve skipped "+type(exc).__name__,flush=True)
                return False

    async def suggest(self,bot_api,uid,only_candidate=None):
        uid=int(uid)
        if self.disabled(uid):return False
        slot=self.desired_slot(uid)
        if slot is None:return False
        viewer=self.call("profile",uid)
        if not viewer:return False
        recipient=self.call("user",uid)
        if not recipient or int(recipient["is_banned"] or 0):return False
        for sv,candidate in self.candidates(uid,only_candidate):
            cid=int(candidate["user_id"])
            if not self.reserve(uid,cid,slot):continue
            try:
                link=self.call("pair_link",self.ns["PAIR_WEB_BASE_URL"],uid,cid,self.ns["FLASK_SECRET"])
                name=html.escape(str(candidate["name"]))
                age=self.call("xm_age",candidate["birth_date"])
                age_label=f", {age}" if age else ""
                city=html.escape(str(candidate["city"]))
                normalize=self.ns.get("cn_key")
                if callable(normalize):
                    same_city=bool(normalize(viewer["city"])) and normalize(viewer["city"])==normalize(candidate["city"])
                else:
                    same_city=str(viewer["city"]).strip().casefold()==str(candidate["city"]).strip().casefold()
                near=f"\n📍 Вы из одного города — ещё один плюс." if same_city else ""
                caption=(f"💞 <b>Новое совпадение · {sv}%</b>\n\n"
                         f"<b>{name}{age_label}</b> · {city}\n"
                         "У вас есть общие ориентиры в отношениях."
                         +near+"\n\n"
                         "Персональный разбор и фотография — по кнопке ниже. "
                         "Знакомство начнётся только по взаимному согласию.")
                from telegram import InlineKeyboardMarkup,InlineKeyboardButton
                keyboard=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✨ Посмотреть совместимость",url=link)]
                ])
                if candidate["photo_file_id"]:
                    try:
                        await bot_api.send_photo(recipient["tg_id"],candidate["photo_file_id"],
                                                 caption=caption,parse_mode="HTML",reply_markup=keyboard)
                    except Exception:
                        await bot_api.send_message(recipient["tg_id"],caption,
                                                   parse_mode="HTML",reply_markup=keyboard)
                else:
                    await bot_api.send_message(recipient["tg_id"],caption,
                                               parse_mode="HTML",reply_markup=keyboard)
                self.call("execute","""UPDATE match_pushes SET status='sent',sent_at=?
                          WHERE recipient_user_id=? AND candidate_user_id=? AND status='reserved'""",
                          (self.naive_iso(self.now()),uid,cid))
                self.call("execute","""UPDATE match_pair_directions SET status='sent',sent_at=?
                    WHERE pair_low=? AND pair_high=? AND recipient_user_id=?""",
                    (self.naive_iso(self.now()),min(uid,cid),max(uid,cid),uid))
                print("[match-push] suggestion delivered slot="+slot+" score="+str(sv),flush=True)
                return True
            except Exception as exc:
                self.call("execute","""UPDATE match_pushes SET status='failed'
                        WHERE recipient_user_id=? AND candidate_user_id=? AND status='reserved'""",(uid,cid))
                self.call("execute","""UPDATE match_pair_directions SET status='failed'
                    WHERE pair_low=? AND pair_high=? AND recipient_user_id=?
                      AND status='reserved'""",(min(uid,cid),max(uid,cid),uid))
                print("[match-push] send failed "+type(exc).__name__+": "+str(exc)[:140],flush=True)
                # A failed delivery is not a reason to push another message instantly.
                return False
        return False

    async def new_profile(self,bot_api,uid):
        # Existing subscriber receives newcomer FIRST if they are compatible.
        # A globally unique unordered pair claim prevents reciprocal delivery.
        uid=int(uid)
        self.init_db()
        newcomer=self.call("profile",uid)
        if not newcomer:return
        rows=self.call("many","""SELECT p.*,u.is_banned FROM profiles p
              JOIN users u ON u.id=p.user_id WHERE p.user_id<>? AND u.is_banned=0
              ORDER BY p.completed_at ASC LIMIT 500""",(uid,))
        existing_sent=0
        for recipient in rows:
            rec_uid=int(recipient["user_id"])
            if self.suitable(recipient,newcomer) is None:continue
            if self.viewed(rec_uid,uid):continue
            if await self.suggest(bot_api,rec_uid,only_candidate=uid):
                existing_sent=1
                break
        # Newcomer can receive different profiles, never the one now allocated.
        newcomer_sent=await self.suggest(bot_api,uid)
        print("[match-push] new profile scanned; existing="+str(existing_sent)+
              " newcomer="+str(int(bool(newcomer_sent))),flush=True)

    async def maintain(self,bot_api):
        await asyncio.sleep(9)
        print("[match-push] scheduler: first-ever match immediate; subsequent 09-22/evening 18-22, 2/day",flush=True)
        while True:
            try:
                self.init_db()
                # Clear abandoned reservations; never repeat that same candidate.
                cutoff=self.naive_iso(self.now()-timedelta(minutes=20))
                self.call("execute","""UPDATE match_pushes SET status='abandoned'
                   WHERE status='reserved' AND created_at<?""",(cutoff,))
                users=self.call("many","""SELECT p.user_id FROM profiles p
                    JOIN users u ON u.id=p.user_id WHERE u.is_banned=0
                    ORDER BY p.completed_at ASC LIMIT 300""")
                pushed=0
                for row in users:
                    uid=int(row["user_id"])
                    if self.desired_slot(uid) is None:continue
                    if await self.suggest(bot_api,uid):
                        pushed+=1
                        await asyncio.sleep(.12)
                if pushed:
                    print("[match-push] maintenance sent="+str(pushed),flush=True)
            except Exception as exc:
                print("[match-push] maintenance "+type(exc).__name__+": "+str(exc)[:140],flush=True)
            await asyncio.sleep(120)
