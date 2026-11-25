"""JSON API (/api/...) + 권한 확인 후 이미지 전송."""
import json
import re
from urllib.parse import quote

from flask import Blueprint, Response, abort, current_app, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from ..apiutil import body, fail, ok
from ..domain import INSP_TYPES, TARGETS, WORKTYPES, ZONES
from ..extensions import db
from ..models import (
    ACTION_LABELS,
    ACTION_STATUSES,
    RESULTS,
    RISK_LABELS,
    STATUSES,
    ActionChangeLog,
    ChecklistTemplate,
    Inspection,
    InspectionCategory,
    InspectionItem,
    ItemAction,
    Photo,
    ResultChangeLog,
    Signature,
    TemplateItem,
)
from ..seed import get_setting, set_setting
from ..services import audit, export_import, images, judgment, repeat, report, workflow
from ..services.permissions import (
    EDITABLE_STATUSES,
    can_action,
    can_delete,
    can_review,
    can_view,
    is_admin,
    visible_inspections,
)
from ..timeutil import is_valid_date, now_iso, today_kst
from .core import compose, create_new, default_template, list_row, new_item, serialize

bp = Blueprint("api", __name__)

MAX_TEXT = 2000
COMPLETED = ("submitted", "confirmed")
ACTION_FIELD_LABELS = {"content": "부적합 내용", "cause": "발생 원인", "risk": "위험도", "action": "개선조치 내용",
                       "owner": "조치 담당자", "due": "조치 예정일", "status": "조치 상태", "done_date": "조치 완료일"}


# ---------------------------------------------------------------------------
# 공통 도우미
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, code, message, status=400, **extra):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra


@bp.app_errorhandler(ApiError)
def _api_error(e):
    db.session.rollback()
    return fail(e.code, e.message, e.status, **e.extra)


@bp.app_errorhandler(workflow.WorkflowError)
def _wf_error(e):
    db.session.rollback()
    return fail(e.code, e.message, e.status, **e.extra)


def get_insp(pid, include_deleted=False):
    insp = Inspection.query.filter_by(public_id=pid).first()
    if not insp or (insp.deleted_at and not include_deleted):
        raise ApiError("NOT_FOUND", "점검을 찾을 수 없습니다.", 404)
    if not can_view(current_user, insp):
        raise ApiError("FORBIDDEN", "이 점검에 접근할 권한이 없습니다.", 403)
    return insp


def get_item(item_id):
    it = db.session.get(InspectionItem, item_id)
    if not it or it.is_deleted:
        raise ApiError("NOT_FOUND", "항목을 찾을 수 없습니다.", 404)
    insp = it.inspection
    if insp.deleted_at:
        raise ApiError("NOT_FOUND", "점검을 찾을 수 없습니다.", 404)
    if not can_view(current_user, insp):
        raise ApiError("FORBIDDEN", "이 점검에 접근할 권한이 없습니다.", 403)
    return it, insp


def require_edit(insp):
    """점검 결과 수정 권한: 본인 + 작성 중/반려 상태. 잠긴 상태는 409."""
    if insp.inspector_id != current_user.id:
        raise ApiError("FORBIDDEN", "본인이 작성한 점검만 수정할 수 있습니다.", 403)
    if insp.status not in EDITABLE_STATUSES:
        raise ApiError("LOCKED", "제출·확정된 점검의 결과는 수정할 수 없습니다.", 409)


def require_action(insp):
    if not can_action(current_user, insp):
        raise ApiError("FORBIDDEN", "권한이 없습니다.", 403)


def check_version(insp, data, required=True):
    v = data.get("version")
    if v is None:
        if required:
            raise ApiError("VALIDATION", "version 값이 필요합니다.", 400, fields={"version": "필수"})
        return
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ApiError("VALIDATION", "version 값이 올바르지 않습니다.", 400)
    if v != insp.version:
        raise ApiError("CONFLICT", "다른 곳에서 수정되었습니다. 새로고침 후 다시 시도하세요.", 409, version=insp.version)


def text_field(data, key, maxlen=MAX_TEXT):
    v = data.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("VALIDATION", f"{key} 값이 올바르지 않습니다.", 400, fields={key: "문자열이어야 합니다."})
    return v[:maxlen]


def reason_of(data):
    r = data.get("reason")
    return r.strip()[:1000] if isinstance(r, str) else ""


