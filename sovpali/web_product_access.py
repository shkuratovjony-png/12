"""Web-only Sovpali product entitlements.

This module does not charge or unlock on its own. All grants require a confirmed
server-side billing_web_orders row, correct product and exact bank amount.
"""
from datetime import datetime, timezone, timedelta
import threading

CATALOG = {
    "workshop": {"rub": 500, "kopecks": 50000, "title": "Эмулятор общения"},
    "contact": {"rub": 100, "kopecks": 10000, "title": "Запрос на знакомство"},
    "coach": {"rub": 900, "kopecks": 90000, "title": "Помощник после ответа"},
    "premium": {"rub": 1200, "kopecks": 120000, "title": "Premium · 30 дней"},
}
_LOCK = threading.RLock()


def _utc(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _ts(dt):
    return _utc(dt).isoformat(timespec="seconds")


def ensure_schema(db):
    """Postgres and SQLite compatible, additive; does not touch user profiles."""
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS web_purchase_bindings (
          billing_order_id TEXT PRIMARY KEY,
          buyer_user_id BIGINT NOT NULL,
          target_user_id BIGINT,
          sku TEXT NOT NULL,
          linked_intro_id BIGINT,
          binding_status TEXT NOT NULL DEFAULT 'reserved',
          delivered_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_web_purchase_buyer
          ON web_purchase_bindings(buyer_user_id);
        CREATE TABLE IF NOT EXISTS web_premium_memberships (
          user_id BIGINT PRIMARY KEY,
          active_until TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS web_product_grants (
          billing_order_id TEXT PRIMARY KEY,
          buyer_user_id BIGINT NOT NULL,
          sku TEXT NOT NULL,
          granted_at TEXT NOT NULL,
          details TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS web_intro_credits (
          source_order_id TEXT PRIMARY KEY,
          buyer_user_id BIGINT NOT NULL,
          redeemed_for_order TEXT UNIQUE,
          credited_at TEXT NOT NULL,
          redeemed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_web_intro_credits_owner
          ON web_intro_credits(buyer_user_id);
        """)


def bind_order(db, order_id, buyer_id, sku, target_id=None, linked_intro_id=None):
    """Fix immutable owner/product before the bank checkout is created."""
    if sku not in CATALOG or not order_id or not buyer_id:
        raise ValueError("invalid product identity")
    if sku == "contact" and (target_id is None or int(buyer_id) == int(target_id)):
        raise ValueError("contact requires a different target")
    with db() as c:
        c.execute("""INSERT INTO web_purchase_bindings(
                     billing_order_id,buyer_user_id,target_user_id,sku,linked_intro_id,
                     binding_status,updated_at)
                   VALUES(?,?,?,?,?,'reserved',?)""",
                  (str(order_id),int(buyer_id),
                   int(target_id) if target_id is not None else None,
                   sku,int(linked_intro_id) if linked_intro_id is not None else None,
                   _ts(_utc())))


def binding(db, order_id):
    with db() as c:
        return c.execute("SELECT * FROM web_purchase_bindings WHERE billing_order_id=?",
                         (str(order_id),)).fetchone()


def _bank_paid(c, order_id, sku):
    row = c.execute("""SELECT * FROM billing_web_orders
                       WHERE order_id=? AND status='paid'""",(str(order_id),)).fetchone()
    if not row or row["product_key"] != sku or str(row["currency_code"]) != "643":
        return False
    return int(row["amount_kopecks"]) == CATALOG[sku]["kopecks"]


def premium_expires(db, buyer_id):
    with db() as c:
        row=c.execute("SELECT active_until FROM web_premium_memberships WHERE user_id=?",
                      (int(buyer_id),)).fetchone()
    return row["active_until"] if row else None


def premium_active(db, buyer_id, now=None):
    exp=premium_expires(db, buyer_id)
    if not exp:
        return False
    try:
        return datetime.fromisoformat(str(exp).replace("Z","+00:00")) > _utc(now)
    except (ValueError,TypeError):
        return False


def grant_premium(db, order_id, now=None):
    """30 calendar days, cumulative; idempotent for duplicated callbacks."""
    current=_utc(now)
    with _LOCK:
        with db() as c:
            bound=c.execute("SELECT * FROM web_purchase_bindings WHERE billing_order_id=?",
                            (str(order_id),)).fetchone()
            if not bound or bound["sku"] != "premium" or not _bank_paid(c,order_id,"premium"):
                return False
            earlier=c.execute("SELECT 1 FROM web_product_grants WHERE billing_order_id=?",
                              (str(order_id),)).fetchone()
            if earlier:
                return True
            buyer=int(bound["buyer_user_id"])
            old=c.execute("SELECT active_until FROM web_premium_memberships WHERE user_id=?",
                          (buyer,)).fetchone()
            start=current
            if old:
                try:
                    exp=datetime.fromisoformat(str(old["active_until"]).replace("Z","+00:00"))
                    if exp > start:
                        start=exp
                except (ValueError,TypeError):
                    pass
            until=_ts(start+timedelta(days=30))
            c.execute("""INSERT INTO web_premium_memberships(user_id,active_until,updated_at)
                        VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE
                        SET active_until=excluded.active_until,updated_at=excluded.updated_at""",
                      (buyer,until,_ts(current)))
            c.execute("""INSERT INTO web_product_grants(billing_order_id,buyer_user_id,sku,granted_at,details)
                        VALUES(?,?,'premium',?,?)""",
                      (str(order_id),buyer,_ts(current),until))
            c.execute("""UPDATE web_purchase_bindings SET binding_status='delivered',
                        delivered_at=?,updated_at=? WHERE billing_order_id=?""",
                      (_ts(current),_ts(current),str(order_id)))
    return True


def credit_intro(db, source_order_id, now=None):
    """Only a paid and bound introduction can generate one replacement credit."""
    current=_ts(_utc(now))
    with db() as c:
        bound=c.execute("SELECT * FROM web_purchase_bindings WHERE billing_order_id=?",
                        (str(source_order_id),)).fetchone()
        if not bound or bound["sku"] != "contact" or not _bank_paid(c,source_order_id,"contact"):
            return False
        c.execute("""INSERT INTO web_intro_credits(source_order_id,buyer_user_id,credited_at)
                     VALUES(?,?,?) ON CONFLICT(source_order_id) DO NOTHING""",
                  (str(source_order_id),int(bound["buyer_user_id"]),current))
    return True



def reconcile_intro_credits(db):
    """Restore a paid entitlement after each unsuccessful FREE repeat.

    The original bank-paid order remains the sole source of entitlement.
    A free repeat temporarily claims that entitlement as web-credit-<intro_id>;
    reject, 24-hour silence or failed delivery restores the SAME claim.
    Accepted introductions remain redeemed forever. Safe on restart/retry.
    """
    with db() as c:
        # Fast path: do not require intro reservation tables when the buyer
        # has no pending redeemed credits (e.g. standalone checkout bootstrap).
        any_pending=c.execute("""SELECT 1 FROM web_intro_credits
            WHERE redeemed_for_order LIKE 'web-credit-%' LIMIT 1""").fetchone()
        if not any_pending:return 0
        rows=c.execute("""SELECT v.source_order_id,v.redeemed_for_order,i.id
            FROM web_intro_credits v
            JOIN intro_orders i ON v.redeemed_for_order=('web-credit-' || CAST(i.id AS TEXT))
            WHERE i.status IN ('declined','expired','closed')""").fetchall()
        restored=0
        for row in rows:
            updated=c.execute("""UPDATE web_intro_credits
               SET redeemed_for_order=NULL,redeemed_at=NULL
               WHERE source_order_id=? AND redeemed_for_order=?
                 AND EXISTS(SELECT 1 FROM intro_orders
                            WHERE id=? AND status IN ('declined','expired','closed'))""",
               (row["source_order_id"],row["redeemed_for_order"],int(row["id"])))
            restored+=int(updated.rowcount or 0)
        return restored


def redeem_intro_credit(db, buyer_id, for_order_id, now=None):
    """Atomic single-use credit, returns source order or None; never counts as a bank payment."""
    current=_ts(_utc(now))
    reconcile_intro_credits(db)
    with db() as c:
        previous=c.execute("""SELECT source_order_id FROM web_intro_credits
                             WHERE redeemed_for_order=? AND buyer_user_id=?""",
                           (str(for_order_id),int(buyer_id))).fetchone()
        if previous:
            return previous["source_order_id"]
        row=c.execute("""SELECT source_order_id FROM web_intro_credits
                         WHERE buyer_user_id=? AND redeemed_for_order IS NULL
                         ORDER BY credited_at LIMIT 1""",(int(buyer_id),)).fetchone()
        if not row:
            return None
        changed=c.execute("""UPDATE web_intro_credits SET redeemed_for_order=?,redeemed_at=?
                             WHERE source_order_id=? AND redeemed_for_order IS NULL
                             RETURNING source_order_id""",
                          (str(for_order_id),current,row["source_order_id"])).fetchone()
        return changed["source_order_id"] if changed else None


def available_intro_credit(db, buyer_id):
    reconcile_intro_credits(db)
    with db() as c:
        row=c.execute("""SELECT source_order_id FROM web_intro_credits
                         WHERE buyer_user_id=? AND redeemed_for_order IS NULL
                         ORDER BY credited_at LIMIT 1""",(int(buyer_id),)).fetchone()
    return row["source_order_id"] if row else None


def restore_intro_credit(db, buyer_id, source_order_id, for_order_id):
    """Reinstate a credit if Telegram could not accept the replacement request."""
    with db() as c:
        c.execute("""UPDATE web_intro_credits
                     SET redeemed_for_order=NULL,redeemed_at=NULL
                     WHERE buyer_user_id=? AND source_order_id=?
                       AND redeemed_for_order=?""",
                  (int(buyer_id),str(source_order_id),str(for_order_id)))
