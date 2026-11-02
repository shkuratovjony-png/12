from io import BytesIO
from functools import lru_cache
from pathlib import Path
from PIL import Image

ASSETS = Path(__file__).resolve().parent / 'assets'
THEMES = {
    'welcome':'welcome', 'gender':'gender', 'looking':'gender', 'birth':'birth',
    'time':'birth', 'place':'place', 'city':'city', 'goal':'goal',
    'priority':'priority', 'photo':'photo', 'matching':'matching',
    'profile':'profile', 'pairs':'pairs', 'chats':'chats', 'more':'more'
}


def _bright_fallback() -> bytes:
    im = Image.new('RGB', (960, 540), (178, 92, 116))
    bio = BytesIO(); im.save(bio, 'JPEG', quality=84); return bio.getvalue()


@lru_cache(maxsize=32)
def visual(theme: str) -> bytes:
    name = THEMES.get(theme, 'welcome')
    p = ASSETS / f'{name}.jpg'
    try:
        data = p.read_bytes()
        Image.open(BytesIO(data)).verify()
        return data
    except Exception:
        return _bright_fallback()


def animation(theme: str = 'welcome') -> bytes:
    # Сохранено только для обратной совместимости; фактически всегда используется фото.
    return visual(theme)


def as_file(data: bytes, name: str):
    bio = BytesIO(data)
    if name.lower().endswith('.gif'):
        name = name[:-4] + '.jpg'
    bio.name = name
    return bio
