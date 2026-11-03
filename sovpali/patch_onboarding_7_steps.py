from pathlib import Path

# === SOVPALI_ONBOARDING_7_STEPS ===
# Use seven optimized local JPEGs for onboarding instead of slicing/re-encoding the old atlas.
visuals = Path('visuals.py')
s = visuals.read_text(encoding='utf-8')

marker = '# === SOVPALI_ONBOARDING_IMAGES ==='
if marker not in s:
    s = s.replace(
        'from functools import lru_cache\n',
        'from functools import lru_cache\nfrom pathlib import Path\n',
        1,
    )
    old = """@lru_cache(maxsize=32)
def visual(theme: str) -> bytes:
    return _cell(_THEME_CELL.get(theme, 0), theme)
"""
    new = """# === SOVPALI_ONBOARDING_IMAGES ===
_STEP_IMAGE = {
    'gender': 'assets/onboarding/01_gender.jpg',
    'birth': 'assets/onboarding/02_birth.jpg',
    'place': 'assets/onboarding/03_place.jpg',
    'city': 'assets/onboarding/04_city.jpg',
    'goal': 'assets/onboarding/05_goal.jpg',
    'priority': 'assets/onboarding/06_priority.jpg',
    'photo': 'assets/onboarding/07_photo.jpg',
}

@lru_cache(maxsize=32)
def visual(theme: str) -> bytes:
    rel = _STEP_IMAGE.get(theme)
    if rel:
        path = Path(__file__).resolve().parent / rel
        if path.is_file():
            return path.read_bytes()
    return _cell(_THEME_CELL.get(theme, 0), theme)
"""
    if old not in s:
        raise SystemExit('onboarding images patch: visual() anchor not found')
    s = s.replace(old, new, 1)
    visuals.write_text(s, encoding='utf-8')
    print('onboarding images patch applied')
else:
    print('onboarding images patch already applied')

app = Path('app.py')
a = app.read_text(encoding='utf-8')

for step in range(1, 7):
    a = a.replace(f'Шаг {step} из 6', f'Шаг {step} из 7')

a = a.replace(
    '📸 <b>Последний штрих</b>\\n\\n',
    '📸 <b>Шаг 7 из 7</b>\\n\\n<b>Покажи себя</b>\\n\\n',
    1,
)

app.write_text(a, encoding='utf-8')
print('onboarding step counters updated to 7')
