"""Three-friend invite rewards: SQLite integration smoke test; no live users/payments."""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime

from affiliate_program import (
    ensure_schema as affiliate_schema, ensure_code as affiliate_code,
    register_start as affiliate_start,
)
from friend_invites import (
    ensure_schema as friend_schema, ensure_code, claim_start,
    profile_completed, overview, FRIEND_PREFIX,
)
from web_product_access import (
    ensure_schema as credit_schema, available_intro_credit,
    redeem_intro_credit,
)

with tempfile.TemporaryDirectory() as directory:
    path = os.path.join(directory, "friends.db")

    @contextmanager
    def db():
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    with db() as conn:
        conn.executescript("""
            CREATE TABLE users(
              id INTEGER PRIMARY KEY, tg_id INTEGER UNIQUE, is_banned INTEGER,
              created_at TEXT, last_seen_at TEXT);
            CREATE TABLE profiles(user_id INTEGER PRIMARY KEY);
            CREATE TABLE intro_orders(id INTEGER PRIMARY KEY, status TEXT);
        """)
    affiliate_schema(db)
    credit_schema(db)
    friend_schema(db)
    stamp = datetime.now().isoformat(timespec="seconds")

    def new_user(uid, profile=False):
        with db() as conn:
            conn.execute("INSERT INTO users VALUES(?,?,0,?,?)",
                         (uid, uid+10000, stamp, stamp))
            if profile:
                conn.execute("INSERT INTO profiles VALUES(?)", (uid,))
            return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    referrer = new_user(1, profile=True)
    code = ensure_code(db, 1)
    partner_code = affiliate_code(db, 1)
    assert not claim_start(db, referrer, ["friend_" + code]), "self referral blocked"

    # A click alone grants no benefit, and old users / bogus links are ignored.
    for uid in (2, 3, 4):
        account = new_user(uid)
        assert claim_start(db, account, ["friend_" + code])
        assert not claim_start(db, account, ["friend_invalid"])
    stat = overview(db, 1, "SovpaliBot_bot")
    assert stat["invited_count"] == 3
    assert stat["qualified_count"] == 0
    assert stat["available_rewards"] == 0
    assert stat["referral_url"] == "https://t.me/SovpaliBot_bot?start=friend_" + code
    # Friend channel must block even a fresh affiliate click.
    with db() as conn:
        user2 = conn.execute("SELECT * FROM users WHERE id=2").fetchone()
    assert not affiliate_start(db, user2, ["ref_" + partner_code])

    for uid in (2, 3):
        with db() as conn:
            conn.execute("INSERT INTO profiles VALUES(?)", (uid,))
        profile_completed(db, uid)
        profile_completed(db, uid)
    assert overview(db, 1, "SovpaliBot_bot")["qualified_count"] == 2
    assert available_intro_credit(db, 1) is None

    with db() as conn:
        conn.execute("INSERT INTO profiles VALUES(4)")
    profile_completed(db, 4)
    profile_completed(db, 4)
    stat = overview(db, 1, "SovpaliBot_bot")
    assert stat["qualified_count"] == 3
    assert stat["rewards_earned"] == 1
    assert stat["available_rewards"] == 1
    assert stat["progress"] == 0
    with db() as conn:
        rows = conn.execute("SELECT * FROM web_intro_credits").fetchall()
        assert len(rows) == 1 and rows[0]["source_order_id"] == FRIEND_PREFIX + "1-1"
        assert conn.execute("SELECT COUNT(*) n FROM affiliate_rewards").fetchone()["n"] == 0

    # Reused existing contact-credit mechanism; refusal restores the same gift.
    source = redeem_intro_credit(db, 1, "web-credit-41")
    assert source == FRIEND_PREFIX + "1-1"
    assert available_intro_credit(db, 1) is None
    with db() as conn:
        conn.execute("INSERT INTO intro_orders VALUES(41,'declined')")
    assert available_intro_credit(db, 1) == source
    assert redeem_intro_credit(db, 1, "web-credit-42") == source
    with db() as conn:
        conn.execute("INSERT INTO intro_orders VALUES(42,'accepted')")
    assert available_intro_credit(db, 1) is None

    # A second complete group creates exactly one additional (unused) voucher.
    for uid in (5,6,7):
        account = new_user(uid)
        assert claim_start(db, account, ["friend_" + code])
        with db() as conn:
            conn.execute("INSERT INTO profiles VALUES(?)", (uid,))
        profile_completed(db, uid)
    profile_completed(db, 7)
    assert overview(db, 1, "SovpaliBot_bot")["rewards_earned"] == 2
    assert overview(db, 1, "SovpaliBot_bot")["available_rewards"] == 1

    # Partner links still work and cannot also qualify for the gift program.
    other = new_user(8)
    assert affiliate_start(db, other, ["ref_" + partner_code])
    assert affiliate_start(db, other, ["ref_" + partner_code])
    assert not claim_start(db, other, ["friend_" + code])
    with db() as conn:
        conn.execute("INSERT INTO profiles VALUES(8)")
    profile_completed(db, 8)
    assert overview(db, 1, "SovpaliBot_bot")["qualified_count"] == 6
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM affiliate_referrals").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) n FROM friend_invite_referrals").fetchone()["n"] == 6
        assert conn.execute("SELECT COUNT(*) n FROM referral_source_claims").fetchone()["n"] == 7

print("[test] friends: 3 completed -> 1 free intro, restores on decline, no double claims or affiliate overlap PASS", flush=True)
