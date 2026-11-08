"""Keep first welcome image prominent; brief caption for the legacy route and Mini App entry."""
from pathlib import Path
p=Path("app.py")
s=p.read_text(encoding="utf-8")
start=s.index('    text=("✨ <b>Совпали</b>')
end=s.index("    await send_card(update.effective_message,'welcome',text,",start)
s=s[:start]+"""    text=('💞 <b>Совпали</b>\\n\\n'
          'Подбираем пару по астрологии, нумерологии и совместимости. '
          'Знакомство здесь не случайно.\\n\\n'
          '<b>Тебе уже есть 18 лет?</b>')
"""+s[end:]
old="'💞 <b>Совпали</b>\\n\\nЗнакомства, где важны не только фотографии, но и ваши ценности, астрология и нумерология.\\n\\nОткрой личное пространство — заполнить анкету можно прямо здесь.'"
new="'💞 <b>Совпали</b>\\n\\nТвоя пара по астрологии, нумерологии и жизненной совместимости.\\n\\nОткрой Mini App и узнай, кто подходит именно тебе.'"
if old in s:s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8")
print("[build] welcome caption shortened for image and Mini App entry",flush=True)
