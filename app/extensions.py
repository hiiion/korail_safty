"""Flask 확장 객체 (앱 팩토리에서 init_app)."""
import sqlite3

from flask import has_request_context, request
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


# ---------------------------------------------------------------------------
# SQLite 연결 설정
#  - 연결마다 PRAGMA 적용 (외래키, WAL, busy_timeout)
#  - 드라이버 자동 트랜잭션을 끄고, 트랜잭션 시작을 직접 제어한다.
#    쓰기 요청(POST/PATCH/DELETE)과 CLI·테스트에서는 BEGIN IMMEDIATE를 사용해
#    관리번호 발급 같은 "읽고-증가" 작업이 경합 없이 직렬화되도록 한다.
# ---------------------------------------------------------------------------
@event.listens_for(Engine, "connect")
def _sqlite_on_connect(dbapi_conn, _record):
    if not isinstance(dbapi_conn, sqlite3.Connection):
        return
    dbapi_conn.isolation_level = None
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA busy_timeout = 5000")
    cur.close()


def _want_immediate() -> bool:
    if not has_request_context():
        return True
    return request.method not in ("GET", "HEAD", "OPTIONS")


@event.listens_for(Engine, "begin")
def _sqlite_on_begin(conn):
    if conn.dialect.name != "sqlite":
        return
    conn.exec_driver_sql("BEGIN IMMEDIATE" if _want_immediate() else "BEGIN")
