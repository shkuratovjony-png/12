"""Make old Telegram-chat birth date registration accept digits only.

The Mini App now has day/month/year native dropdowns. This patch covers
users who already started the old chat ConversationHandler flow.
"""
from pathlib import Path

p=Path("app.py")
s=p.read_text(encoding="utf-8")
old="    s=update.message.text.strip()\n    try:\n        d=datetime.strptime(s,'%d.%m.%Y');"
new="""    s=update.message.text.strip()
    digits=''.join(ch for ch in s if ch.isdigit())
    if len(digits)==8 and (s==digits or s.count('.')==2 or '/' in s or '-' in s):
        s=digits[:2]+'.'+digits[2:4]+'.'+digits[4:]
    try:
        d=datetime.strptime(s,'%d.%m.%Y');"""
if s.count(old)!=1:raise SystemExit("birth-date fallback anchor missing")
s=s.replace(old,new,1)
old_prompt="Напиши дату рождения</b> в формате ДД.ММ.ГГГГ.\\nНапример: 05.01.1990"
new_prompt="Отправь дату рождения <b>восемью цифрами, без точек</b>.\\nНапример: <b>05011990</b>. Я сам поставлю точки."
if old_prompt in s:
    s=s.replace(old_prompt,new_prompt,1)
else:
    # Earlier onboarding patches can rewrite copy. The date parser remains the source of truth.
    print("[build] date prompt variant differs; parser fix still applied",flush=True)
old_retry="Напиши дату в формате ДД.ММ.ГГГГ, например 05.01.1990"
if old_retry in s:
    s=s.replace(old_retry,"Введи 8 цифр даты без точек, например 05011990. Дата должна быть настоящей, тебе должно быть не меньше 18 лет.",1)
p.write_text(s,encoding="utf-8")
print("[build] legacy date accepts 8 digits without punctuation",flush=True)
