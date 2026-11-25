"""사진·서명 이미지 처리.

- Pillow로 실제 이미지인지 확인 (확장자·MIME만으로 판단하지 않음)
- exif_transpose로 회전 보정 후 EXIF 제거 재저장 (GPS 노출 방지)
- 긴 변 최대 1920px, JPEG 품질 80, 썸네일 320px
- 파일명은 서버가 UUID로 생성
- 실제 저장은 services/storage.py (로컬 폴더 또는 Supabase Storage)
"""
import base64
import binascii
import hashlib
import io
import uuid

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

from ..timeutil import utcnow
from . import storage

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_SIDE = 1920
THUMB_SIDE = 320
JPEG_QUALITY = 80
Image.MAX_IMAGE_PIXELS = 60_000_000  # 압축 폭탄 방지


class ImageError(ValueError):
    pass


def upload_root():
    return storage._local_root()


def abs_path(rel):
    """로컬 저장소 전용 경로 (테스트·백업용)."""
    try:
        return storage.local_path(rel)
    except storage.StorageError:
        raise ImageError("잘못된 경로")


def _open_verified(data: bytes):
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ImageError("이미지 파일이 아닙니다.")
    if fmt not in ALLOWED_FORMATS:
        raise ImageError("JPEG, PNG, WebP 형식만 첨부할 수 있습니다.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ImageError("이미지를 읽을 수 없습니다.")
    return img, fmt


def _to_rgb(img):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _jpeg_bytes(img) -> bytes:
    buf = io.BytesIO()
    # exif 인자를 넘기지 않으면 메타데이터 없이 저장된다
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _store(rel, data, mime):
    try:
        storage.save(rel, data, mime)
    except storage.StorageError as e:
        current_app.logger.error("storage save failed: %s", e)
        raise ImageError("사진을 저장하지 못했습니다. 잠시 후 다시 시도하세요.")


def process_photo(data: bytes):
    """업로드 바이트 → 저장. 반환: 메타정보 dict."""
    img, _fmt = _open_verified(data)
    img = ImageOps.exif_transpose(img)
    img = _to_rgb(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    now = utcnow()
    name = uuid.uuid4().hex
    rel = f"{now:%Y}/{now:%m}/{name}.jpg"
    rel_thumb = f"{now:%Y}/{now:%m}/{name}_t.jpg"
    raw = _jpeg_bytes(img)
    th = img.copy()
    th.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.LANCZOS)
    _store(rel, raw, "image/jpeg")
    _store(rel_thumb, _jpeg_bytes(th), "image/jpeg")
    return {
        "stored_path": rel,
        "thumb_path": rel_thumb,
        "mime": "image/jpeg",
        "size_bytes": len(raw),
        "width": img.width,
        "height": img.height,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def save_signature(data_url: str):
    prefix = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ImageError("서명 이미지 형식이 올바르지 않습니다.")
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise ImageError("서명 이미지 형식이 올바르지 않습니다.")
    if len(raw) > current_app.config["SIGNATURE_MAX_BYTES"]:
        raise ImageError("서명 이미지가 너무 큽니다.")
    img, fmt = _open_verified(raw)
    if fmt != "PNG":
        raise ImageError("서명은 PNG 형식이어야 합니다.")
    if img.width > 4000 or img.height > 2000:
        raise ImageError("서명 이미지 크기가 올바르지 않습니다.")
    rel = f"signatures/{uuid.uuid4().hex}.png"
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    _store(rel, buf.getvalue(), "image/png")
    return rel


def save_raw(rel, data: bytes, mime: str):
    _store(rel, data, mime)


def read_file(rel) -> bytes:
    return storage.read(rel)


def remove_file(rel):
    storage.delete(rel)


def file_to_data_url(rel, mime):
    try:
        return f"data:{mime};base64," + base64.b64encode(storage.read(rel)).decode()
    except (OSError, storage.StorageError):
        return None


def decode_data_url(s):
    """data:image/...;base64,.... → bytes (불러오기용)."""
    if not isinstance(s, str) or not s.startswith("data:image/") or ";base64," not in s:
        return None
    try:
        return base64.b64decode(s.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        return None
