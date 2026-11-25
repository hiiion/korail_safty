"""권한 검사 함수 — 모든 권한 판단은 서버에서 이 함수들로 한다."""
from functools import wraps

from flask import abort
from flask_login import current_user
from sqlalchemy import or_

EDITABLE_STATUSES = ("draft", "rejected")


def visible_inspections(user):
    """조회 가능한 점검 쿼리: 관리자는 전체, 그 외는 본인 + 같은 소속(사용자 계정의 소속 기준)."""
    from ..models import Inspection, User

    q = Inspection.query.filter(Inspection.deleted_at.is_(None))
    if not is_admin(user):
        q = q.join(User, Inspection.inspector_id == User.id)
        conds = [Inspection.inspector_id == user.id]
        if user.org:
            conds.append(User.org == user.org)
        q = q.filter(or_(*conds))
    return q


def is_admin(user):
    return bool(user and user.is_authenticated and user.role == "admin")


def can_view(user, insp):
    if not user or not user.is_authenticated or insp is None:
        return False
    if insp.deleted_at and not is_admin(user):
        return False
    if is_admin(user) or insp.inspector_id == user.id:
        return True
    owner_org = insp.inspector.org if insp.inspector else insp.inspector_org
    return bool(user.org) and owner_org == user.org


def can_edit(user, insp):
    """점검 결과·메모·사진·기본정보 수정 (본인, 작성 중/반려 상태)."""
    return (
        can_view(user, insp)
        and not insp.deleted_at
        and insp.status in EDITABLE_STATUSES
        and insp.inspector_id == user.id
    )


def can_action(user, insp):
    """개선·사후 조치 입력 — 조회 권한자 모두, 확정 후에도 허용."""
    return can_view(user, insp) and not insp.deleted_at


def can_submit(user, insp):
    return can_edit(user, insp)


def can_review(user, insp):
    """확인(승인)·반려 — 확인자/관리자, 본인 점검 제외, 제출된 상태."""
    return (
        can_view(user, insp)
        and not insp.deleted_at
        and user.role in ("confirmer", "admin")
        and insp.status == "submitted"
        and insp.inspector_id != user.id
    )


def can_delete(user, insp):
    if not can_view(user, insp) or insp.deleted_at:
        return False
    if is_admin(user):
        return True
    return insp.inspector_id == user.id and insp.status in EDITABLE_STATUSES


def perms_for(user, insp):
    return {
        "view": can_view(user, insp),
        "edit": can_edit(user, insp),
        "action": can_action(user, insp),
        "submit": can_submit(user, insp),
        "review": can_review(user, insp),
        "delete": can_delete(user, insp),
        "admin": is_admin(user),
    }


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not is_admin(current_user):
            abort(403)
        return fn(*a, **kw)

    return wrapper
