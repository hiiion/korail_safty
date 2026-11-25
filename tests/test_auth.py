from app.extensions import db
from app.models import AuditLog, User
from conftest import PW, login


def test_login_success_and_failure(app, make_client):
    c = make_client()
    assert login(c, "insp", "wrongpass1").status_code == 401
    r = login(c, "insp")
    assert r.status_code == 302
    assert c.get("/api/inspections").status_code == 200
    with app.app_context():
        acts = [a.action for a in AuditLog.query.all()]
    assert "login.fail" in acts and "login.success" in acts


def test_lock_after_five_failures(app, make_client):
    c = make_client()
    for _ in range(5):
        login(c, "insp", "wrongpass1")
    with app.app_context():
        u = User.query.filter_by(username="insp").first()
        assert u.locked_until is not None
        assert AuditLog.query.filter_by(action="login.locked").count() == 1
    # 올바른 비밀번호도 잠금 중에는 거부
    r = login(c, "insp")
    assert r.status_code == 401
    assert "잠겼" in r.get_data(as_text=True)


def test_password_hashed(app):
    with app.app_context():
        u = User.query.filter_by(username="insp").first()
        assert u.password_hash != PW
        assert u.password_hash.startswith(("scrypt:", "pbkdf2:"))
        assert u.check_password(PW)


def test_must_change_password(app, make_client):
    with app.app_context():
        u = User.query.filter_by(username="insp").first()
        u.must_change_password = 1
        db.session.commit()
    c = make_client()
    r = login(c, "insp")
    assert r.status_code == 302 and r.headers["Location"].endswith("/password")
    # 변경 전에는 다른 화면·API 접근 차단
    assert c.get("/").status_code == 302
    assert c.get("/api/inspections").status_code == 403
    # 규칙 위반 비밀번호 거부
    r = c.post("/password", data={"current_password": PW, "new_password": "short", "new_password2": "short"})
    assert "8자 이상" in r.get_data(as_text=True)
    r = c.post("/password", data={"current_password": PW, "new_password": "NewPass123", "new_password2": "NewPass123"})
    assert r.status_code == 302
    assert c.get("/api/inspections").status_code == 200


def test_logout_clears_session(make_client):
    c = make_client("insp")
    assert c.post("/logout").status_code == 302
    assert c.get("/api/inspections").status_code == 401


def test_security_headers(make_client):
    r = make_client().get("/login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
