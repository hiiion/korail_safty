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


def database_url() -> str:
    """DATABASE_URL 정규화. Supabase가 주는 postgres:// / postgresql:// 주소는 psycopg 3 드라이버로 연결한다."""
    # Vercel의 Supabase 연동은 POSTGRES_URL(트랜잭션 풀러)을 넣어 준다.
    url = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "sqlite:///app.db").strip()
    if url.startswith("postgres") and "?" in url:
        # psycopg가 모르는 연동 전용 파라미터(supa=...)는 제거하고 sslmode 등만 남긴다.
        from urllib.parse import parse_qsl, urlencode

        head, q = url.split("?", 1)
        keep = [(k, v) for k, v in parse_qsl(q) if k != "supa"]
        url = head + ("?" + urlencode(keep) if keep else "")
    for head in ("postgres://", "postgresql://"):
        if url.startswith(head):
            return "postgresql+psycopg://" + url[len(head):]
    return url


def engine_options(url: str) -> dict:
    if not url.startswith("postgresql"):
        return {}
    from sqlalchemy.pool import NullPool

    # 서버리스(Vercel)에서는 요청마다 함수가 뜨고 꺼지므로 앱 쪽 풀을 두지 않고
    # Supabase 연결 풀러(Supavisor, 트랜잭션 모드 6543 포트)에 맡긴다.
    # 트랜잭션 모드 풀러는 prepared statement를 지원하지 않으므로 끈다.
    return {"poolclass": NullPool, "connect_args": {"prepare_threshold": None}}


def base_config() -> dict:
    url = database_url()
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY") or None,
        # 상대 sqlite 경로는 Flask-SQLAlchemy가 instance/ 폴더 기준으로 해석한다.
        "SQLALCHEMY_DATABASE_URI": url,
        "SQLALCHEMY_ENGINE_OPTIONS": engine_options(url),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "UPLOAD_DIR": _str("UPLOAD_DIR", "uploads"),
        # SUPABASE_URL이 있으면 사진·서명을 Supabase Storage(비공개 버킷)에 저장한다.
        "SUPABASE_URL": _str("SUPABASE_URL", "").rstrip("/"),
        "SUPABASE_SERVICE_KEY": _str("SUPABASE_SERVICE_KEY", "") or _str("SUPABASE_SERVICE_ROLE_KEY", ""),
        "SUPABASE_BUCKET": _str("SUPABASE_BUCKET", "photos"),
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
