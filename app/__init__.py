"""앱 팩토리."""
import os

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError

from .apiutil import fail, wants_json
from .config import base_config
from .extensions import csrf, db, login_manager, migrate

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app(test_config=None):
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    app = Flask(
        __name__,
        instance_path=os.path.join(PROJECT_ROOT, "instance"),
        instance_relative_config=True,
    )
    app.config.update(base_config())
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY가 설정되지 않았습니다. .env 파일에 SECRET_KEY를 지정하세요. "
            "(예: python -c \"import secrets; print(secrets.token_hex(32))\")"
        )
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "로그인이 필요합니다."
    login_manager.session_protection = "strong"

    from .models import User

    @login_manager.user_loader
    def load_user(uid):
        try:
            return db.session.get(User, int(uid))
        except (TypeError, ValueError):
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        if wants_json():
            return fail("UNAUTHORIZED", "로그인이 필요합니다.", 401)
        return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))

    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .inspections.api import bp as api_bp
    from .inspections.views import bp as views_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    from . import cli

    cli.register(app)
    _register_hooks(app)
    _register_filters(app)
    return app


def _register_hooks(app):
    @app.before_request
    def force_password_change():
        if not current_user.is_authenticated or not current_user.must_change_password:
            return None
        if request.endpoint in ("auth.password", "auth.logout", "static"):
            return None
        if wants_json():
            return fail("PASSWORD_CHANGE_REQUIRED", "비밀번호를 먼저 변경하세요.", 403)
        return redirect(url_for("auth.password"))

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:"
        if request.path.startswith("/api/") or request.endpoint in ("auth.login", "auth.password"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def _err(status, code, message, template_msg=None):
        if wants_json():
            return fail(code, message, status)
        return render_template("error.html", status=status, message=template_msg or message), status

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return _err(400, "CSRF", "보안 토큰이 만료되었거나 올바르지 않습니다. 페이지를 새로고침하세요.")

    @app.errorhandler(400)
    def bad_request(e):
        return _err(400, "BAD_REQUEST", "잘못된 요청입니다.")

    @app.errorhandler(403)
    def forbidden(e):
        return _err(403, "FORBIDDEN", "권한이 없습니다.")

    @app.errorhandler(404)
    def not_found(e):
        return _err(404, "NOT_FOUND", "찾을 수 없습니다.")

    @app.errorhandler(405)
    def not_allowed(e):
        return _err(405, "METHOD_NOT_ALLOWED", "허용되지 않은 요청입니다.")

    @app.errorhandler(413)
    def too_large(e):
        mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return _err(413, "TOO_LARGE", f"파일이 너무 큽니다. (요청 1건 최대 {mb}MB)")


def _register_filters(app):
    from .models import ACTION_LABELS, RESULT_LABELS, RISK_LABELS, ROLE_LABELS, RULE_LABELS, STATUS_LABELS
    from .timeutil import duration_text, fmt_kst

    app.jinja_env.filters["kst"] = fmt_kst
    app.jinja_env.filters["kst_sec"] = lambda s: fmt_kst(s, True)
    app.jinja_env.filters["kst_date"] = lambda s: fmt_kst(s)[:10]
    app.jinja_env.globals.update(
        duration_text=duration_text,
        ACTION_LABELS=ACTION_LABELS,
        RESULT_LABELS=RESULT_LABELS,
        RISK_LABELS=RISK_LABELS,
        ROLE_LABELS=ROLE_LABELS,
        RULE_LABELS=RULE_LABELS,
        STATUS_LABELS=STATUS_LABELS,
        APP_NAME="스마트 철도차량 안전점검 시스템",
    )
