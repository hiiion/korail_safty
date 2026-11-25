"""관리자: 사용자 · 체크리스트 템플릿 · 감사로그."""
import json
import secrets
import string

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..auth import PW_RULE_MSG, password_ok
from ..extensions import db
from ..models import ROLES, RULES, AuditLog, ChecklistTemplate, TemplateCategory, TemplateItem, User
from ..services import audit
from ..services.audit import ACTION_LABELS
from ..services.permissions import admin_required
from ..timeutil import KST, now_iso

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _temp_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(10))
        if password_ok(pw):
            return pw


# ---------------------------------------------------------------------------
# 사용자 관리
# ---------------------------------------------------------------------------
@bp.get("/users")
@login_required
@admin_required
def users():
    rows = User.query.order_by(User.role, User.username).all()
    return render_template("admin/users.html", users=rows, roles=ROLES, rule=PW_RULE_MSG, page="admin", now=now_iso())


@bp.post("/users")
@login_required
@admin_required
def user_action():
    act = request.form.get("act")
    if act == "create":
        username = (request.form.get("username") or "").strip()
        name = (request.form.get("name") or "").strip()
        org = (request.form.get("org") or "").strip()
        role = request.form.get("role")
        pw = request.form.get("password") or ""
        if not username or not name or role not in ROLES:
            flash("아이디·이름·역할을 입력하세요.", "err")
        elif User.query.filter_by(username=username).first():
            flash("이미 존재하는 아이디입니다.", "err")
        else:
            temp = not pw
            pw = pw or _temp_password()
            if not password_ok(pw):
                flash(PW_RULE_MSG, "err")
                return redirect(url_for("admin.users"))
            u = User(username=username[:40], name=name[:40], org=org[:60], role=role, must_change_password=1)
            u.set_password(pw)
            db.session.add(u)
            db.session.flush()
            audit.log("user.create", "user", u.id, {"username": username, "role": role, "org": org})
            db.session.commit()
            flash(f"'{username}' 계정을 만들었습니다." + (f" 임시 비밀번호: {pw} (최초 로그인 시 변경해야 합니다)" if temp else " 최초 로그인 시 비밀번호를 변경해야 합니다."), "ok")
        return redirect(url_for("admin.users"))

    u = db.session.get(User, request.form.get("user_id", type=int) or 0)
    if not u:
        flash("사용자를 찾을 수 없습니다.", "err")
        return redirect(url_for("admin.users"))
    if act == "update":
        role = request.form.get("role")
        org = (request.form.get("org") or "").strip()[:60]
        name = (request.form.get("name") or "").strip()[:40] or u.name
        active = 1 if request.form.get("is_active") == "1" else 0
        if u.id == current_user.id and (role != "admin" or not active):
            flash("본인 계정의 관리자 권한이나 사용 상태는 바꿀 수 없습니다.", "err")
            return redirect(url_for("admin.users"))
        if role in ROLES:
            before = {"role": u.role, "org": u.org, "name": u.name, "active": u.is_active_flag}
            u.role, u.org, u.name, u.is_active_flag = role, org, name, active
            audit.log("user.update", "user", u.id, {"before": before, "after": {"role": role, "org": org, "name": name, "active": active}})
            db.session.commit()
            flash(f"'{u.username}' 정보를 저장했습니다.", "ok")
    elif act == "unlock":
        u.locked_until = None
        u.failed_login_count = 0
        audit.log("user.unlock", "user", u.id, {"username": u.username})
        db.session.commit()
        flash(f"'{u.username}' 계정 잠금을 해제했습니다.", "ok")
    elif act == "reset":
        pw = _temp_password()
        u.set_password(pw)
        u.must_change_password = 1
        u.locked_until = None
        u.failed_login_count = 0
        audit.log("password.reset", "user", u.id, {"username": u.username})
        db.session.commit()
        flash(f"'{u.username}' 임시 비밀번호: {pw} — 사용자에게 전달하세요. 최초 로그인 시 변경해야 합니다.", "ok")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# 체크리스트 템플릿 관리
# ---------------------------------------------------------------------------
@bp.get("/templates")
@login_required
@admin_required
def templates():
    rows = ChecklistTemplate.query.order_by(ChecklistTemplate.is_default.desc(), ChecklistTemplate.id).all()
    sel = request.args.get("t", type=int)
    cur = next((t for t in rows if t.id == sel), rows[0] if rows else None)
    return render_template("admin/templates.html", templates=rows, cur=cur, rules=RULES, page="admin")


def _reorder(objs, obj, delta):
    objs = list(objs)
    i = objs.index(obj)
    j = i + delta
    if 0 <= j < len(objs):
        objs[i], objs[j] = objs[j], objs[i]
    for k, o in enumerate(objs):
        o.sort_order = k


