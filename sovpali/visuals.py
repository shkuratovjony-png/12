from io import BytesIO
from functools import lru_cache
import requests
from PIL import Image, ImageOps, ImageEnhance

W, H = 1200, 675

# Надёжные прямые JPG-ссылки. На каждом экране — мужчина + женщина,
# а контекст меняется под вопрос: город, отношения, близость и т.д.
URLS = {
    'welcome': 'https://images.pexels.com/photos/2888147/pexels-photo-2888147.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'gender': 'https://images.pexels.com/photos/36488505/pexels-photo-36488505.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'birth': 'https://images.pexels.com/photos/38802627/pexels-photo-38802627.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'place': 'https://images.pexels.com/photos/4839779/pexels-photo-4839779.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'city': 'https://images.pexels.com/photos/40347568/pexels-photo-40347568.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'goal': 'https://images.pexels.com/photos/31559034/pexels-photo-31559034.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'priority': 'https://images.pexels.com/photos/28961734/pexels-photo-28961734.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'photo': 'https://images.pexels.com/photos/30452992/pexels-photo-30452992.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'matching': 'https://images.pexels.com/photos/33123055/pexels-photo-33123055.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'profile': 'https://images.pexels.com/photos/36488505/pexels-photo-36488505.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'pairs': 'https://images.pexels.com/photos/36986687/pexels-photo-36986687.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'chats': 'https://images.pexels.com/photos/40347567/pexels-photo-40347567.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'more': 'https://images.pexels.com/photos/18920147/pexels-photo-18920147.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
}

# Если одна конкретная фотография временно недоступна, пробуем запасные,
# а не отправляем пустой/чёрный экран.
FALLBACKS = [
    'https://images.pexels.com/photos/4015014/pexels-photo-4015014.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
    'https://images.pexels.com/photos/2888147/pexels-photo-2888147.jpeg?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop',
]


def _prepare(raw: bytes) -> bytes:
    im = Image.open(BytesIO(raw)).convert('RGB')
    im = ImageOps.fit(im, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    im = ImageEnhance.Color(im).enhance(1.10)
    im = ImageEnhance.Contrast(im).enhance(1.05)
    im = ImageEnhance.Brightness(im).enhance(1.03)
    out = BytesIO()
    im.save(out, 'JPEG', quality=88, optimize=True, progressive=True)
    return out.getvalue()


def _download(url: str) -> bytes:
    r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0 SovpaliBot/3.2'})
    r.raise_for_status()
    if 'image' not in r.headers.get('content-type', '').lower():
        raise ValueError('photo host returned non-image response')
    return _prepare(r.content)


@lru_cache(maxsize=32)
def visual(theme: str) -> bytes:
    urls = [URLS.get(theme, URLS['welcome'])] + FALLBACKS
    last_error = None
    for url in urls:
        try:
            return _download(url)
        except Exception as exc:
            last_error = exc
            print(f'[visual-download] {theme}: {exc}', flush=True)
    raise RuntimeError(f'No photo available for {theme}: {last_error}')


def animation(theme: str = 'welcome') -> bytes:
    return visual(theme)


def as_file(data: bytes, name: str):
    bio = BytesIO(data)
    bio.name = name.rsplit('.', 1)[0] + '.jpg'
    return bio
