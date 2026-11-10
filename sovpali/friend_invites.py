"""Voluntary friend invites: 3 distinct completed new profiles -> one intro voucher.

Separate from the 30% paid affiliate channel. Every credit is recorded in
web_intro_credits with a non-bank 'friend-invite-' source. No fake orders.
"""
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import abort, make_response, request
from pair_miniapp import validate_init_data

QUALIFY_PER_REWARD = 3
FRIEND_PREFIX = "friend-invite-"
CODE_PATTERN = re.compile(r"friend_[A-Za-z0-9_-]{8,18}")
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_]{5,32}")


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_schema(db):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS friend_invite_codes (
          owner_user_id BIGINT PRIMARY KEY, code TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS friend_invite_referrals (
          invited_user_id BIGINT PRIMARY KEY,
          inviter_user_id BIGINT NOT NULL,
          captured_at TEXT NOT NULL,
          qualified_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_friend_invites_inviter
          ON friend_invite_referrals(inviter_user_id, qualified_at);
        CREATE TABLE IF NOT EXISTS referral_source_claims (
          referred_user_id BIGINT PRIMARY KEY, source TEXT NOT NULL,
          owner_user_id BIGINT NOT NULL, claimed_at TEXT NOT NULL
        );
        INSERT INTO referral_source_claims(referred_user_id,source,owner_user_id,claimed_at)
          SELECT invited_user_id,'friend',inviter_user_id,captured_at
          FROM friend_invite_referrals
          ON CONFLICT(referred_user_id) DO NOTHING;
        """)


def ensure_code(db, uid):
    uid = int(uid)
    with db() as c:
        existing = c.execute(
            "SELECT code FROM friend_invite_codes WHERE owner_user_id=?", (uid,)
        ).fetchone()
        if existing:
            return existing["code"]
        code = secrets.token_urlsafe(9)
        c.execute("""INSERT INTO friend_invite_codes(owner_user_id,code,created_at)
                     VALUES(?,?,?) ON CONFLICT(owner_user_id) DO NOTHING""",
                  (uid, code, utc()))
        row = c.execute(
            "SELECT code FROM friend_invite_codes WHERE owner_user_id=?", (uid,)
        ).fetchone()
        return row["code"]


def claim_start(db, user, args):
    """Only a new account's first /start may claim a friend link."""
    if not args or len(args) != 1 or not CODE_PATTERN.fullmatch(str(args[0])):
        return False
    created = str(user["created_at"] or "")
    last = str(user["last_seen_at"] or "")
    if not created or created != last:
        return False
    try:
        stamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - stamp).total_seconds()
        if not -5 <= age_seconds <= 180:
            return False
    except (ValueError, TypeError):
        return False
    invited_id = int(user["id"])
    code = str(args[0])[7:]
    with db() as c:
        inviter = c.execute(
            "SELECT owner_user_id FROM friend_invite_codes WHERE code=?", (code,)
        ).fetchone()
        if not inviter:
            return False
        inviter_id = int(inviter["owner_user_id"])
        if invited_id == inviter_id:
            return False
        if not c.execute(
            "SELECT 1 FROM profiles WHERE user_id=?", (inviter_id,)
        ).fetchone():
            return False
        if c.execute(
            "SELECT 1 FROM profiles WHERE user_id=?", (invited_id,)
        ).fetchone():
            return False
        # An invite is either a 30% affiliate signup OR a friend gift, never both.
        if c.execute(
            "SELECT 1 FROM affiliate_referrals WHERE referred_user_id=?",
            (invited_id,)
        ).fetchone():
            return False
        stamp = utc()
        claim = c.execute(
            """INSERT INTO referral_source_claims(
                 referred_user_id,source,owner_user_id,claimed_at)
               VALUES(?,'friend',?,?) ON CONFLICT(referred_user_id) DO NOTHING
               RETURNING referred_user_id""",
            (invited_id, inviter_id, stamp)
        ).fetchone()
        if not claim:
            return False
        row = c.execute(
            """INSERT INTO friend_invite_referrals(
                 invited_user_id,inviter_user_id,captured_at)
               VALUES(?,?,?) ON CONFLICT(invited_user_id) DO NOTHING
               RETURNING invited_user_id""",
            (invited_id, inviter_id, stamp)
        ).fetchone()
        return bool(row)


def sync_rewards(db, inviter_id):
    """Idempotent, DB-unique grants, safe under concurrent profile completions."""
    inviter_id = int(inviter_id)
    with db() as c:
        if not c.execute(
            "SELECT 1 FROM profiles WHERE user_id=?", (inviter_id,)
        ).fetchone():
            return 0
        count = c.execute(
            """SELECT COUNT(*) AS n FROM friend_invite_referrals
               WHERE inviter_user_id=? AND qualified_at IS NOT NULL""",
            (inviter_id,)
        ).fetchone()
        complete = int(count["n"])
        earned = complete // QUALIFY_PER_REWARD
        awarded = 0
        for batch in range(1, earned + 1):
            source = FRIEND_PREFIX + str(inviter_id) + "-" + str(batch)
            row = c.execute(
                """INSERT INTO web_intro_credits(
                     source_order_id,buyer_user_id,credited_at)
                   VALUES(?,?,?) ON CONFLICT(source_order_id) DO NOTHING
                   RETURNING source_order_id""",
                (source, inviter_id, utc())
            ).fetchone()
            if row:
                awarded += 1
        return awarded


def profile_completed(db, uid):
    """Call AFTER successful profile save. Repeating it never pays twice."""
    uid = int(uid)
    with db() as c:
        row = c.execute(
            "SELECT inviter_user_id FROM friend_invite_referrals WHERE invited_user_id=?",
            (uid,)
        ).fetchone()
        if row:
            c.execute(
                """UPDATE friend_invite_referrals SET qualified_at=?
                   WHERE invited_user_id=? AND qualified_at IS NULL
                     AND EXISTS(SELECT 1 FROM profiles WHERE user_id=?)""",
                (utc(), uid, uid)
            )
            inviter = int(row["inviter_user_id"])
        else:
            inviter = None
    if inviter is not None:
        sync_rewards(db, inviter)
    # A referrer may finish their own profile after friends joined.
    sync_rewards(db, uid)


def overview(db, uid, bot_username):
    uid = int(uid)
    code = ensure_code(db, uid)
    sync_rewards(db, uid)
    with db() as c:
        rows = c.execute(
            """SELECT qualified_at FROM friend_invite_referrals
               WHERE inviter_user_id=?""", (uid,)
        ).fetchall()
        available = c.execute(
            """SELECT COUNT(*) AS n FROM web_intro_credits
               WHERE buyer_user_id=? AND source_order_id LIKE ?
                 AND redeemed_for_order IS NULL""",
            (uid, FRIEND_PREFIX + "%")
        ).fetchone()
    qualified = sum(1 for row in rows if row["qualified_at"] is not None)
    progress = qualified % QUALIFY_PER_REWARD
    safe_username = str(bot_username or "")
    url = ("https://t.me/" + safe_username + "?start=friend_" + code
           if USERNAME_PATTERN.fullmatch(safe_username) else "")
    return {
        "referral_url": url,
        "invited_count": len(rows),
        "qualified_count": qualified,
        "pending_count": len(rows) - qualified,
        "progress": progress,
        "needed": QUALIFY_PER_REWARD - progress,
        "reward_every": QUALIFY_PER_REWARD,
        "rewards_earned": qualified // QUALIFY_PER_REWARD,
        "available_rewards": int(available["n"]),
    }


def mount(app, ns):
    db = ns["db"]
    ensure_schema(db)

    @app.post("/s/app/api/friends")
    def friend_invites_overview():
        origin = request.headers.get("Origin", "")
        if origin and urlsplit(origin).netloc != urlsplit(request.host_url).netloc:
            abort(403)
        if (request.content_length or 0) > 4096:
            abort(413)
        try:
            tg_id = validate_init_data(
                request.headers.get("X-Telegram-Init-Data", ""),
                ns.get("TOKEN") or ""
            )
        except (ValueError, TypeError, KeyError):
            abort(401)
        account = ns["one"]("SELECT * FROM users WHERE tg_id=?", (int(tg_id),))
        if not account or int(account["is_banned"] or 0):
            abort(403)
        uid = int(account["id"])
        if not ns["profile"](uid):
            result = {"message": "Сначала заполни анкету, чтобы приглашать друзей."}
            return make_response(result, 403)
        username = (ns.get("MINIAPP_BOT_USERNAME")
                    or getattr(getattr(ns.get("bot"), "bot", None), "username", ""))
        response = make_response(overview(db, uid, username), 200)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
