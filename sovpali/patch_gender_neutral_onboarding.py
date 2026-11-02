from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

replacements = {
    '<b>Ты мужчина или женщина?</b>': '<b>Укажи пол</b>',
    '<b>Напиши дату рождения</b> в формате ДД.ММ.ГГГГ.': '<b>Укажи дату рождения</b> в формате ДД.ММ.ГГГГ.',
    '<b>В каком городе ты родился?</b>': '<b>Укажи город рождения</b>',
    '<b>В каком городе ты живёшь сейчас?</b>': '<b>В каком городе ты живёшь сейчас?</b>',
    'Даже очень похожие люди не совпадут, если один ищет семью, а второй — только лёгкое общение. Поэтому сначала синхронизируем намерения.': 'Даже очень похожие люди могут не совпасть, если цели отношений разные — например, семья и лёгкое общение. Поэтому сначала синхронизируем намерения.',
}

changed = 0
for old, new in replacements.items():
    if old in s:
        s = s.replace(old, new)
        changed += 1

# Remove direct-address gendered variants from onboarding copy if future patches
# reintroduce them in these exact common forms.
for old, new in [
    ('ты родился?', 'город рождения?'),
    ('ты родилась?', 'город рождения?'),
    ('ты готов?', 'можно продолжать?'),
    ('ты готова?', 'можно продолжать?'),
]:
    if old in s:
        s = s.replace(old, new)
        changed += 1

p.write_text(s, encoding='utf-8')
print(f'[build] gender-neutral onboarding copy applied: {changed} replacements', flush=True)
