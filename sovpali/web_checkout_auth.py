"""Frictionless signed-link checkout session for the standalone Sovpali site.

The personal pair URL is already HMAC-signed by the Telegram bot and carries
the fixed viewer ID and candidate ID. We validate it, bind the viewer to the
Flask signed browser session, and keep the existing CSRF, purchase ownership,
bank confirmation and consent rules. No Telegram OTP / extra login page.

Security tradeoff: a personal link is a bearer credential. Do not share it.
Never treat an unsigned user ID in a query or form as a purchase identity.
"""
from datetime import datetime, timedelta, timezone

from flask import session
from pair_web import _load as load_pair_token


def _now():
    return datetime.now(timezone.utc)


def register_web_checkout_auth(app, ns):
    def claim_signed_pair(buyer):
        token = session.get("billing_pair_token")
        if not token:
            return False
        try:
            viewer, candidate = load_pair_token(token, ns["FLASK_SECRET"])
            if int(viewer) != int(buyer) or int(viewer) == int(candidate):
                return False
        except Exception:
            return False
        session["billing_signed_viewer"] = int(buyer)
        session["billing_signed_until"] = (
            _now() + timedelta(hours=12)
        ).isoformat(timespec="seconds")
        # Clear legacy OTP flags from existing browser sessions.
        session.pop("billing_authenticated_uid", None)
        session.pop("billing_auth_until", None)
        session.pop("web_auth_last_sent", None)
        return True

    def verified_signed_pair(buyer):
        token = session.get("billing_pair_token")
        if not token:
            return False
        try:
            viewer, candidate = load_pair_token(token, ns["FLASK_SECRET"])
            if (int(viewer) != int(buyer) or int(viewer) == int(candidate)
                    or int(session.get("billing_signed_viewer", -1)) != int(buyer)):
                return False
            until = datetime.fromisoformat(session.get("billing_signed_until", ""))
            if until.tzinfo is None:
                return False
            return until > _now()
        except Exception:
            return False

    ns["web_owner_claim"] = claim_signed_pair
    ns["web_owner_verified"] = verified_signed_pair
    # The old /billing/auth/start/* and /billing/auth/verify/* endpoints are
    # deliberately NOT registered, so no OTP page can reappear.
