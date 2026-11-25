"""관리번호 발급: RSI-YYYYMMDD-NNN.

report_sequences 테이블의 날짜별 일련번호를 트랜잭션 안에서 증가시킨다.
쓰기 요청의 트랜잭션은 BEGIN IMMEDIATE로 시작하므로(extensions.py),
동시에 확인 요청이 들어와도 읽기-증가가 직렬화되어 중복이 생기지 않는다.
"""
from flask import current_app
from sqlalchemy import text

from ..extensions import db
from ..timeutil import today_kst


def issue(date_iso=None):
    day = (date_iso or today_kst()).replace("-", "")
    prefix = current_app.config.get("REPORT_NO_PREFIX") or "RSI"
    # 단일 UPSERT 문으로 원자적으로 증가 (SQLite 3.35+). BEGIN IMMEDIATE 트랜잭션으로 동시 발급이 직렬화된다.
    seq = db.session.execute(
        text(
            "INSERT INTO report_sequences (date_key, last_seq) VALUES (:k, 1) "
            "ON CONFLICT (date_key) DO UPDATE SET last_seq = report_sequences.last_seq + 1 "
            "RETURNING last_seq"
        ),
        {"k": day},
    ).scalar_one()
    return f"{prefix}-{day}-{seq:03d}"