def _like(s):
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def filtered_inspections(args, completed_only=False):
    """이력 검색·필터 (아티팩트 점검 이력 필터 + 상태 필터)."""
    q = visible_inspections(current_user)
    if completed_only:
        q = q.filter(Inspection.status.in_(COMPLETED))
    for key, col in (("inspector", Inspection.inspector_name), ("dept", Inspection.inspector_org),
                     ("place", Inspection.place)):
        v = (args.get(key) or "").strip()
        if v:
            q = q.filter(col.ilike(_like(v), escape="\\"))
    kw = (args.get("q") or "").strip()
    if kw:
        p = _like(kw)
        q = q.filter(or_(Inspection.place.ilike(p, escape="\\"), Inspection.inspector_name.ilike(p, escape="\\"),
                         Inspection.inspector_org.ilike(p, escape="\\"), Inspection.report_no.ilike(p, escape="\\")))
    f, t = args.get("from"), args.get("to")
    if is_valid_date(f):
        q = q.filter(Inspection.inspect_date >= f)
    if is_valid_date(t):
        q = q.filter(Inspection.inspect_date <= t)
    if args.get("type") in INSP_TYPES:
        q = q.filter(Inspection.insp_type == args.get("type"))
    if args.get("target") in TARGETS:
        q = q.filter(Inspection.target == args.get("target"))
    st = args.get("status")
    if st in STATUSES:
        q = q.filter(Inspection.status == st)
    elif st == "completed":
        q = q.filter(Inspection.status.in_(COMPLETED))
    if args.get("mine") == "1":
        q = q.filter(Inspection.inspector_id == current_user.id)
    rows = q.order_by(Inspection.inspect_date.desc(), Inspection.inspect_time.desc(), Inspection.updated_at.desc()).all()
    ng = args.get("ng")
    if ng in ("y", "n"):
        rows = [r for r in rows if any(i.result == "ng" for i in r.live_items) == (ng == "y")]
    return rows


def _done(insp, extra=None):
    """변경 후 공통 응답: 새 version + 서버 집계."""
    items = report.flat_items(report.categories_data(insp))
    data = {"version": insp.version, "counts": judgment.counts(items), "status": insp.status}
    if extra:
        data.update(extra)
    return ok(data)


def _attachment(data, mimetype, filename):
    resp = Response(data, mimetype=mimetype)
    resp.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return resp


