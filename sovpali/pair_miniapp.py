"""Telegram presentation adapter. No matching or billing mutations."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from telegram import InlineKeyboardButton, WebAppInfo

def pair_button(text, url):
    parts = urlsplit(url)
    if not parts.path.startswith('/s/m/') or parts.scheme != 'https':
        return InlineKeyboardButton(text, url=url)
    path = parts.path.replace('/s/m/', '/s/mini/', 1)
    return InlineKeyboardButton(text.replace(' на сайте', ''), web_app=WebAppInfo(
        url=urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))))

def validate_init_data(raw, bot_token, now=None):
    if not raw or len(raw)>16384 or not bot_token:
        raise ValueError('Missing Telegram credentials')
    fields = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    data = dict(fields)
    if len(fields)!=len(data): raise ValueError('Duplicate field')
    signature = data.pop('hash', '')
    secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    check = '\n'.join(f'{key}={data[key]}' for key in sorted(data))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected): raise ValueError('Invalid signature')
    age = (time.time() if now is None else now)-int(data.get('auth_date',0))
    if age < -30 or age > 3600: raise ValueError('Expired authorization')
    uid = json.loads(data['user'])['id']
    if type(uid) is not int or uid<=0: raise ValueError('Invalid user')
    return uid
