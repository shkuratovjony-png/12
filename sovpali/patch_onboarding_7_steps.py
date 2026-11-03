from pathlib import Path
from io import BytesIO
import base64
import shutil

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# === SOVPALI_ONBOARDING_7_STEPS ===
# Final local-only onboarding assets. During Docker build we materialize the
# approved intro image and normalize every onboarding JPEG. At runtime the bot
# reads ordinary JPEG files from /app/assets/onboarding; no network is used.
ROOT = Path(__file__).resolve().parent
ONBOARDING = ROOT / 'assets' / 'onboarding'
B64_DIR = ROOT / 'assets' / 'onboarding_b64'
W, H = 1200, 675


def _save_normalized(raw: bytes, dest: Path) -> None:
    with Image.open(BytesIO(raw)) as src:
        src.load()
        im = ImageOps.exif_transpose(src).convert('RGB')
    im = ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    # Mild finishing only: preserve the approved artwork, avoid artificial effects.
    im = ImageEnhance.Sharpness(im).enhance(1.08)
    im = ImageEnhance.Contrast(im).enhance(1.02)
    im = im.filter(ImageFilter.UnsharpMask(radius=0.7, percent=55, threshold=3))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.tmp.jpg')
    im.save(tmp, 'JPEG', quality=90, optimize=True, progressive=True, subsampling=0)
    tmp.replace(dest)
    # Hard validation: a broken image must fail the build instead of reaching Telegram.
    with Image.open(dest) as check:
        check.verify()
    with Image.open(dest) as check:
        if check.size != (W, H) or check.format != 'JPEG':
            raise RuntimeError(f'bad onboarding image: {dest.name} {check.size} {check.format}')


# Materialize the approved intro into a normal JPEG file.
intro_b64 = B64_DIR / '00_intro.b64'
welcome = ONBOARDING / '00_welcome.jpg'
if intro_b64.is_file():
    encoded = ''.join(intro_b64.read_text(encoding='ascii').split())
    _save_normalized(base64.b64decode(encoded, validate=True), welcome)
elif not welcome.is_file():
    raise SystemExit('missing local welcome image source')

# Normalize all seven step images to one Telegram-friendly 16:9 size.
step_files = [
    '01_gender.jpg',
    '02_birth.jpg',
    '03_place.jpg',
    '04_city.jpg',
    '05_goal.jpg',
    '06_priority.jpg',
    '07_photo.jpg',
]
for name in step_files:
    path = ONBOARDING / name
    if not path.is_file():
        raise SystemExit(f'missing onboarding image: {name}')
    _save_normalized(path.read_bytes(), path)

# The staging representation is not needed in the runtime image.
if B64_DIR.is_dir():
    shutil.rmtree(B64_DIR)

final_files = ['00_welcome.jpg', *step_files]
for name in final_files:
    path = ONBOARDING / name
    with Image.open(path) as check:
        check.load()
        if check.size != (W, H) or check.format != 'JPEG':
            raise SystemExit(f'onboarding validation failed: {name}')
    print(f'[onboarding] {name}: {path.stat().st_size} bytes, {W}x{H}', flush=True)

# Wire local files into visuals.py.
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
    'welcome': 'assets/onboarding/00_welcome.jpg',
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
