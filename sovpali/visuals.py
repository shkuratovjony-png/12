from io import BytesIO
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance

W, H = 1200, 675
ATLAS = Path(__file__).with_name('assets_atlas.jpg')
CELL_W, CELL_H = 300, 169

# Один встроенный атлас с нашими сгенерированными фотографиями.
# 0 — пара + астрология, 1 — пара + место/пейзаж,
# 2 — пара + современный город, 3 — пара + естественное селфи.
THEME_CELL = {
    'welcome': 0,
    'gender': 3,
    'birth': 0,
    'place': 1,
    'city': 2,
    'goal': 1,
    'priority': 0,
    'photo': 3,
    'matching': 0,
    'profile': 3,
    'pairs': 1,
    'chats': 2,
    'more': 3,
}

@lru_cache(maxsize=8)
def _atlas():
    return Image.open(ATLAS).convert('RGB')

@lru_cache(maxsize=32)
def visual(theme: str) -> bytes:
    idx = THEME_CELL.get(theme, 0)
    src = _atlas()
    left = idx * CELL_W
    frame = src.crop((left, 0, left + CELL_W, CELL_H))
    frame = ImageOps.fit(frame, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    frame = ImageEnhance.Color(frame).enhance(1.08)
    frame = ImageEnhance.Contrast(frame).enhance(1.04)
    bio = BytesIO()
    frame.save(bio, 'JPEG', quality=88, optimize=True, progressive=True)
    return bio.getvalue()

def animation(theme: str = 'welcome') -> bytes:
    return visual(theme)

def as_file(data: bytes, name: str):
    bio = BytesIO(data)
    bio.name = name.rsplit('.', 1)[0] + '.jpg'
    return bio
