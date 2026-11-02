from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
anchor = "bot=Application.builder().token(TOKEN).build()"
if anchor not in s:
    raise SystemExit('[build] priority/natal copy: bot anchor not found')

block = r'''
# --- Priority + basic natal-profile personalization -------------------------
# We do not claim a full natal chart because exact birth time is not collected.
# The "basic natal profile" uses the birth-date astrology layer already present
# in the matcher, plus the user's explicitly selected relationship priority.

def pn_clamp(v, lo=60, hi=98):
    return max(lo, min(hi, int(v)))


def pn_priority_pct(viewer, candidate):
    same = str(viewer['priority']) == str(candidate['priority'])
    base = 93 if same else 72
    try:
        if viewer['goal'] == candidate['goal']:
            base += 2
        if lifepath(viewer['birth_date']) == lifepath(candidate['birth_date']):
            base += 2
    except Exception:
        pass
    return pn_clamp(base)


def pn_astro_pct(a, b):
    try:
        za, zb = zodiac(a['birth_date']), zodiac(b['birth_date'])
        ea, eb = ELEMENT[za], ELEMENT[zb]
        value = 90 if eb in GOOD[ea] else 74
        la, lb = lifepath(a['birth_date']), lifepath(b['birth_date'])
        if la == lb:
            value += 5
        elif abs(la-lb) in (1,3):
            value += 3
        # deterministic tiny variation avoids every compatible pair showing 90
        value += (sum(ord(ch) for ch in (za + zb)) % 3)
        return pn_clamp(value)
    except Exception:
        return 78


def pn_priority_copy(viewer, candidate):
    pr = str(viewer['priority'] or '').strip()
    pct = pn_priority_pct(viewer, candidate)
    templates = {
        'Страсть': (
            '🔥', 'Страсть',
            'Ты сам отметил страсть как главное. Здесь совпадение особенно сильное: '
            'вам обоим важны химия, притяжение и отношения, в которых друг к другу действительно тянет.'
        ),
        'Семья': (
            '👨‍👩‍👧', 'Семья',
            'Ты сам поставил семью на первое место. Здесь вы смотрите в одну сторону: '
            'не просто познакомиться, а строить устойчивую близость и совместную жизнь.'
        ),
        'Любовь': (
            '❤️', 'Любовь',
            'Для тебя главное — чувства. У этой пары сильное совпадение именно здесь: '
            'вам обоим важна эмоциональная близость, а не просто удобный формат отношений.'
        ),
        'Ценности': (
            '🧭', 'Общие ценности',
            'Ты выбрал общие ценности главным критерием. Здесь у вас похожая внутренняя настройка: '
            'важно не только нравиться друг другу, но и одинаково смотреть на сам смысл отношений.'
        ),
        'Опора': (
            '🤝', 'Спокойствие и опора',
            'Ты выбрал надёжность и опору. Здесь совпадение сильное именно по этому запросу: '
            'вам обоим ближе отношения, где можно доверять человеку и чувствовать устойчивость.'
        ),
    }
    emoji, label, body = templates.get(pr, ('💎', pr or 'Главный критерий', 'По твоему главному критерию у этой пары сильное совпадение.'))
    return f'{emoji} <b>{html.escape(label)} — {pct}%</b>\n{body}'


def pn_astro_copy(a, b):
    pct = pn_astro_pct(a, b)
    if pct >= 93:
        tail = 'Сочетание редкое. Выглядит так, будто эта встреча совсем не случайна.'
    elif pct >= 88:
        tail = 'Очень сильное сочетание. Тут есть ощущение той самой «неслучайной» встречи.'
    else:
        tail = 'Есть заметная астрологическая связка — хороший дополнительный сигнал к обычной совместимости.'
    try:
        za, zb = zodiac(a['birth_date']), zodiac(b['birth_date'])
        signs = f'{za} + {zb}. '
    except Exception:
        signs = ''
    return f'✨ <b>Базовый натальный профиль — {pct}%</b>\n{html.escape(signs)}{tail}'


def pn_match_block(viewer, candidate):
    return pn_priority_copy(viewer, candidate) + '\n\n' + pn_astro_copy(viewer, candidate)


# Enrich initial exclusive offer.
_pn_old_xm_personal_copy = xm_personal_copy
def xm_personal_copy(viewer, candidate, score_value):
    base = _pn_old_xm_personal_copy(viewer, candidate, score_value)
    return base + '\n\n' + pn_match_block(viewer, candidate)


# Enrich the message received by the second side after interest.
_pn_old_xm_interest_copy = xm_interest_copy
def xm_interest_copy(subject, interested, score_value):
    base = _pn_old_xm_interest_copy(subject, interested, score_value)
    return base + '\n\n' + pn_match_block(subject, interested)


# Enrich lifecycle reminders so each reminder anchors to what the user chose.
_pn_old_lf_offer_text = lf_offer_text
def lf_offer_text(uid, o, c):
    base = _pn_old_lf_offer_text(uid, o, c)
    viewer = profile(uid)
    return base + ('\n\n' + pn_match_block(viewer, c) if viewer and c else '')


_pn_old_lf_interest_text = lf_interest_text
def lf_interest_text(uid, o, c):
    base = _pn_old_lf_interest_text(uid, o, c)
    viewer = profile(uid)
    return base + ('\n\n' + pn_match_block(viewer, c) if viewer and c else '')


_pn_old_lf_unlock_text = lf_unlock_text
def lf_unlock_text(uid, o, c):
    base = _pn_old_lf_unlock_text(uid, o, c)
    viewer = profile(uid)
    if not viewer or not c:
        return base
    return base + '\n\n' + pn_priority_copy(viewer, c) + '\n\n' + pn_astro_copy(viewer, c)
# ---------------------------------------------------------------------------

'''

s = s.replace(anchor, block + anchor, 1)
p.write_text(s, encoding='utf-8')
print('[build] priority-specific + basic natal-profile copy applied', flush=True)
