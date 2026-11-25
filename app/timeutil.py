"""시간 처리: DB는 UTC ISO 8601 문자열, 화면은 Asia/Seoul."""
from datetime import date, datetime, timedelta, timezone

try:  # Windows에는 tz 데이터베이스가 없을 수 있다 → 고정 +09:00로 대체 (한국은 서머타임 없음)
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:  # pragma: no cover
    KST = timezone(timedelta(hours=9), "KST")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def parse_iso(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def to_kst(s):
    d = parse_iso(s) if isinstance(s, str) else s
    return d.astimezone(KST) if d else None


def fmt_kst(s, with_sec=False) -> str:
    d = to_kst(s)
    if not d:
        return "-"
    return d.strftime("%Y-%m-%d %H:%M:%S" if with_sec else "%Y-%m-%d %H:%M")


def today_kst() -> str:
    return utcnow().astimezone(KST).date().isoformat()


def today_kst_date() -> date:
    return utcnow().astimezone(KST).date()


def iso_to_ms(s):
    d = parse_iso(s)
    return int(d.timestamp() * 1000) if d else None


def ms_to_iso(ms):
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def duration_text(start, end) -> str:
    a, b = parse_iso(start), parse_iso(end)
    if not a or not b or b < a:
        return "-"
    m = max(1, round((b - a).total_seconds() / 60))
    h = m // 60
    return f"{h}시간 {m % 60}분" if h else f"{m}분"


def is_valid_date(s) -> bool:
    if not isinstance(s, str) or len(s) != 10:
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False
