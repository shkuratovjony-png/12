"""Session binding for a personal bot-signed link, without Telegram OTP.

The Telegram bot generates a URLSafeTimedSerializer token containing the viewer
and candidate IDs. A valid, nonexpired signature is a bearer capability. The
checkout binds that signed token to the browser's Flask-signed session for
12 hours; bank verification, CSRF and recipient consent remain independent.

Important: a forwarded personal URL grants the same capability. Never expose
purchase links publicly, and do not construe URL possession as independent
Telegram login proof.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from flask import session
from pair_web import _load as load_pair_token


def _now():
    return datetime.now(timezone.utc)


def _pair_fingerprint(token, secret):
    return hmac.new(str(secret).encode("utf-8"), str(token).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def register_web_checkout_auth(app, ns):
    def claim_signed_pair(viewer_id):
        token = session.get("billing_pair_token")
        if not token:
            return False
        try:
            viewer, candidate = load_pair_token(token, ns["FLASK_SECRET"])
            if int(viewer) != int(viewer_id) or int(viewer) == int(candidate):
                return False
            ns_profile = ns.get("profile")
            ns_user = ns.get("user")
            if not callable(ns_profile) or not callable(ns_user):
                return False
            if not ns_profile(int(viewer)) or not ns_profile(int(candidate)):
                return False
            if not ns_user(int(viewer)) or not ns_user(int(candidate)):
                return False
        except Exception:
            return False
        session["billing_signed_viewer"] = int(viewer)
        session["billing_signed_pair"] = _pair_fingerprint(token, ns["FLASK_SECRET"])
        session["billing_signed_until"] = (
            _now() + timedelta(hours=12)).isoformat(timespec="seconds")
        # Legacy authorization was for a separate code screen. Do not use it.
        session.pop("billing_authenticated_uid", None)
        session.pop("billing_auth_until", None)
        session.pop("web_auth_last_sent", None)
        return True

    def verified_signed_pair(viewer_id):
        token = session.get("billing_pair_token")
        if not token:
            return False
        try:
            viewer, candidate = load_pair_token(token, ns["FLASK_SECRET"])
            if int(viewer) != int(viewer_id) or int(viewer) == int(candidate):
                return False
            if int(session.get("billing_signed_viewer", -1)) != int(viewer):
                return False
            expected = _pair_fingerprint(token, ns["FLASK_SECRET"])
            if not hmac.compare_digest(
                    str(session.get("billing_signed_pair", "")), expected):
                return False
            expiry = datetime.fromisoformat(session.get("billing_signed_until", ""))
            return expiry.tzinfo is not None and expiry > _now()
        except Exception:
            return False

    ns["web_owner_claim"] = claim_signed_pair
    ns["web_owner_verified"] = verified_signed_pair
