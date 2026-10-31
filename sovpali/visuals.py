from io import BytesIO
from functools import lru_cache
import requests
from PIL import Image, ImageOps, ImageEnhance

# Реальные editorial/cinematic фотографии с Unsplash.
# На сервере они скачиваются один раз, приводятся к 16:9 и кешируются.
PHOTO_IDS = {
    'welcome': 'QJYtAE3or-s',       # пара, кинематографичный красный свет
    'gender': '7ifJOPWjdo4',        # пара в тёмной editorial-сцене
    'looking': 'iiizowST2ZM',       # пара + городской skyline
    'birth': 'oQ3HCGqIA7w',         # астрономические часы / зодиак
    'time': 'KQSmqtj65Rk',          # золотые часы, premium close-up
    'place': 'OHxGotO7r7w',         # кинематографичный ночной город
    'city': 'yFD7UytTePE',          # огни большого города
    'goal': 'g_WaXHTSlEE',          # золотые кольца на тёмном фоне
    'priority': 'nXPtHBURBY0',      # руки тянутся друг к другу
    'photo': 'QJYtAE3or-s',         # эмоциональный портрет пары
    'matching': 'nXPtHBURBY0',      # визуальная метафора совпадения
    'profile': '7ifJOPWjdo4',       # editorial-портрет пары
    'pairs': 'QJYtAE3or-s',         # близость / отношения
    'chats': 'OHxGotO7r7w',         # городской lifestyle
    'more': 'r1CwE8FpIeM',          # luxury watch / детали
}

FALLBACK_ID = 'QJYtAE3or-s'
W, H = 1280, 720


def _download(photo_id: str) -> bytes:
    url = f'https://unsplash.com/photos/{photo_id}/download?force=true'
    r = requests.get(
        url,
        timeout=20,
        allow_redirects=True,
        headers={'User-Agent': 'SovpaliBot/2.1'},
    )
    r.raise_for_status()
    return r.content


def _prepare(raw: bytes) -> bytes:
    im = Image.open(BytesIO(raw)).convert('RGB')
    im = ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    # Чуть более дорогая editorial-подача: мягко приглушаем пересветы и насыщенность.
    im = ImageEnhance.Contrast(im).enhance(1.04)
    im = ImageEnhance.Color(im).enhance(0.92)
    bio = BytesIO()
    im.save(bio, 'JPEG', quality=88, optimize=True, progressive=True)
    return bio.getvalue()


@lru_cache(maxsize=32)
def visual(theme: str) -> bytes:
    photo_id = PHOTO_IDS.get(theme, FALLBACK_ID)
    try:
        return _prepare(_download(photo_id))
    except Exception:
        if photo_id != FALLBACK_ID:
            try:
                return _prepare(_download(FALLBACK_ID))
            except Exception:
                pass
        # Последняя страховка: нейтральный тёмный кадр, чтобы бот не падал.
        im = Image.new('RGB', (W, H), (16, 14, 20))
        bio = BytesIO(); im.save(bio, 'JPEG', quality=88); return bio.getvalue()


def animation(theme: str = 'welcome') -> bytes:
    # Оставлено только для обратной совместимости старого кода.
    # Возвращаем тот же статичный кадр — а Docker-патч переключает отправку на reply_photo.
    return visual(theme)


def as_file(data: bytes, name: str):
    bio = BytesIO(data)
    # Даже если старый вызов передал .gif, физически отправляем JPEG через patched send_card.
    if name.lower().endswith('.gif'):
        name = name[:-4] + '.jpg'
    bio.name = name
    return bio
