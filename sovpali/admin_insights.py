"""Read-only Sovpali business dashboard on existing verified project records.

No billing writes, matchmaking changes, or Telegram API calls. All user input is
bound as parameters. Order values are recorded gross, before processor fees,
refunds not yet reflected by the provider, taxes or affiliate payments.
"""
from datetime import datetime, timezone


def _count(row, key):
    return int(row.get(key) or 0)


def snapshot(query, since, data):
    """Collect cohort and payment metrics; each definition is explicit in UI."""
    raw_page = data.get("insights_page", 1)
    try:
        page = int(raw_page)
    except (ValueError, TypeError):
        raise ValueError("Неверный номер страницы")
    if not 1 <= page <= 10000:
        raise ValueError("Неверный номер страницы")
    search = str(data.get("insights_search", ""))[:100].strip()
    pattern = "%" + search.lstrip("@") + "%"

    users = query("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE p.gender='Мужчина') AS men,
               COUNT(*) FILTER (WHERE p.gender='Женщина') AS women,
               COUNT(*) FILTER (WHERE p.user_id IS NOT NULL) AS completed,
               COUNT(*) FILTER (WHERE p.user_id IS NULL) AS without_profile
        FROM users u LEFT JOIN profiles p ON p.user_id=u.id
        WHERE u.created_at::timestamptz >= %s
    """, (since,))[0]

    deliveries = query("""
        SELECT COUNT(*) AS delivered,
               COUNT(DISTINCT recipient_user_id) AS recipients
        FROM match_pushes
        WHERE status='sent'
          AND NULLIF(sent_at,'')::timestamptz >= %s
    """, (since,))[0]

    payments = query("""
        SELECT COUNT(DISTINCT o.order_id) AS orders,
               COUNT(DISTINCT b.buyer_user_id) AS buyers,
               COALESCE(SUM(o.amount_kopecks),0) AS revenue_kopecks
        FROM billing_web_orders o
        JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
        WHERE o.status='paid' AND o.currency_code='643'
          AND NULLIF(o.paid_at,'')::timestamptz >= %s
    """, (since,))[0]

    products = query("""
        SELECT o.product_key AS sku, COUNT(DISTINCT o.order_id) AS orders,
               COALESCE(SUM(o.amount_kopecks),0) AS revenue_kopecks
        FROM billing_web_orders o
        JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
        WHERE o.status='paid' AND o.currency_code='643'
          AND NULLIF(o.paid_at,'')::timestamptz >= %s
        GROUP BY o.product_key ORDER BY revenue_kopecks DESC
    """, (since,))

    # User detail totals are lifetime per user; selection is by signup cohort.
    # LATERAL aggregates use existing recipient/viewer and buyer IDs.
    where = """u.created_at::timestamptz >= %s
         AND (COALESCE(p.name,'') ILIKE %s
              OR COALESCE(u.first_name,'') ILIKE %s
              OR COALESCE(u.username,'') ILIKE %s
              OR u.tg_id::text LIKE %s)"""
    args = (since, pattern, pattern, pattern, "%" + search + "%")
    total_rows = query("""
        SELECT COUNT(*) AS n
        FROM users u LEFT JOIN profiles p ON p.user_id=u.id
        WHERE """ + where, args)[0]["n"]
    people = query("""
        SELECT u.id, u.tg_id,
               COALESCE(NULLIF(p.name,''),NULLIF(u.first_name,''),u.username,'Имя не указано') AS name,
               u.username, COALESCE(p.gender,'Анкета не заполнена') AS gender,
               COALESCE(p.city,'') AS city,
               COALESCE(m.delivered,0) AS delivered,
               COALESCE(v.views,0) AS views,
               COALESCE(o.orders,0) AS paid_orders,
               COALESCE(o.spent_kopecks,0) AS spent_kopecks,
               o.last_paid_at, u.created_at
        FROM users u LEFT JOIN profiles p ON p.user_id=u.id
        LEFT JOIN LATERAL (
          SELECT COUNT(*) AS delivered FROM match_pushes m
          WHERE m.recipient_user_id=u.id AND m.status='sent'
        ) m ON true
        LEFT JOIN LATERAL (
          SELECT COUNT(*) AS views FROM match_push_views v
          WHERE v.viewer_user_id=u.id
        ) v ON true
        LEFT JOIN LATERAL (
          SELECT COUNT(DISTINCT o.order_id) AS orders,
                 COALESCE(SUM(o.amount_kopecks),0) AS spent_kopecks,
                 MAX(o.paid_at) AS last_paid_at
          FROM billing_web_orders o
          JOIN web_purchase_bindings b ON b.billing_order_id=o.order_id
          WHERE b.buyer_user_id=u.id AND o.status='paid' AND o.currency_code='643'
        ) o ON true
        WHERE """ + where + """
        ORDER BY u.created_at DESC,u.id DESC LIMIT 50 OFFSET %s
    """, args + ((page - 1) * 50,))

    partner_summary = query("""
        SELECT COUNT(DISTINCT partner_user_id) AS partners,
               COALESCE(SUM(commission_kopecks) FILTER
                  (WHERE status<>'reversed'),0) AS accrued_kopecks,
               COALESCE(SUM(commission_kopecks) FILTER
                  (WHERE status='paid'),0) AS paid_kopecks,
               COALESCE(SUM(commission_kopecks) FILTER
                  (WHERE status='requested'),0) AS requested_kopecks,
               COALESCE(SUM(commission_kopecks) FILTER
                  (WHERE status='earned' AND available_at <= %s),0) AS available_kopecks,
               COALESCE(SUM(commission_kopecks) FILTER
                  (WHERE status='earned' AND available_at > %s),0) AS hold_kopecks
        FROM affiliate_rewards
    """, (datetime.now(timezone.utc).isoformat(timespec="seconds"),) * 2)[0]

    partners = query("""
        SELECT c.partner_user_id, u.tg_id,u.username,
               COALESCE(r.invited,0) AS invited,
               COALESCE(a.orders,0) AS paid_orders,
               COALESCE(a.earned_kopecks,0) AS earned_kopecks,
               COALESCE(a.paid_kopecks,0) AS paid_kopecks,
               COALESCE(a.requested_kopecks,0) AS requested_kopecks
        FROM affiliate_codes c JOIN users u ON u.id=c.partner_user_id
        LEFT JOIN (
           SELECT partner_user_id,COUNT(*) AS invited
           FROM affiliate_referrals GROUP BY partner_user_id
        ) r ON r.partner_user_id=c.partner_user_id
        LEFT JOIN (
           SELECT partner_user_id,
                  COUNT(*) FILTER (WHERE status<>'reversed') AS orders,
                  COALESCE(SUM(commission_kopecks) FILTER
                    (WHERE status<>'reversed'),0) AS earned_kopecks,
                  COALESCE(SUM(commission_kopecks) FILTER
                    (WHERE status='paid'),0) AS paid_kopecks,
                  COALESCE(SUM(commission_kopecks) FILTER
                    (WHERE status='requested'),0) AS requested_kopecks
           FROM affiliate_rewards GROUP BY partner_user_id
        ) a ON a.partner_user_id=c.partner_user_id
        ORDER BY earned_kopecks DESC, invited DESC,c.partner_user_id LIMIT 50
    """)

    payouts = query("""
        SELECT p.request_id,u.username,u.tg_id,p.amount_kopecks,
               p.legal_status,p.status,p.requested_at,p.completed_at,p.bank_reference
        FROM affiliate_payout_requests p JOIN users u ON u.id=p.partner_user_id
        ORDER BY p.requested_at DESC LIMIT 30
    """)

    return {
        "users": users, "deliveries": deliveries, "payments": payments,
        "products": products, "people": people,
        "total": int(total_rows), "page": page,
        "partners": partners, "partner_summary": partner_summary,
        "payouts": payouts,
        "definitions": {
            "cohort": "Регистрации за выбранный период",
            "matching": "Успешно отправленные автоматические рекомендации за период",
            "payment": "Подтверждённые платежи по дате оплаты за период",
            "people": "Показатели за всё время каждого пользователя из выбранной когорты",
            "affiliate": "Партнёрские показатели за всё время",
        }
    }
