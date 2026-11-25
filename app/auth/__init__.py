"""로그인 · 로그아웃 · 비밀번호 변경."""
import re
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import User
from ..services import audit
from ..timeutil import now_iso, parse_iso, utcnow

bp = Blueprint("auth", __name__)

PW_RULE_MSG = "비밀번호는 8자 이상이며 영문과 숫자를 모두 포함해야 합니다."


def password_ok(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) >= 8 and re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)


def _safe_next(target):
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("views.home"))
    error = None
    username = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first() if username else None
        locked_until = parse_iso(user.locked_until) if user else None
        if user and locked_until and locked_until > utcnow():
            mins = max(1, int((locked_until - utcnow()).total_seconds() // 60) + 1)
            error = f"로그인 5회 실패로 계정이 잠겼습니다. 약 {mins}분 후 다시 시도하세요."
            audit.log("login.fail", "user", user.id, {"username": username, "reason": "locked"}, user=user, commit=True)
        elif user and user.is_active and user.check_password(password):
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now_iso()
            session.clear()
            session.permanent = True
            login_user(user, remember=False)
            audit.log("login.success", "user", user.id, user=user, commit=True)
            nxt = _safe_next(request.args.get("next"))
            if user.must_change_password:
                return redirect(url_for("auth.password"))
            return redirect(nxt or url_for("views.home"))
        else:
            error = "아이디 또는 비밀번호가 올바르지 않습니다."
            if user:
                user.failed_login_count = (user.failed_login_count or 0) + 1
                detail = {"username": username, "count": user.failed_login_count}
                if user.failed_login_count >= current_app.config["LOGIN_MAX_FAIL"]:
                    user.locked_until = (utcnow() + timedelta(minutes=current_app.config["LOGIN_LOCK_MINUTES"])).isoformat(timespec="seconds")
                    user.failed_login_count = 0
                    audit.log("login.locked", "user", user.id, detail, user=user)
                    error = "로그인 5회 실패로 계정이 10분간 잠겼습니다."
                audit.log("login.fail", "user", user.id, detail, user=user)
            else:
                audit.log("login.fail", "user", None, {"username": username[:60]})
            db.session.commit()
    return render_template("auth/login.html", error=error, username=username), (401 if error else 200)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    audit.log("logout", "user", current_user.id, commit=True)
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def password():
    error = None
    if request.method == "POST":
        cur_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        new_pw2 = request.form.get("new_password2") or ""
        if not current_user.check_password(cur_pw):
            error = "현재 비밀번호가 올바르지 않습니다."
        elif not password_ok(new_pw):
            error = PW_RULE_MSG
        elif new_pw != new_pw2:
            error = "새 비밀번호가 서로 일치하지 않습니다."
        elif new_pw == cur_pw:
            error = "현재 비밀번호와 다른 비밀번호를 사용하세요."
        else:
            current_user.set_password(new_pw)
            current_user.must_change_password = 0
            audit.log("password.change", "user", current_user.id)
            db.session.commit()
            flash("비밀번호를 변경했습니다.", "ok")
            return redirect(url_for("views.home"))
    return render_template("auth/password.html", error=error, rule=PW_RULE_MSG)
