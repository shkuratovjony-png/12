from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] single-payer-intro: bot anchor not found')

block = r'''
# --- Single-payer introduction reservation model ----------------------------
# Product rule:
# 1) only the initiator ever pays;
# 2) the other person only receives an accept/decline request;
# 3) the pair and both participants are transactionally locked before checkout,
#    so the same pair/person cannot be sold twice at the same time;
# 4) the request is sent only after a verified payment webhook marks the order paid.
# Payments remain hidden while payments_live=0; these primitives are ready for
# the payment-provider integration.
IP_RESERVE_MINUTES = int(os.getenv('INTRO_RESERVE_MINUTES', '12'))
IP_RESPONSE_HOURS = int(os.getenv('INTRO_RESPONSE_HOURS', '24'))
IP_ACTIVE_STATUSES = ('reserved','payment_pending','paid','awaiting_response','accepted')


def ip_now():
    return datetime.utcnow().replace(microsecond=0)


def ip_iso(dt=None):
    return (dt or ip_now()).isoformat()


def ip_parse(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace('Z','+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def ip_init_db():
    with db() as c:
        if USE_POSTGRES:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS intro_orders(
                id BIGSERIAL PRIMARY KEY,
                pair_low BIGINT NOT NULL,
                pair_high BIGINT NOT NULL,
                buyer_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount_rub INTEGER NOT NULL DEFAULT 100,
                status TEXT NOT NULL DEFAULT 'reserved',
                provider_order_id TEXT,
                reservation_expires_at TEXT,
                response_expires_at TEXT,
                created_at TEXT NOT NULL,
                paid_at TEXT,
                responded_at TEXT,
                closed_at TEXT,
                credit_reissued INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_intro_orders_buyer ON intro_orders(buyer_user_id);
            CREATE INDEX IF NOT EXISTS idx_intro_orders_target ON intro_orders(target_user_id);
            CREATE INDEX IF NOT EXISTS idx_intro_orders_status ON intro_orders(status);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_intro_active_pair
              ON intro_orders(pair_low,pair_high)
              WHERE status IN ('reserved','payment_pending','paid','awaiting_response','accepted');
            CREATE TABLE IF NOT EXISTS intro_participant_locks(
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                order_id BIGINT NOT NULL REFERENCES intro_orders(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_intro_locks_order ON intro_participant_locks(order_id);
            ''')
        else:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS intro_orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_low INTEGER NOT NULL,
                pair_high INTEGER NOT NULL,
                buyer_user_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                amount_rub INTEGER NOT NULL DEFAULT 100,
                status TEXT NOT NULL DEFAULT 'reserved',
                provider_order_id TEXT,
                reservation_expires_at TEXT,
                response_expires_at TEXT,
                created_at TEXT NOT NULL,
                paid_at TEXT,
                responded_at TEXT,
                closed_at TEXT,
                credit_reissued INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_intro_orders_buyer ON intro_orders(buyer_user_id);
            CREATE INDEX IF NOT EXISTS idx_intro_orders_target ON intro_orders(target_user_id);
            CREATE INDEX IF NOT EXISTS idx_intro_orders_status ON intro_orders(status);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_intro_active_pair
              ON intro_orders(pair_low,pair_high)
              WHERE status IN ('reserved','payment_pending','paid','awaiting_response','accepted');
            CREATE TABLE IF NOT EXISTS intro_participant_locks(
                user_id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_intro_locks_order ON intro_participant_locks(order_id);
            ''')


def ip_cleanup_expired():
    nowv = ip_now()
    rows = many("SELECT * FROM intro_orders WHERE status IN ('reserved','payment_pending') AND reservation_expires_at IS NOT NULL")
    for r in rows:
        ex = ip_parse(r['reservation_expires_at'])
        if ex and ex <= nowv:
            oid = int(r['id'])
            execute("UPDATE intro_orders SET status='expired',closed_at=? WHERE id=?", (ip_iso(), oid))
            execute('DELETE FROM intro_participant_locks WHERE order_id=?', (oid,))
    rows = many("SELECT * FROM intro_orders WHERE status='awaiting_response' AND response_expires_at IS NOT NULL")
    for r in rows:
        ex = ip_parse(r['response_expires_at'])
        if ex and ex <= nowv:
            oid = int(r['id'])
            execute("UPDATE intro_orders SET status='expired',closed_at=?,credit_reissued=1 WHERE id=?", (ip_iso(), oid))
            execute('DELETE FROM intro_participant_locks WHERE order_id=?', (oid,))
            try:
                audit(int(r['buyer_user_id']), 'intro_credit_reissued', {'order_id': oid, 'reason': 'no_response'})
            except Exception:
                pass


def ip_active_for_user(uid):
    ip_cleanup_expired()
    return one('''SELECT o.* FROM intro_participant_locks l
                  JOIN intro_orders o ON o.id=l.order_id
                  WHERE l.user_id=? AND o.status IN ('reserved','payment_pending','paid','awaiting_response','accepted')
                  ORDER BY o.id DESC LIMIT 1''', (int(uid),))


def ip_active_pair(a, b):
    ip_cleanup_expired()
    lo, hi = sorted((int(a), int(b)))
    return one('''SELECT * FROM intro_orders WHERE pair_low=? AND pair_high=?
                  AND status IN ('reserved','payment_pending','paid','awaiting_response','accepted')
                  ORDER BY id DESC LIMIT 1''', (lo, hi))


def ip_reserve_intro(buyer_uid, target_uid, amount_rub=None):
    """Atomically reserve both people before opening a checkout.

    Returns ('reserved', order) or ('busy', existing_order_or_none).
    The two participant-lock inserts make opposite-direction simultaneous buys
    impossible: A->B and B->A cannot both commit.
    """
    buyer_uid, target_uid = int(buyer_uid), int(target_uid)
    if buyer_uid == target_uid:
        return 'busy', None
    ip_cleanup_expired()
    current = ip_active_pair(buyer_uid, target_uid)
    if current:
        return 'busy', current
    amount = int(amount_rub or setting('unlock_price_rub','100') or 100)
    lo, hi = sorted((buyer_uid, target_uid))
    created = ip_iso()
    expires = ip_iso(ip_now() + timedelta(minutes=IP_RESERVE_MINUTES))
    try:
        with db() as c:
            cur = c.execute('''INSERT INTO intro_orders(
                pair_low,pair_high,buyer_user_id,target_user_id,amount_rub,status,
                reservation_expires_at,created_at)
                VALUES(?,?,?,?,?,'reserved',?,?) RETURNING id''',
                (lo,hi,buyer_uid,target_uid,amount,expires,created))
            oid = int(cur.fetchone()['id'])
            # PRIMARY KEY(user_id) is the concurrency guard. If either person is
            # already reserved/paid/awaiting a response, this transaction rolls back.
            c.execute('INSERT INTO intro_participant_locks(user_id,order_id,role,expires_at,created_at) VALUES(?,?,?,?,?)',
                      (buyer_uid,oid,'buyer',expires,created))
            c.execute('INSERT INTO intro_participant_locks(user_id,order_id,role,expires_at,created_at) VALUES(?,?,?,?,?)',
                      (target_uid,oid,'target',expires,created))
    except Exception as exc:
        print(f'[intro] reserve conflict buyer={buyer_uid} target={target_uid}: {type(exc).__name__}: {exc}', flush=True)
        return 'busy', ip_active_pair(buyer_uid, target_uid) or ip_active_for_user(target_uid) or ip_active_for_user(buyer_uid)
    row = one('SELECT * FROM intro_orders WHERE id=?', (oid,))
    try:
        audit(buyer_uid,'intro_reserved',{'order_id':oid,'target_user_id':target_uid,'amount_rub':amount})
    except Exception:
        pass
    return 'reserved', row


def ip_mark_payment_pending(order_id, provider_order_id=None):
    execute("UPDATE intro_orders SET status='payment_pending',provider_order_id=COALESCE(?,provider_order_id) WHERE id=? AND status='reserved'",
            (provider_order_id, int(order_id)))
    return one('SELECT * FROM intro_orders WHERE id=?', (int(order_id),))


def ip_mark_paid(order_id, provider_order_id=None):
    """Idempotent post-webhook transition. Does not trust Telegram callbacks."""
    oid = int(order_id)
    row = one('SELECT * FROM intro_orders WHERE id=?', (oid,))
    if not row:
        return None
    if str(row['status']) in ('paid','awaiting_response','accepted'):
        return row
    if str(row['status']) not in ('reserved','payment_pending'):
        return None
    response_expires = ip_iso(ip_now() + timedelta(hours=IP_RESPONSE_HOURS))
    execute("""UPDATE intro_orders SET status='paid',paid_at=?,provider_order_id=COALESCE(?,provider_order_id),
               reservation_expires_at=NULL,response_expires_at=? WHERE id=? AND status IN ('reserved','payment_pending')""",
            (ip_iso(), provider_order_id, response_expires, oid))
    # Paid introductions stay locked until the other person answers.
    execute('UPDATE intro_participant_locks SET expires_at=? WHERE order_id=?', (response_expires, oid))
    return one('SELECT * FROM intro_orders WHERE id=?', (oid,))


def ip_mark_request_sent(order_id):
    execute("UPDATE intro_orders SET status='awaiting_response' WHERE id=? AND status='paid'", (int(order_id),))
    return one('SELECT * FROM intro_orders WHERE id=?', (int(order_id),))


def ip_finish(order_id, accepted):
    oid = int(order_id)
    row = one('SELECT * FROM intro_orders WHERE id=?', (oid,))
    if not row:
        return None
    if accepted:
        execute("UPDATE intro_orders SET status='accepted',responded_at=? WHERE id=?", (ip_iso(), oid))
        # Keep accepted pair locked until they explicitly end the introduction.
    else:
        execute("UPDATE intro_orders SET status='declined',responded_at=?,closed_at=?,credit_reissued=1 WHERE id=?",
                (ip_iso(),ip_iso(),oid))
        execute('DELETE FROM intro_participant_locks WHERE order_id=?', (oid,))
        try:
            audit(int(row['buyer_user_id']),'intro_credit_reissued',{'order_id':oid,'reason':'declined'})
        except Exception:
            pass
    return one('SELECT * FROM intro_orders WHERE id=?', (oid,))


def ip_close(order_id):
    oid = int(order_id)
    execute("UPDATE intro_orders SET status='closed',closed_at=? WHERE id=?", (ip_iso(), oid))
    execute('DELETE FROM intro_participant_locks WHERE order_id=?', (oid,))


def ip_purchase_copy(order):
    target = profile(int(order['target_user_id'])) if order else None
    name = html.escape(str(target['name'])) if target else 'этого человека'
    amount = int(order['amount_rub']) if order else int(setting('unlock_price_rub','100') or 100)
    return (f'💖 <b>Знакомство с {name}</b>\n\n'
            f'Платит только тот, кто первым выбирает знакомство — <b>{amount} ₽</b>. '
            'Второй человек ничего не оплачивает: после подтверждённой оплаты ему приходит запрос, '
            'и контакт открывается только если он тоже скажет «да».\n\n'
            'Пока идёт оплата и ожидание ответа, эта пара закреплена только за вами двумя.')


# Initialize reservation tables with the rest of the application schema.
_ip_old_init_db = init_db
def init_db():
    _ip_old_init_db()
    ip_init_db()
    try:
        ip_cleanup_expired()
    except Exception as exc:
        print(f'[intro] startup cleanup warning: {type(exc).__name__}: {exc}', flush=True)


# Payment-ready wrapper for My Pair. During the current free product test the
# existing free request remains unchanged. Once payments_live=1, this function
# is the only permitted entry point before creating a provider checkout.
def ip_prepare_my_pair_purchase(buyer_uid, target_uid, amount_rub=None):
    if setting('payments_live','0') != '1':
        return 'payments_off', None
    return ip_reserve_intro(buyer_uid, target_uid, amount_rub)
# ---------------------------------------------------------------------------

'''

# timedelta is already imported by the exclusive-matching patch in the built app.
s = s.replace(anchor, block + anchor, 1)
p.write_text(s, encoding='utf-8')
print('[build] single-payer intro reservation + concurrency locks applied', flush=True)