@bp.post("/templates")
@login_required
@admin_required
def template_action():
    act = request.form.get("act")
    tid = request.form.get("template_id", type=int)
    t = db.session.get(ChecklistTemplate, tid) if tid else None
    name = (request.form.get("name") or "").strip()[:80]
    detail = {"act": act}
    if act == "create_template":
        if not name:
            flash("템플릿 이름을 입력하세요.", "err")
            return redirect(url_for("admin.templates"))
        src = db.session.get(ChecklistTemplate, request.form.get("copy_from", type=int) or 0)
        now = now_iso()
        t = ChecklistTemplate(name=name, is_default=0, is_active=1, created_by=current_user.id, created_at=now, updated_at=now)
        if src:
            for c in src.categories:
                nc = TemplateCategory(name=c.name, rule=c.rule, sort_order=c.sort_order, is_active=c.is_active)
                for i in c.items:
                    nc.items.append(TemplateItem(name=i.name, sort_order=i.sort_order, is_active=i.is_active))
                t.categories.append(nc)
        db.session.add(t)
        db.session.flush()
        detail["name"] = name
    elif not t:
        flash("템플릿을 찾을 수 없습니다.", "err")
        return redirect(url_for("admin.templates"))
    elif act == "rename_template" and name:
        t.name = name
    elif act == "set_default":
        for o in ChecklistTemplate.query.all():
            o.is_default = 1 if o.id == t.id else 0
        t.is_active = 1
    elif act == "toggle_template":
        if t.is_default and t.is_active:
            flash("기본 템플릿은 비활성화할 수 없습니다. 다른 템플릿을 기본으로 지정하세요.", "err")
            return redirect(url_for("admin.templates", t=t.id))
        t.is_active = 0 if t.is_active else 1
    elif act == "add_category" and name:
        rule = request.form.get("rule")
        t.categories.append(TemplateCategory(name=name, rule=rule if rule in RULES else "custom",
                                             sort_order=len(t.categories)))
    else:
        cat = db.session.get(TemplateCategory, request.form.get("category_id", type=int) or 0)
        item = db.session.get(TemplateItem, request.form.get("item_id", type=int) or 0)
        if cat and cat.template_id != t.id:
            cat = None
        if item and item.category.template_id != t.id:
            item = None
        if act == "rename_category" and cat and name:
            cat.name = name
            rule = request.form.get("rule")
            if rule in RULES:
                cat.rule = rule
        elif act == "toggle_category" and cat:
            cat.is_active = 0 if cat.is_active else 1
        elif act == "move_category" and cat:
            _reorder(t.categories, cat, request.form.get("delta", type=int) or 0)
        elif act == "delete_category" and cat:
            if any(True for _ in cat.items):
                flash("항목이 있는 분야는 삭제할 수 없습니다. 항목을 먼저 비활성화하거나 옮기세요.", "err")
                return redirect(url_for("admin.templates", t=t.id))
            db.session.delete(cat)
        elif act == "add_item" and cat and name:
            cat.items.append(TemplateItem(name=name, sort_order=len(cat.items)))
        elif act == "rename_item" and item and name:
            item.name = name
        elif act == "move_item" and item:
            _reorder(item.category.items, item, request.form.get("delta", type=int) or 0)
        elif act == "toggle_item" and item:
            item.is_active = 0 if item.is_active else 1
        else:
            flash("요청을 처리하지 못했습니다. 입력값을 확인하세요.", "err")
            return redirect(url_for("admin.templates", t=t.id))
        detail.update({"category_id": cat.id if cat else None, "item_id": item.id if item else None, "name": name or None})
    t.updated_at = now_iso()
    audit.log("template.update", "template", t.id, detail)
    db.session.commit()
    flash("템플릿을 저장했습니다. (기존 점검에는 영향이 없습니다)", "ok")
    return redirect(url_for("admin.templates", t=t.id))


# ---------------------------------------------------------------------------
# 감사로그 조회
# ---------------------------------------------------------------------------
@bp.get("/audit")
@login_required
@admin_required
def audit_logs():
    from datetime import datetime, timedelta, timezone

    q = AuditLog.query
    f, t = request.args.get("from") or "", request.args.get("to") or ""
    uid = request.args.get("user_id", type=int)
    act = request.args.get("action") or ""

    def kst_bound(d, end=False):
        try:
            day = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=KST)
        except ValueError:
            return None
        if end:
            day += timedelta(days=1)
        return day.astimezone(timezone.utc).isoformat(timespec="seconds")

    if f and kst_bound(f):
        q = q.filter(AuditLog.created_at >= kst_bound(f))
    if t and kst_bound(t, True):
        q = q.filter(AuditLog.created_at < kst_bound(t, True))
    if uid:
        q = q.filter(AuditLog.user_id == uid)
    if act:
        q = q.filter(AuditLog.action == act)
    page = max(1, request.args.get("page", 1, type=int))
    size = 50
    total = q.count()
    rows = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * size).limit(size).all()
    for r in rows:
        try:
            r.detail = json.loads(r.detail_json) if r.detail_json else None
        except ValueError:
            r.detail = r.detail_json
    return render_template(
        "admin/audit.html", rows=rows, total=total, page_no=page, pages=max(1, (total + size - 1) // size),
        users=User.query.order_by(User.username).all(), actions=ACTION_LABELS,
        f=f, t=t, uid=uid, act=act, page="admin",
    )