# ---------------------------------------------------------------------------
# 점검
# ---------------------------------------------------------------------------
@bp.get("/api/inspections")
@login_required
def list_inspections():
    rows = filtered_inspections(request.args)
    size = current_app.config["PAGE_SIZE"]
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    total = len(rows)
    chunk = rows[(page - 1) * size: page * size]
    return ok({"items": [list_row(r, current_user) for r in chunk], "total": total, "page": page,
               "pages": max(1, (total + size - 1) // size), "page_size": size})


@bp.get("/api/inspections/drafts")
@login_required
def my_drafts():
    rows = (Inspection.query.filter(Inspection.inspector_id == current_user.id, Inspection.deleted_at.is_(None),
                                    Inspection.status.in_(EDITABLE_STATUSES))
            .order_by(Inspection.updated_at.desc()).all())
    return ok({"items": [list_row(r, current_user) for r in rows]})


def create_inspection_from(data):
    copy_from = data.get("copy_from")
    src = None
    tpl = None
    if copy_from:
        src = get_insp(str(copy_from))
    elif data.get("template_id"):
        try:
            tpl = db.session.get(ChecklistTemplate, int(data["template_id"]))
        except (TypeError, ValueError):
            tpl = None
        if not tpl or not tpl.is_active:
            raise ApiError("VALIDATION", "사용할 수 없는 템플릿입니다.", 400)
    insp = create_new(current_user, tpl or default_template(), src)
    db.session.flush()
    audit.log("inspection.create", "inspection", insp.public_id,
              {"template_id": insp.template_id, "copy_from": copy_from or None})
    db.session.commit()
    return insp


@bp.post("/api/inspections")
@login_required
def create_inspection():
    insp = create_inspection_from(body())
    return ok(serialize(insp, current_user), 201)


@bp.get("/api/inspections/<pid>")
@login_required
def get_inspection(pid):
    return ok(serialize(get_insp(pid), current_user))


INFO_FIELDS = {  # 요청 key: (속성, 최대 길이, 허용값)
    "inspector": ("inspector_name", 60, None), "dept": ("inspector_org", 60, None), "place": ("place", 100, None),
    "insp_type": ("insp_type", 20, INSP_TYPES), "target": ("target", 40, TARGETS),
    "target_etc": ("target_etc", 60, None), "zone": ("zone", 40, ZONES), "zone_etc": ("zone_etc", 60, None),
    "work_type": ("work_type", 40, WORKTYPES), "work_type_etc": ("work_type_etc", 60, None),
    "vehicle_type": ("vehicle_type", 60, None), "vehicle_no": ("vehicle_no", 30, None),
    "equip_name": ("equip_name", 60, None), "equip_no": ("equip_no", 30, None),
}
STRUCT_FIELDS = ("target", "zone", "work_type")


@bp.patch("/api/inspections/<pid>")
@login_required
def patch_inspection(pid):
    insp = get_insp(pid)
    require_edit(insp)
    data = body()
    check_version(insp, data)
    fields = {}
    for key, (attr, n, allowed) in INFO_FIELDS.items():
        v = text_field(data, key, n)
        if v is None:
            continue
        if allowed is not None and v and v not in allowed:
            fields[key] = "선택 값이 올바르지 않습니다."
            continue
        if key in STRUCT_FIELDS and insp.is_composed and getattr(insp, attr) != v:
            insp.needs_recompose = 1  # 체크리스트 재구성 필요
        setattr(insp, attr, v if key == "place" else v.strip())
        if key == "target":
            if v != "철도차량":
                insp.vehicle_type = insp.vehicle_no = ""
            if v != "정비설비":
                insp.equip_name = insp.equip_no = ""
    d = data.get("date")
    if d is not None:
        if not is_valid_date(d):
            fields["date"] = "날짜 형식(YYYY-MM-DD)이 올바르지 않습니다."
        else:
            insp.inspect_date = d
    t = data.get("time")
    if t is not None:
        if not isinstance(t, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            fields["time"] = "시각 형식(HH:MM)이 올바르지 않습니다."
        else:
            insp.inspect_time = t
    v = text_field(data, "opinion", 8000)
    if v is not None:
        insp.opinion = v
        insp.opinion_edited = 1
    if fields:
        raise ApiError("VALIDATION", "입력값을 확인하세요.", 400, fields=fields)
    insp.bump()
    db.session.commit()
    return _done(insp, {"needs_recompose": bool(insp.needs_recompose)})


@bp.post("/api/inspections/<pid>/compose")
@login_required
def compose_checklist(pid):
    insp = get_insp(pid)
    require_edit(insp)
    data = body()
    check_version(insp, data)
    ids = data.get("category_ids")
    if not isinstance(ids, list):
        raise ApiError("VALIDATION", "category_ids 값이 필요합니다.", 400)
    try:
        lost = compose(insp, ids)
    except ValueError as e:
        raise ApiError("VALIDATION", str(e), 400)
    if not insp.started_at:
        insp.started_at = now_iso()
    insp.bump()
    db.session.commit()
    return ok(dict(serialize(insp, current_user), lost=lost))


@bp.post("/api/inspections/<pid>/opinion")
@login_required
def regenerate_opinion(pid):
    """종합의견 초안 다시 생성 (저장하고 수정 표시를 해제)."""
    insp = get_insp(pid)
    require_edit(insp)
    data = body()
    check_version(insp, data)
    insp.opinion = report.opinion_for(insp, current_user)
    insp.opinion_edited = 0
    insp.bump()
    db.session.commit()
    return _done(insp, {"opinion": insp.opinion})


@bp.delete("/api/inspections/<pid>")
@login_required
def delete_inspection(pid):
    insp = get_insp(pid)
    if not can_delete(current_user, insp):
        raise ApiError("FORBIDDEN", "삭제 권한이 없습니다.", 403)
    data = body()
    detail = {"place": insp.place, "date": insp.inspect_date, "report_no": insp.report_no, "status": insp.status}
    if insp.status in EDITABLE_STATUSES:
        export_import.remove_inspection_files(insp)
        db.session.delete(insp)
        audit.log("inspection.delete", "inspection", pid, dict(detail, mode="hard"))
    else:
        reason = reason_of(data)
        if not reason:
            raise ApiError("VALIDATION", "삭제 사유를 입력하세요.", 400, fields={"reason": "필수 입력 항목입니다."})
        insp.deleted_at = now_iso()
        insp.deleted_reason = reason
        insp.bump()
        audit.log("inspection.delete", "inspection", pid, dict(detail, mode="soft", reason=reason))
    db.session.commit()
    return ok({"deleted": True})


@bp.post("/api/inspections/<pid>/start")
@login_required
def start_inspection(pid):
    insp = get_insp(pid)
    require_edit(insp)
    if not insp.started_at:
        insp.started_at = now_iso()
        insp.bump()
        db.session.commit()
    return _done(insp, {"started_at": insp.started_at})


# ---------------------------------------------------------------------------
# 항목
# ---------------------------------------------------------------------------
def _dup_name(insp, name, except_id=None):
    k = repeat.norm(name)
    return any(i.id != except_id and repeat.norm(i.name) == k for i in insp.live_items)


@bp.post("/api/inspections/<pid>/categories/<int:cid>/items")
@login_required
def add_item(pid, cid):
    insp = get_insp(pid)
    require_edit(insp)
    data = body()
    check_version(insp, data, required=False)
    cat = db.session.get(InspectionCategory, cid)
    if not cat or cat.inspection_id != insp.id:
        raise ApiError("NOT_FOUND", "분야를 찾을 수 없습니다.", 404)
    name = (text_field(data, "name", 200) or "").strip()
    if not name:
        raise ApiError("VALIDATION", "점검 항목 내용을 입력하세요.", 400, fields={"name": "필수 입력 항목입니다."})
    if _dup_name(insp, name):
        raise ApiError("DUPLICATE", "동일한 점검 항목이 이미 있습니다.", 400, fields={"name": "중복"})
    tid = None
    if data.get("to_template"):
        # 기본 템플릿에도 저장 (템플릿 관리는 관리자 권한)
        if not is_admin(current_user):
            raise ApiError("FORBIDDEN", "기본 템플릿 저장은 관리자만 할 수 있습니다.", 403)
        from ..models import TemplateCategory

        tc = db.session.get(TemplateCategory, cat.template_category_id) if cat.template_category_id else None
        if not tc:
            raise ApiError("VALIDATION", "이 분야는 기본 템플릿에 연결되어 있지 않습니다.", 400)
        if any(repeat.norm(t.name) == repeat.norm(name) for t in tc.active_items):
            raise ApiError("DUPLICATE", "기본 템플릿에 동일한 항목이 이미 있습니다.", 400)
        ti = TemplateItem(name=name, sort_order=max([t.sort_order for t in tc.items] + [-1]) + 1)
        tc.items.append(ti)
        db.session.flush()
        tid = ti.id
        audit.log("template.update", "template", tc.template_id, {"op": "add_item", "category": tc.name, "name": name})
    order = max([i.sort_order for i in cat.items] + [-1]) + 1
    with db.session.no_autoflush:
        it = new_item(insp, cat, name, order, tid, is_custom=tid is None)
    insp.bump()
    db.session.commit()
    return _done(insp, {"item": report.item_data(it)})


@bp.patch("/api/items/<int:item_id>")
@login_required
def patch_item(item_id):
    it, insp = get_item(item_id)
    require_edit(insp)
    data = body()
    check_version(insp, data)
    if "result" in data:
        r = data["result"]
        if r not in RESULTS and r is not None:
            raise ApiError("VALIDATION", "점검 결과 값이 올바르지 않습니다.", 400, fields={"result": "ok/ng/na"})
        if it.result == "ng" and r != "ng":
            reason = reason_of(data)
            if not reason:
                raise ApiError("REASON_REQUIRED", "부적합 판정을 변경하려면 사유를 입력해야 합니다.", 400,
                               fields={"reason": "필수 입력 항목입니다."})
            db.session.add(ResultChangeLog(inspection_id=insp.id, item_id=it.id, kind="change", from_result="ng",
                                           to_result=r or "none", reason=reason, changed_by=current_user.id,
                                           changed_at=now_iso()))
            audit.log("item.ng_change", "item", it.id,
                      {"inspection": insp.public_id, "name": it.name, "from": "ng", "to": r, "reason": reason})
        it.result = r
    for key in ("memo", "na_reason"):
        v = text_field(data, key)
        if v is not None:
            setattr(it, key, v)
    name = text_field(data, "name", 200)
    if name is not None:
        name = name.strip()
        if not name:
            raise ApiError("VALIDATION", "점검 항목 내용을 입력하세요.", 400, fields={"name": "필수"})
        if _dup_name(insp, name, it.id):
            raise ApiError("DUPLICATE", "동일한 점검 항목이 이미 있습니다.", 400, fields={"name": "중복"})
        it.name = name
    it.updated_at = now_iso()
    insp.bump()
    db.session.commit()
    d = report.item_data(it)
    d["change_logs"] = [{"from": l.from_result, "to": l.to_result, "reason": l.reason, "at": l.changed_at}
                        for l in insp.change_logs if l.item_id == it.id and l.kind == "change"]
    return _done(insp, {"item": d})


@bp.delete("/api/items/<int:item_id>")
@login_required
def delete_item(item_id):
    it, insp = get_item(item_id)
    require_edit(insp)
    data = body()
    check_version(insp, data, required=False)
    if it.result == "ng":
        reason = reason_of(data)
        if not reason:
            raise ApiError("REASON_REQUIRED", "부적합 항목을 삭제하려면 사유를 입력해야 합니다.", 400,
                           fields={"reason": "필수 입력 항목입니다."})
        now = now_iso()
        it.is_deleted = 1
        it.deleted_reason = reason
        it.deleted_by = current_user.id
        it.deleted_at = now
        for p in it.photos:
            if not p.is_deleted:
                p.is_deleted = 1
                images.remove_file(p.stored_path)
                images.remove_file(p.thumb_path)
        db.session.add(ResultChangeLog(inspection_id=insp.id, item_id=it.id, kind="delete", from_result="ng",
                                       to_result=None, reason=reason, changed_by=current_user.id, changed_at=now))
        audit.log("item.ng_delete", "item", it.id,
                  {"inspection": insp.public_id, "name": it.name, "category": it.category.name, "reason": reason})
    else:
        for p in it.photos:
            images.remove_file(p.stored_path)
            images.remove_file(p.thumb_path)
        insp.items.remove(it)
        db.session.delete(it)
    insp.bump()
    db.session.commit()
    return _done(insp, {"deleted": True})


@bp.get("/api/items/<int:item_id>/history")
@login_required
def item_history(item_id):
    it, insp = get_item(item_id)
    idx = repeat.past_ng_index(current_user, insp.id)
    occ = idx.get(repeat.item_key(insp.place, it.template_item_id, it.name), [])
    return ok({"name": it.name, "place": insp.place, "rows": [repeat.occ_row(p, pit) for p, pit in occ]})


def _log_action(insp, it, field, old, new):
    if insp.status in COMPLETED and (old or "") != (new or ""):
        db.session.add(ActionChangeLog(inspection_id=insp.id, item_id=it.id, field=field,
                                       from_value=old or "-", to_value=new or "-", user_id=current_user.id,
                                       created_at=now_iso()))


@bp.patch("/api/items/<int:item_id>/action")
@login_required
def patch_action(item_id):
    """부적합 세부정보·개선조치 수정.
    - 부적합 내용·원인·위험도: 점검 결과의 일부 → 작성 중(본인)만
    - 개선조치 내용·담당자·예정일·상태·완료일: 확정 이후에도 조회 권한자가 수정 가능(변경 이력 기록)"""
    it, insp = get_item(item_id)
    require_action(insp)
    data = body()
    check_version(insp, data, required=False)
    a = it.action or ItemAction(item=it, updated_at=now_iso())
    locked = insp.status in COMPLETED
    fields = {}
    finding = {k: data[k] for k in ("content", "cause", "risk") if k in data}
    if finding:
        if insp.status not in EDITABLE_STATUSES or insp.inspector_id != current_user.id:
            raise ApiError("LOCKED", "제출·확정된 점검의 부적합 내용·원인·위험도는 수정할 수 없습니다.", 409)
        for k in ("content", "cause"):
            v = text_field(data, k)
            if v is not None:
                setattr(a, k, v)
        if "risk" in data:
            if data["risk"] not in RISK_LABELS and data["risk"] not in (None, ""):
                fields["risk"] = "h/m/l"
            else:
                a.risk = data["risk"] or None
    old = {"action": a.plan, "owner": a.owner_name, "due": a.due_date, "status": a.status, "done_date": a.done_date}
    v = text_field(data, "action")
    if v is not None:
        a.plan = v
    v = text_field(data, "owner", 60)
    if v is not None:
        a.owner_name = v
    for key, attr in (("due", "due_date"), ("done_date", "done_date")):
        if key in data:
            d = data[key]
            if d in (None, ""):
                setattr(a, attr, None)
            elif is_valid_date(d):
                setattr(a, attr, d)
            else:
                fields[key] = "날짜 형식(YYYY-MM-DD)이 올바르지 않습니다."
    if "status" in data:
        if data["status"] not in ACTION_STATUSES:
            fields["status"] = "todo/in_progress/done"
        else:
            a.status = data["status"]
    if locked:
        for k, attr in (("action", "plan"), ("owner", "owner_name"), ("due", "due_date")):
            if k in data and not str(getattr(a, attr) or "").strip():
                fields[k] = "확정된 점검의 개선조치 내용·담당자·예정일은 비울 수 없습니다."
    if fields:
        raise ApiError("VALIDATION", "입력값을 확인하세요.", 400, fields=fields)
    auto_done = False
    if a.status == "done" and not a.done_date:
        a.done_date = today_kst()
        auto_done = True
    if a.status != "done" and old["status"] == "done" and "done_date" not in data:
        a.done_date = None
    a.updated_by = current_user.id
    a.updated_at = now_iso()
    _log_action(insp, it, "개선조치 내용", old["action"], a.plan)
    _log_action(insp, it, "조치 담당자", old["owner"], a.owner_name)
    _log_action(insp, it, "조치 예정일", old["due"], a.due_date)
    _log_action(insp, it, "조치 상태", ACTION_LABELS.get(old["status"]), ACTION_LABELS.get(a.status))
    _log_action(insp, it, "조치 완료일", old["done_date"], a.done_date)
    if old["status"] != a.status:
        audit.log("action.status", "item", it.id,
                  {"inspection": insp.public_id, "name": it.name, "from": old["status"], "to": a.status})
    insp.bump()
    db.session.commit()
    return _done(insp, {"item": report.item_data(it), "auto_done_date": auto_done})


# ---------------------------------------------------------------------------
# 사진 (finding: 항목 사진 · before: 개선 전 · action: 개선 후)
# ---------------------------------------------------------------------------
KIND_LABELS = {"finding": "현장 사진", "before": "개선 전 사진", "action": "개선 후 사진"}


def _require_photo_perm(insp, it, kind):
    if kind == "action":
        require_action(insp)
        if it.result != "ng":
            raise ApiError("VALIDATION", "개선 후 사진은 부적합 항목에만 첨부할 수 있습니다.", 400)
    else:
        require_edit(insp)
        if kind == "before" and it.result != "ng":
            raise ApiError("VALIDATION", "개선 전 사진은 부적합 항목에만 첨부할 수 있습니다.", 400)


@bp.post("/api/items/<int:item_id>/photos")
@login_required
def upload_photo(item_id):
    it, insp = get_item(item_id)
    kind = request.form.get("kind", "finding")
    if kind not in KIND_LABELS:
        raise ApiError("VALIDATION", "kind 값이 올바르지 않습니다.", 400)
    _require_photo_perm(insp, it, kind)
    f = request.files.get("file")
    if not f:
        raise ApiError("VALIDATION", "첨부할 파일이 없습니다.", 400)
    n = len(it.live_photos(kind))
    if n >= current_app.config["MAX_PHOTOS_PER_ITEM"]:
        raise ApiError("LIMIT", f"{KIND_LABELS[kind]}은 항목당 최대 {current_app.config['MAX_PHOTOS_PER_ITEM']}장까지 첨부할 수 있습니다.", 400)
    raw = f.read()
    try:
        meta = images.process_photo(raw)
    except images.ImageError as e:
        raise ApiError("INVALID_IMAGE", str(e), 400)
    p = Photo(item_id=it.id, kind=kind, original_name=(f.filename or "")[:200], uploaded_by=current_user.id,
              created_at=now_iso(), **meta)
    db.session.add(p)
    if kind == "action":
        _log_action(insp, it, "개선 후 사진", f"{n}장", f"{n + 1}장")
    insp.bump()
    db.session.commit()
    return _done(insp, {"photo": {"id": p.id, "kind": kind}})


@bp.delete("/api/photos/<int:photo_id>")
@login_required
def delete_photo(photo_id):
    p = db.session.get(Photo, photo_id)
    if not p or p.is_deleted:
        raise ApiError("NOT_FOUND", "사진을 찾을 수 없습니다.", 404)
    it, insp = get_item(p.item_id)
    if p.kind == "action":
        require_action(insp)
    else:
        require_edit(insp)
    n = len(it.live_photos(p.kind))
    p.is_deleted = 1
    if insp.status in EDITABLE_STATUSES:  # 확정 전 점검만 실제 파일 정리 (확정본 보고서 보존)
        images.remove_file(p.stored_path)
        images.remove_file(p.thumb_path)
    if p.kind == "action":
        _log_action(insp, it, "개선 후 사진", f"{n}장", f"{n - 1}장")
    insp.bump()
    db.session.commit()
    return _done(insp, {"deleted": True})


def _photo_for_view(photo_id):
    p = db.session.get(Photo, photo_id)
    if not p:
        abort(404)
    insp = p.item.inspection
    if not can_view(current_user, insp):
        abort(403)
    # 소프트 삭제된 사진은 최초 보고서(확정본)에 남아 있는 경우에만 보여준다
    if p.is_deleted and not insp.original_snapshot:
        abort(404)
    return p


def _send(rel, mime):
    from ..services.storage import StorageError

    try:
        data = images.read_file(rel)
    except (FileNotFoundError, StorageError, OSError):
        abort(404)
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


@bp.get("/photos/<int:photo_id>")
@login_required
def view_photo(photo_id):
    p = _photo_for_view(photo_id)
    return _send(p.stored_path, p.mime)


@bp.get("/photos/<int:photo_id>/thumb")
@login_required
def view_thumb(photo_id):
    p = _photo_for_view(photo_id)
    return _send(p.thumb_path, "image/jpeg")


# ---------------------------------------------------------------------------
# 서명 · 결재
# ---------------------------------------------------------------------------
@bp.get("/signatures/<pid>/<role>")
@login_required
def view_signature(pid, role):
    insp = Inspection.query.filter_by(public_id=pid).first()
    if not insp or not can_view(current_user, insp):
        abort(404)
    s = insp.signature(role)
    if not s:
        abort(404)
    return _send(s.image_path, "image/png")


@bp.post("/api/inspections/<pid>/signatures")
@login_required
def save_signature(pid):
    insp = get_insp(pid)
    data = body()
    role = data.get("role")
    if role == "inspector":
        require_edit(insp)
    elif role == "confirmer":
        if not can_review(current_user, insp):
            raise ApiError("FORBIDDEN", "확인자 서명 권한이 없습니다.", 403)
    else:
        raise ApiError("VALIDATION", "role 값이 올바르지 않습니다.", 400)
    image = data.get("image") or ""
    old = insp.signature(role)
    if not image:
        if old:
            images.remove_file(old.image_path)
            db.session.delete(old)
            db.session.commit()
        return ok({"signed": False})
    try:
        rel = images.save_signature(image)
    except images.ImageError as e:
        raise ApiError("INVALID_IMAGE", str(e), 400)
    if old:
        images.remove_file(old.image_path)
        old.image_path, old.signer_id, old.signer_name, old.signed_at, old.ip = (
            rel, current_user.id, current_user.name, now_iso(), request.remote_addr)
    else:
        db.session.add(Signature(inspection_id=insp.id, role=role, signer_id=current_user.id, signer_name=current_user.name,
                                 image_path=rel, signed_at=now_iso(), ip=request.remote_addr))
    db.session.commit()
    return ok({"signed": True})


@bp.post("/api/inspections/<pid>/submit")
@login_required
def submit(pid):
    insp = get_insp(pid)
    if insp.inspector_id != current_user.id:
        raise ApiError("FORBIDDEN", "본인이 작성한 점검만 제출할 수 있습니다.", 403)
    workflow.submit(insp, current_user)
    db.session.commit()
    return _done(insp, {"submitted_at": insp.submitted_at})


@bp.post("/api/inspections/<pid>/confirm")
@login_required
def confirm(pid):
    insp = get_insp(pid)
    if not can_review(current_user, insp):
        if insp.status != "submitted" and current_user.role in ("confirmer", "admin") and insp.inspector_id != current_user.id:
            raise ApiError("STATE", "제출된 점검만 확인할 수 있습니다.", 409)
        raise ApiError("FORBIDDEN", "확인 권한이 없습니다. (확인자·관리자만 가능하며, 본인 점검은 확인할 수 없습니다.)", 403)
    no = workflow.confirm(insp, current_user)
    db.session.commit()
    return _done(insp, {"report_no": no})


@bp.post("/api/inspections/<pid>/reject")
@login_required
def reject(pid):
    insp = get_insp(pid)
    if not can_review(current_user, insp):
        raise ApiError("FORBIDDEN", "반려 권한이 없습니다.", 403)
    workflow.reject(insp, current_user, reason_of(body()))
    db.session.commit()
    return _done(insp)


# ---------------------------------------------------------------------------
# 대시보드 · 부적합 관리
# ---------------------------------------------------------------------------
def _ng_entries(rows):
    out = []
    for insp in rows:
        for cat in insp.categories:
            for it in cat.live_items:
                if it.result == "ng":
                    out.append((insp, cat, it))
    return out


def time_settings():
    try:
        b, a = int(get_setting("before_min", 90)), int(get_setting("after_min", 43))
    except (TypeError, ValueError):
        b, a = 90, 43
    return b, a


@bp.get("/api/dashboard")
@login_required
def dashboard():
    rows = filtered_inspections({"from": request.args.get("from"), "to": request.args.get("to")}, completed_only=True)
    today = today_kst()
    days = current_app.config["REPEAT_DAYS"]
    ok_n = ng_n = na_n = 0
    for insp in rows:
        for it in insp.live_items:
            if it.result == "ok":
                ok_n += 1
            elif it.result == "na":
                na_n += 1
            elif it.result == "ng":
                ng_n += 1
    ngs = _ng_entries(rows)
    st = {"todo": 0, "in_progress": 0, "done": 0}
    overdue = 0
    by_cat = {}
    for insp, cat, it in ngs:
        g = report.action_data(it.action)
        st[g["status"]] = st.get(g["status"], 0) + 1
        if judgment.is_overdue(g, today):
            overdue += 1
        by_cat[cat.name] = by_cat.get(cat.name, 0) + 1
    reps = repeat.repeat_groups(current_user, today, days)[:5]
    b, a = time_settings()
    per = max(0, b - a)
    recent = sorted(rows, key=lambda r: r.submitted_at or "", reverse=True)[:5]
    return ok({
        "total": len(rows), "ok": ok_n, "ng": ng_n, "na": na_n, "rate": judgment.pct(ok_n, ok_n + ng_n),
        "status": st, "undone": st["todo"] + st["in_progress"], "overdue": overdue,
        "done_rate": judgment.pct(st["done"], len(ngs)), "ng_total": len(ngs),
        "by_category": sorted(([k, v] for k, v in by_cat.items()), key=lambda kv: -kv[1]),
        "repeats": [{"key": g["key"], "text": g["text"], "place": g["place"], "cat": g["cat"], "count": g["count"],
                     "last": g["last"], "rows": [repeat.occ_row(p, it) for p, it in g["occ"]]} for g in reps],
        "time": {"before": b, "after": a, "per": per, "rate": judgment.pct(per, b), "total_hours": round(per * len(rows) / 60, 1)},
        "recent": [list_row(r, current_user) for r in recent],
        "today": today, "repeat_days": days,
    })


@bp.get("/api/ng")
@login_required
def ng_list():
    """부적합 관리 목록 (제출·확정된 점검의 부적합 항목)."""
    args = request.args
    rows = filtered_inspections({}, completed_only=True)
    today = today_kst()
    days = current_app.config["REPEAT_DAYS"]
    rep = repeat.repeat_key_set(current_user, today, days)
    out = []
    st_count = {"todo": 0, "in_progress": 0, "done": 0}
    overdue_n = 0
    for insp, cat, it in _ng_entries(rows):
        g = report.action_data(it.action)
        od = judgment.is_overdue(g, today)
        st_count[g["status"]] += 1
        overdue_n += 1 if od else 0
        is_rep = repeat.item_key(insp.place, it.template_item_id, it.name) in rep
        f = args.get("status") or ""
        if f == "undone" and g["status"] == "done":
            continue
        if f in ACTION_STATUSES and g["status"] != f:
            continue
        if args.get("risk") in RISK_LABELS and g["risk"] != args.get("risk"):
            continue
        if args.get("overdue") == "1" and not od:
            continue
        if args.get("repeat") == "1" and not is_rep:
            continue
        q = repeat.norm(args.get("q"))
        if q and not any(q in repeat.norm(v) for v in (insp.place, it.name, g["content"], g["owner"], insp.report_no)):
            continue
        out.append({
            "insp_id": insp.public_id, "report_no": insp.report_no or "", "status": insp.status,
            "status_label": insp.status_label, "date": insp.inspect_date, "place": insp.place, "cat": cat.name,
            "item_id": it.id, "name": it.name, "ng": g, "overdue": od, "repeat": is_rep,
            "before": [p.id for p in it.live_photos("before")], "after": [p.id for p in it.live_photos("action")],
            "can_action": can_action(current_user, insp),
        })
    order = {"todo": 0, "in_progress": 1, "done": 2}
    risk_o = {"h": 0, "m": 1, "l": 2}
    out.sort(key=lambda x: x["date"], reverse=True)
    out.sort(key=lambda x: (not x["overdue"], order[x["ng"]["status"]], risk_o.get(x["ng"]["risk"], 3)))
    total = sum(st_count.values())
    return ok({"items": out, "status": st_count, "undone": st_count["todo"] + st_count["in_progress"],
               "overdue": overdue_n, "done_rate": judgment.pct(st_count["done"], total), "today": today})


# ---------------------------------------------------------------------------
# 설정 (업무시간 절감 기준)
# ---------------------------------------------------------------------------
@bp.get("/api/settings")
@login_required
def get_settings():
    b, a = time_settings()
    return ok({"before_min": b, "after_min": a})


@bp.patch("/api/settings")
@login_required
def patch_settings():
    if not is_admin(current_user):
        raise ApiError("FORBIDDEN", "관리자만 변경할 수 있습니다.", 403)
    data = body()
    try:
        b, a = int(data.get("before_min")), int(data.get("after_min"))
    except (TypeError, ValueError):
        raise ApiError("VALIDATION", "숫자를 입력하세요.", 400)
    if b <= 0 or a < 0 or a > b:
        raise ApiError("VALIDATION", "기존 소요시간은 0보다 커야 하며, 자동화 후 시간은 기존 시간 이하여야 합니다.", 400)
    set_setting("before_min", b)
    set_setting("after_min", a)
    audit.log("settings.update", "settings", None, {"before_min": b, "after_min": a})
    db.session.commit()
    return ok({"before_min": b, "after_min": a})


# ---------------------------------------------------------------------------
# 내보내기 · 불러오기
# ---------------------------------------------------------------------------
def file_base(insp):
    place = re.sub(r'[\\/:*?"<>|\s]+', "_", insp.place or "장소미입력")[:30]
    return f"안전점검_{(insp.inspect_date or '').replace('-', '')}_{place}_{insp.report_no or insp.public_id[-6:]}"


@bp.get("/api/inspections/<pid>/export.json")
@login_required
def export_one(pid):
    insp = get_insp(pid)
    payload = json.dumps(export_import.export_payload([insp]), ensure_ascii=False)
    return _attachment(payload, "application/json", file_base(insp) + ".json")


@bp.get("/api/export/all.json")
@login_required
def export_all():
    if not is_admin(current_user):
        raise ApiError("FORBIDDEN", "관리자만 전체 내보내기를 할 수 있습니다.", 403)
    rows = Inspection.query.filter(Inspection.deleted_at.is_(None)).order_by(Inspection.id).all()
    audit.log("export.all", "inspection", None, {"count": len(rows)}, commit=True)
    payload = json.dumps(export_import.export_payload(rows), ensure_ascii=False)
    return _attachment(payload, "application/json", f"안전점검_전체백업_{today_kst().replace('-', '')}.json")


@bp.post("/api/import")
@login_required
def import_json():
    if not is_admin(current_user):
        raise ApiError("FORBIDDEN", "관리자만 불러오기를 할 수 있습니다.", 403)
    request.max_content_length = current_app.config["IMPORT_MAX_BYTES"]
    data = body()
    parsed = export_import.parse_file(data.get("data"))
    if isinstance(parsed, str):
        raise ApiError("INVALID_FILE", parsed, 400)
    valid, bad, photos, kind = parsed
    existing = {i.public_id: i for i in Inspection.query.filter(Inspection.public_id.in_([v["id"] for v in valid])).all()}
    conflicts = [{"id": v["id"], "date": v["info"]["date"], "place": v["info"]["place"], "report_no": v["report_no"]}
                 for v in valid if v["id"] in existing]
    mode = data.get("mode")
    if mode not in ("overwrite", "skip"):
        return ok({"preview": True, "kind": kind, "valid": len(valid), "bad": bad, "conflicts": conflicts,
                   "photos": len(photos)})
    imported = skipped = 0
    cache = {}
    for v in valid:
        ex = existing.get(v["id"])
        if ex is not None and mode == "skip":
            skipped += 1
            continue
        export_import.import_one(v, photos, current_user, ex, cache)
        imported += 1
    audit.log("import.json", "inspection", None,
              {"imported": imported, "skipped": skipped, "bad": len(bad), "mode": mode, "kind": kind})
    db.session.commit()
    return ok({"imported": imported, "skipped": skipped, "bad": bad})


@bp.get("/export/stats.csv")
@login_required
def stats_csv():
    rows = filtered_inspections(request.args)
    rows.sort(key=lambda r: (r.inspect_date, r.inspect_time, r.id))
    kind = "detail" if request.args.get("kind") == "detail" else "summary"
    fn = export_import.detail_csv if kind == "detail" else export_import.summary_csv
    text = fn(rows, today_kst())
    f, t = request.args.get("from") or "", request.args.get("to") or ""
    label = "항목상세" if kind == "detail" else "요약"
    name = f"안전점검_{label}_{f.replace('-', '') or '전체'}_{t.replace('-', '') or today_kst().replace('-', '')}.csv"
    return _attachment(text.encode("utf-8"), "text/csv; charset=utf-8", name)
