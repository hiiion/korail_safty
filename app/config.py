"""환경설정 (.env에서 읽음)."""
import os
from datetime import timedelta


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _str(name, default):
    return (os.environ.get(name) or default).split("#")[0].strip()


def base_config() -> dict:
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY") or None,
        # 상대 sqlite 경로는 Flask-SQLAlchemy가 instance/ 폴더 기준으로 해석한다.
        "SQLALCHEMY_DATABASE_URI": _str("DATABASE_URL", "sqlite:///app.db"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "UPLOAD_DIR": _str("UPLOAD_DIR", "uploads"),
        "MAX_CONTENT_LENGTH": _int("MAX_CONTENT_LENGTH_MB", 15) * 1024 * 1024,
        "IMPORT_MAX_BYTES": 200 * 1024 * 1024,
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=_int("SESSION_HOURS", 8)),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # HTTPS 운영 환경에서는 1로 변경 (README 참고)
        "SESSION_COOKIE_SECURE": os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
        "WTF_CSRF_TIME_LIMIT": None,  # 세션 만료와 같이 간다
        "REMEMBER_COOKIE_DURATION": timedelta(seconds=0),
        "TIMEZONE": _str("TIMEZONE", "Asia/Seoul"),
        "REPORT_NO_PREFIX": _str("REPORT_NO_PREFIX", "RSI"),
        "LOGIN_MAX_FAIL": 5,
        "LOGIN_LOCK_MINUTES": 10,
        "MAX_PHOTOS_PER_ITEM": 10,
        "SIGNATURE_MAX_BYTES": 300 * 1024,
        "PAGE_SIZE": 20,
        "REPEAT_DAYS": 60,
    }
