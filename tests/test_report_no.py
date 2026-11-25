from app.extensions import db
from app.services import report_no


def test_sequential_per_day(app):
    with app.app_context():
        a = report_no.issue("2026-11-24")
        b = report_no.issue("2026-11-24")
        c = report_no.issue("2026-11-25")
        db.session.commit()
    assert (a, b, c) == ("RSI-20261124-001", "RSI-20261124-002", "RSI-20261125-001")


def test_no_duplicates(app):
    with app.app_context():
        nos = [report_no.issue("2026-01-01") for _ in range(30)]
        db.session.commit()
    assert len(set(nos)) == 30 and nos[-1] == "RSI-20260101-030"
