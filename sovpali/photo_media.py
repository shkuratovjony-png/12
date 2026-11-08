"""Verified Telegram profile photos and user-uploaded JPEG portraits.

Uploads live in the existing persistent database (not ephemeral Render files).
All uploads are decoded/re-encoded with Pillow to strip EXIF/GPS and bound sizes.
Only the logged-in Telegram owner may alter their portrait. Pair viewers use the
existing signed, eligibility-checked pair photo route.
"""
import io
from datetime import datetime,timezone
import requests
from PIL import Image,ImageOps,UnidentifiedImageError

MAX_INPUT=8*1024*1024
MAX_PIXELS=32_000_000
LOCAL_MARKER="local:portrait-v1"

def ensure_schema(db):
    with db() as c:
        c.executescript("""
          CREATE TABLE IF NOT EXISTS profile_photo_uploads (
            user_id BIGINT PRIMARY KEY, image_bytes BYTEA NOT NULL,
            mime TEXT NOT NULL, updated_at TEXT NOT NULL
          );
        """)

def normalize_image(raw):
    if not raw or len(raw)>MAX_INPUT:raise ValueError("Размер фотографии должен быть до 8 МБ.")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.width<80 or img.height<80 or img.width*img.height>MAX_PIXELS:
                raise ValueError("Выбери фото размером от 80 пикселей, не слишком большое.")
            if img.format not in ("JPEG","PNG","WEBP","HEIF","HEIC"):
                raise ValueError("Выбери фотографию JPG, PNG или WebP.")
            img=ImageOps.exif_transpose(img)
            if img.mode in ("RGBA","P"):
                rgba=img.convert("RGBA")
                bg=Image.new("RGB",rgba.size,(255,255,255))
                bg.paste(rgba,mask=rgba.getchannel("A"))
                img=bg
            else:img=img.convert("RGB")
            img.thumbnail((1280,1280),Image.Resampling.LANCZOS)
            dest=io.BytesIO()
            img.save(dest,format="JPEG",quality=83,optimize=True,progressive=True)
            data=dest.getvalue()
            if len(data)>1200000:raise ValueError("Фото не удалось уменьшить. Попробуй другое.")
            return data
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
        raise ValueError("Не удалось прочитать файл. Попробуй JPG или PNG.") from None

def save_local(db,uid,raw):
    pic=normalize_image(raw)
    ensure_schema(db)
    with db() as c:
        c.execute("""INSERT INTO profile_photo_uploads(user_id,image_bytes,mime,updated_at)
          VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
          image_bytes=excluded.image_bytes,mime=excluded.mime,updated_at=excluded.updated_at""",
          (int(uid),pic,"image/jpeg",datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return len(pic)

def has_local(db,uid):
    with db() as c:
        return bool(c.execute("SELECT 1 FROM profile_photo_uploads WHERE user_id=?",(int(uid),)).fetchone())

def get_local(db,uid):
    with db() as c:
        row=c.execute("SELECT image_bytes,mime FROM profile_photo_uploads WHERE user_id=?",(int(uid),)).fetchone()
        if not row:return None
        return bytes(row["image_bytes"]),str(row["mime"])

def delete_local(db,uid):
    with db() as c:
        c.execute("DELETE FROM profile_photo_uploads WHERE user_id=?",(int(uid),))

def telegram_photo_id(tg_id,bot_token,timeout=4):
    if not bot_token:return None
    response=requests.get("https://api.telegram.org/bot"+bot_token+"/getUserProfilePhotos",
                          params={"user_id":int(tg_id),"limit":1},timeout=timeout)
    response.raise_for_status()
    payload=response.json()
    if not payload.get("ok"):return None
    photos=payload.get("result",{}).get("photos") or []
    return str(photos[0][-1].get("file_id")) if photos and photos[0] else None

def telegram_photo_bytes(file_id,bot_token,timeout=6):
    if not file_id or not bot_token:return None
    info=requests.get("https://api.telegram.org/bot"+bot_token+"/getFile",
                      params={"file_id":str(file_id)},timeout=timeout)
    info.raise_for_status()
    data=info.json()
    path=data.get("result",{}).get("file_path") if data.get("ok") else None
    if not isinstance(path,str) or not path or path.startswith("/") or ".." in path:
        return None
    photo=requests.get("https://api.telegram.org/file/bot"+bot_token+"/"+path,timeout=timeout)
    photo.raise_for_status()
    if not photo.content or len(photo.content)>MAX_INPUT: return None
    content=photo.content
    return content,("image/png" if content.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg")
