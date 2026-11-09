from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] smart-frequency: bot anchor not found')

block = r"""
# --- Smart frequency + directional pair ownership ---------------------------
# Product rules for launch:
# - auto recommendations: max 2/day, >=86%, >=6h apart, daytime Yekaterinburg;
# - My Pair is user-pulled and does not count as a push;
# - one pair has one initiator direction at a time;
# - paid introductions: max 3 confirmed purchases/day per buyer;
# - a target can have only one paid incoming introduction at a time, while a
#   buyer may initiate up to the daily cap to different targets.

SM_DEFAULTS = {
    'auto_match_daily_cap': '2',
    'auto_match_cooldown_hours': '6',
    'auto_match_min_score': '86',
    'engagement_daily_cap': '2',
    'pair_direction_hold_hours': '4',
    'intro_daily_purchase_cap': '3',
    'intro_open_outgoing_cap': '3',
}


def sm_now():
    return datetime.utcnow().replace(microsecond=0)


def sm_iso(dt=None):
    return (dt or sm_now()).isoformat()


def sm_parse(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def sm_int(key, default):
    try:
        return int(setting(key, str(default)) or default)
    except Exception:
        return int(default)


def sm_local_day_bounds():
    # Yekaterinburg = UTC+5. Store/query timestamps in UTC.
    local = sm_now() + timedelta(hours=5)
    start = datetime(local.year, local.month, local.day) - timedelta(hours=5)
    return start, start + timedelta(days=1)


def sm_init_db():
    with db() as c:
        if USE_POSTGRES:
            c.executescript("CREATE TABLE IF NOT EXISTS pair_direction_locks(pair_low BIGINT NOT NULL,pair_high BIGINT NOT NULL,owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,source TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(pair_low,pair_high)); CREATE INDEX IF NOT EXISTS idx_pair_direction_owner ON pair_direction_locks(owner_user_id); CREATE INDEX IF NOT EXISTS idx_pair_direction_target ON pair_direction_locks(target_user_id);")
        else:
            c.executescript("CREATE TABLE IF NOT EXISTS pair_direction_locks(pair_low INTEGER NOT NULL,pair_high INTEGER NOT NULL,owner_user_id INTEGER NOT NULL,target_user_id INTEGER NOT NULL,source TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(pair_low,pair_high)); CREATE INDEX IF NOT EXISTS idx_pair_direction_owner ON pair_direction_locks(owner_user_id); CREATE INDEX IF NOT EXISTS idx_pair_direction_target ON pair_direction_locks(target_user_id);")
    for k, v in SM_DEFAULTS.items():
        try:
            if not one('SELECT key FROM settings WHERE key=?', (k,)):
                set_setting(k, v)
        except Exception:
            pass


def sm_cleanup_direction():
    try:
        execute('DELETE FROM pair_direction_locks WHERE expires_at<=?', (sm_iso(),))
    except Exception:
        pass


def sm_direction_owner(a, b):
    a, b = int(a), int(b)
    lo, hi = sorted((a, b))
    # A paid order is the strongest source of truth: its buyer owns the direction.
    try:
        r = one("SELECT buyer_user_id FROM intro_orders WHERE pair_low=? AND pair_high=? AND status IN ('reserved','payment_pending','paid','awaiting_response','accepted') ORDER BY id DESC LIMIT 1", (lo, hi))
        if r:
            return int(r['buyer_user_id'])
    except Exception:
        pass
    # The current one-way push engine permanently assigns every delivered
    # unordered pair. Without this check the opposite person could still
    # start a paid order by opening an old/forwarded signed pair link.
    try:
        r = one("SELECT recipient_user_id FROM match_pair_directions WHERE pair_low=? AND pair_high=? AND status IN ('reserved','sent') LIMIT 1", (lo, hi))
        if r:
            return int(r['recipient_user_id'])
    except Exception:
        pass
    # A manual communication request already has an initiator.
    try:
        r = one("SELECT requester_user_id FROM communication_requests WHERE pair_low=? AND pair_high=? AND status IN ('pending','accepted') ORDER BY id DESC LIMIT 1", (lo, hi))
        if r:
            return int(r['requester_user_id'])
    except Exception:
        pass
    # For automatic matching, the person who received the recommendation is the initiator.
    try:
        marks = ','.join('?' for _ in XM_ACTIVE)
        r = one(f"SELECT recipient_user_id FROM match_offers WHERE pair_low=? AND pair_high=? AND status IN ({marks}) ORDER BY id DESC LIMIT 1", (lo, hi) + tuple(XM_ACTIVE))
        if r:
            return int(r['recipient_user_id'])
    except Exception:
        pass
    sm_cleanup_direction()
    try:
        r = one('SELECT owner_user_id FROM pair_direction_locks WHERE pair_low=? AND pair_high=? LIMIT 1', (lo, hi))
        return int(r['owner_user_id']) if r else None
    except Exception:
        return None


def sm_claim_direction(owner_uid, target_uid, source='manual', hours=None):
    owner_uid, target_uid = int(owner_uid), int(target_uid)
    if owner_uid == target_uid:
        return False
    existing_owner = sm_direction_owner(owner_uid, target_uid)
    if existing_owner is not None:
        return int(existing_owner) == owner_uid
    lo, hi = sorted((owner_uid, target_uid))
    hold = int(hours or sm_int('pair_direction_hold_hours', 4))
    expires = sm_iso(sm_now() + timedelta(hours=hold))
    created = sm_iso()
    try:
        execute('INSERT INTO pair_direction_locks(pair_low,pair_high,owner_user_id,target_user_id,source,expires_at,created_at) VALUES(?,?,?,?,?,?,?)',
                (lo, hi, owner_uid, target_uid, str(source), expires, created))
        return True
    except Exception:
        try:
            r = one('SELECT owner_user_id FROM pair_direction_locks WHERE pair_low=? AND pair_high=? LIMIT 1', (lo, hi))
            return bool(r and int(r['owner_user_id']) == owner_uid)
        except Exception:
            return False


def sm_auto_today(uid):
    start, end = sm_local_day_bounds()
    r = one("SELECT COUNT(*) c FROM match_offers WHERE recipient_user_id=? AND offered_at IS NOT NULL AND offered_at>=? AND offered_at<? AND status<>'send_failed'", (int(uid), sm_iso(start), sm_iso(end)))
    return int(r['c'] or 0) if r else 0


def sm_lifecycle_today(uid):
    start, end = sm_local_day_bounds()
    try:
        r = one('SELECT COUNT(*) c FROM lifecycle_sends WHERE user_id=? AND created_at>=? AND created_at<?', (int(uid), sm_iso(start), sm_iso(end)))
        return int(r['c'] or 0) if r else 0
    except Exception:
        return 0


def sm_marketing_today(uid):
    return sm_auto_today(uid) + sm_lifecycle_today(uid)


def sm_last_marketing(uid):
    vals = []
    try:
        r = one("SELECT offered_at v FROM match_offers WHERE recipient_user_id=? AND offered_at IS NOT NULL AND status<>'send_failed' ORDER BY offered_at DESC LIMIT 1", (int(uid),))
        if r and r['v']:
            vals.append(sm_parse(r['v']))
    except Exception:
        pass
    try:
        r = one('SELECT created_at v FROM lifecycle_sends WHERE user_id=? ORDER BY created_at DESC LIMIT 1', (int(uid),))
        if r and r['v']:
            vals.append(sm_parse(r['v']))
    except Exception:
        pass
    vals = [x for x in vals if x]
    return max(vals) if vals else None


def sm_auto_recipient_allowed(uid):
    uid = int(uid)
    # Don't send unsolicited automatic recommendations at night in launch city.
    local_hour = (sm_now() + timedelta(hours=5)).hour
    if local_hour < 10 or local_hour >= 22:
        return False
    if sm_auto_today(uid) >= sm_int('auto_match_daily_cap', 2):
        return False
    if sm_marketing_today(uid) >= sm_int('engagement_daily_cap', 2):
        return False
    last = sm_last_marketing(uid)
    if last and (sm_now() - last).total_seconds() < sm_int('auto_match_cooldown_hours', 6) * 3600:
        return False
    return True


# Filter automatic recipients by quality, frequency and directional ownership.
_sm_old_xm_candidates_for = xm_candidates_for
def xm_candidates_for(subject_uid):
    base = _sm_old_xm_candidates_for(subject_uid)
    out = []
    min_score = sm_int('auto_match_min_score', 86)
    source = profile(subject_uid)
    for sv, c in base:
        try:
            recipient_uid = int(c['user_id'])
            # A match on both relationship goal and key priority is strong
            # enough for a national introduction even without a city bonus.
            if int(sv) < min_score and not (source and source['goal'] == c['goal'] and source['priority'] == c['priority']):
                continue
            if not sm_auto_recipient_allowed(recipient_uid):
                continue
            owner = sm_direction_owner(subject_uid, recipient_uid)
            if owner is not None and int(owner) != recipient_uid:
                continue
            out.append((sv, c))
        except Exception:
            continue
    return out


# Claim direction immediately before an automatic recommendation is delivered.
_sm_old_xm_send_candidate = xm_send_candidate
async def xm_send_candidate(bot_api, offer_id, viewer, candidate, score_value):
    viewer_uid = int(viewer['user_id'])
    candidate_uid = int(candidate['user_id'])
    if not sm_claim_direction(viewer_uid, candidate_uid, 'auto', hours=24):
        raise RuntimeError('pair direction belongs to the other side')
    return await _sm_old_xm_send_candidate(bot_api, offer_id, viewer, candidate, score_value)


# My Pair remains pull-based, but the first viewer owns those pair directions
# for a short window. The reciprocal side gets other candidates instead.
_sm_old_mp_candidates = mp_candidates
def mp_candidates(uid, limit=3):
    uid = int(uid)
    base = _sm_old_mp_candidates(uid, max(12, int(limit) * 5))
    out = []
    for sv, c in base:
        cid = int(c['user_id'])
        owner = sm_direction_owner(uid, cid)
        if owner is not None and int(owner) != uid:
            continue
        if owner is None and not sm_claim_direction(uid, cid, 'my_pair'):
            continue
        out.append((sv, c))
        if len(out) >= int(limit):
            break
    return out


# Lifecycle reminders share the same global marketing cap. Transactional events
# (new request, accept/decline, payment confirmation) do not go through lf_send.
_sm_old_lf_send = lf_send
async def lf_send(bot_api, uid, segment, key, text, kb=None, offer_id=None):
    uid = int(uid)
    if sm_marketing_today(uid) >= sm_int('engagement_daily_cap', 2):
        return False
    last = sm_last_marketing(uid)
    if last and (sm_now() - last).total_seconds() < sm_int('auto_match_cooldown_hours', 6) * 3600:
        return False
    return await _sm_old_lf_send(bot_api, uid, segment, key, text, kb, offer_id)


def sm_paid_today(uid):
    start, end = sm_local_day_bounds()
    try:
        r = one("SELECT COUNT(*) c FROM intro_orders WHERE buyer_user_id=? AND paid_at IS NOT NULL AND paid_at>=? AND paid_at<?", (int(uid), sm_iso(start), sm_iso(end)))
        return int(r['c'] or 0) if r else 0
    except Exception:
        return 0


def sm_premium_requests_today(uid):
    """Count ALL sent Premium introductions, including declined/expired.

    Purchase grants three initiation opportunities per local calendar day,
    not unlimited retries. Unsent/failed reservations do not consume a slot.
    """
    uid=int(uid)
    try:
        engine=globals().get("MATCH_PUSH_ENGINE")
        if engine is not None:
            _clock,_zone,start,end=engine.local_bounds(uid)
        else:
            first,last=sm_local_day_bounds()
            start,end=sm_iso(first),sm_iso(last)
        row=one("""SELECT COUNT(*) AS c FROM intro_orders
            WHERE buyer_user_id=? AND created_at>=? AND created_at<?
              AND status IN ('paid','awaiting_response','accepted','declined','expired')""",
            (uid,start,end))
        return int(row["c"] or 0) if row else 0
    except Exception as exc:
        print("[intro] premium count unavailable: "+type(exc).__name__,flush=True)
        return 3  # Fail closed: never issue unlimited free Premium requests.

def sm_open_outgoing(uid):
    try:
        r = one("SELECT COUNT(*) c FROM intro_orders WHERE buyer_user_id=? AND status IN ('reserved','payment_pending','paid','awaiting_response')", (int(uid),))
        return int(r['c'] or 0) if r else 0
    except Exception:
        return 0


# Replace reservation semantics: target is exclusive, buyer can have up to 3
# different outgoing introductions. Pair uniqueness still prevents A->B and B->A
# from both committing.
def ip_reserve_intro(buyer_uid, target_uid, amount_rub=None):
    buyer_uid, target_uid = int(buyer_uid), int(target_uid)
    if buyer_uid == target_uid:
        return 'busy', None
    ip_cleanup_expired()
    owner = sm_direction_owner(buyer_uid, target_uid)
    if owner is not None and int(owner) != buyer_uid:
        return 'busy', ip_active_pair(buyer_uid, target_uid)
    # Premium: three SENT introductions per local day, including requests
    # later declined or expired. Ordinary 100-RUB buys retain existing cap.
    try:
        from web_product_access import premium_active as _sm_premium_active
        premium_member=_sm_premium_active(db,buyer_uid)
    except Exception as exc:
        print("[intro] premium membership lookup failed: "+type(exc).__name__,flush=True)
        return 'daily_cap', None
    if premium_member:
        if sm_premium_requests_today(buyer_uid) >= 3:
            return 'daily_cap', None
    elif sm_paid_today(buyer_uid) >= sm_int('intro_daily_purchase_cap', 3):
        return 'daily_cap', None
    if sm_open_outgoing(buyer_uid) >= sm_int('intro_open_outgoing_cap', 3):
        return 'daily_cap', None
    current = ip_active_pair(buyer_uid, target_uid)
    if current:
        return 'busy', current
    # Target can have only one live incoming paid introduction.
    target_active = ip_active_for_user(target_uid)
    if target_active:
        return 'busy', target_active
    if not sm_claim_direction(buyer_uid, target_uid, 'checkout', hours=24):
        return 'busy', ip_active_pair(buyer_uid, target_uid)
    amount = int(amount_rub or setting('unlock_price_rub', '100') or 100)
    lo, hi = sorted((buyer_uid, target_uid))
    created = ip_iso()
    expires = ip_iso(ip_now() + timedelta(minutes=IP_RESERVE_MINUTES))
    try:
        with db() as c:
            cur = c.execute("INSERT INTO intro_orders(pair_low,pair_high,buyer_user_id,target_user_id,amount_rub,status,reservation_expires_at,created_at) VALUES(?,?,?,?,?,'reserved',?,?) RETURNING id",
                            (lo, hi, buyer_uid, target_uid, amount, expires, created))
            oid = int(cur.fetchone()['id'])
            c.execute('INSERT INTO intro_participant_locks(user_id,order_id,role,expires_at,created_at) VALUES(?,?,?,?,?)',
                      (target_uid, oid, 'target', expires, created))
    except Exception as exc:
        print(f'[intro] smart reserve conflict buyer={buyer_uid} target={target_uid}: {type(exc).__name__}: {exc}', flush=True)
        return 'busy', ip_active_pair(buyer_uid, target_uid) or ip_active_for_user(target_uid)
    row = one('SELECT * FROM intro_orders WHERE id=?', (oid,))
    try:
        audit(buyer_uid, 'intro_reserved', {'order_id': oid, 'target_user_id': target_uid, 'amount_rub': amount, 'smart_cap': sm_int('intro_daily_purchase_cap', 3)})
    except Exception:
        pass
    return 'reserved', row


# Free test requests also obey pair direction, so reciprocal clicks cannot race.
_sm_old_cr_send_request = cr_send_request
async def cr_send_request(ctx, requester_uid, target_uid, score_value):
    requester_uid, target_uid = int(requester_uid), int(target_uid)
    owner = sm_direction_owner(requester_uid, target_uid)
    if owner is not None and int(owner) != requester_uid:
        return 'failed', 0
    if owner is None and not sm_claim_direction(requester_uid, target_uid, 'free_request', hours=24):
        return 'failed', 0
    return await _sm_old_cr_send_request(ctx, requester_uid, target_uid, score_value)


_sm_old_init_db = init_db
def init_db():
    _sm_old_init_db()
    sm_init_db()
    sm_cleanup_direction()
# ---------------------------------------------------------------------------

"""

s = s.replace(anchor, block + anchor, 1)
p.write_text(s, encoding='utf-8')
print('[build] smart frequency caps + directional pair ownership applied', flush=True)
