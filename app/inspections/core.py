"""점검 생성·체크리스트 구성·직렬화 공통 로직."""
import json

from flask import current_app

from ..domain import recommend_rules
from ..extensions import db
from ..models import (
    ChecklistTemplate,
    Inspection,
    InspectionCategory,
    InspectionItem,
    ItemAction,
    TemplateCategory,
)
from ..services import images, judgment, repeat
from ..services.permissions import perms_for
from ..services.report import categories_data, flat_items, info_data
from ..timeutil import now_iso, today_kst, utcnow, KST

INFO_COPY_FIELDS = ("place", "insp_type", "target", "target_etc", "zone", "zone_etc", "work_type", "work_type_etc",
                    "vehicle_type", "vehicle_no", "equip_name", "equip_no")


def default_template():
    t = ChecklistTemplate.query.filter_by(is_default=1, is_active=1).first()
    return t or ChecklistTemplate.query.filter_by(is_active=1).order_by(ChecklistTemplate.id).first()


def now_kst_hm():
    return utcnow().astimezone(KST).strftime("%H:%M")


def new_item(insp, cat, name, order, template_item_id=None, is_custom=False):
    now = now_iso()
    it = InspectionItem(name=name, sort_order=order, updated_at=now, template_item_id=template_item_id,
                        is_custom=1 if is_custom else 0)
    it.action = ItemAction(updated_at=now)
    insp.items.append(it)
    cat.items.append(it)
    return it


def create_new(user, template, src=None):
    now = now_iso()
    insp = Inspection(
        inspector_id=user.id, inspector_name=user.name, inspector_org=user.org or "",
        inspect_date=today_kst(), inspect_time=now_kst_hm(),
        template_id=template.id if template else None, created_at=now, updated_at=now,
    )
    if src is not None:
        # 기본정보 + 체크리스트 구성만 복사하고 결과는 초기화
        for f in INFO_COPY_FIELDS:
            setattr(insp, f, getattr(src, f))
        insp.copied_from_id = src.id
        insp.template_id = src.template_id
        insp.selected_cats = src.selected_cats
        with db.session.no_autoflush:
            for ci, sc in enumerate(src.categories):
                cat = InspectionCategory(name=sc.name, rule=sc.rule, sort_order=ci,
                                         template_category_id=sc.template_category_id)
                insp.categories.append(cat)
                for ii, si in enumerate(sc.live_items):
                    new_item(insp, cat, si.name, ii, si.template_item_id, si.is_custom)
    db.session.add(insp)
    return insp


def template_categories(insp):
    tpl = db.session.get(ChecklistTemplate, insp.template_id) if insp.template_id else None
    tpl = tpl if tpl and tpl.is_active else default_template()
    return [c for c in (tpl.categories if tpl else []) if c.is_active]


def recommended_ids(insp, cats=None):
    rules = recommend_rules(insp.target, insp.zone, insp.work_type)
    return [c.id for c in (cats if cats is not None else template_categories(insp)) if c.rule in rules]


def compose(insp, selected_ids):
    """선택한 템플릿 분야로 체크리스트 구성 (아티팩트 buildSnapshot과 동일한 규칙).
    - 이미 구성된 분야는 응답과 함께 유지, 새로 선택한 분야는 템플릿에서 복사
    - 선택 해제된 분야는 응답·사진과 함께 삭제 (작성 중 점검이므로 실제 파일도 정리)
    - 공통(common) 분야는 항상 포함, 동일 문구 항목은 중복 추가하지 않음
    반환: 삭제된 응답 수"""
    tcats = template_categories(insp)
    by_id = {c.id: c for c in tcats}
    sel = {int(x) for x in selected_ids if str(x).isdigit() and int(x) in by_id}
    sel |= {c.id for c in tcats if c.rule == "common"}
    if not sel:
        raise ValueError("점검 분야를 1개 이상 선택하세요.")
    lost = 0
    keep = []
    for cat in list(insp.categories):
        tid = cat.template_category_id
        if tid in sel or (tid not in by_id and cat.live_items):  # 템플릿에서 사라진 분야는 기존 점검본 유지
            keep.append(cat)
            continue
        for it in list(cat.items):
            if it.result or it.memo or it.photos:
                lost += 1
            for p in it.photos:
                images.remove_file(p.stored_path)
                images.remove_file(p.thumb_path)
            insp.items.remove(it)
            db.session.delete(it)
        insp.categories.remove(cat)
        db.session.delete(cat)
    kept_tids = {c.template_category_id for c in keep}
    seen = {repeat.norm(it.name) for c in keep for it in c.live_items}
    order = 0
    with db.session.no_autoflush:
        for tc in tcats:
            if tc.id not in sel:
                continue
            if tc.id in kept_tids:
                for c in keep:
                    if c.template_category_id == tc.id:
                        c.sort_order = order
                order += 1
                continue
            cat = InspectionCategory(name=tc.name, rule=tc.rule, sort_order=order, template_category_id=tc.id)
            insp.categories.append(cat)
            order += 1
            ii = 0
            for ti in tc.active_items:
                k = repeat.norm(ti.name)
                if k in seen:
                    continue
                seen.add(k)
                new_item(insp, cat, ti.name, ii, ti.id)
                ii += 1
        for c in keep:
            if c.template_category_id not in by_id:
                c.sort_order = order
                order += 1
    insp.selected_cats = json.dumps(sorted(sel))
    insp.needs_recompose = 0
    return lost


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------
def serialize(insp, user, with_history=True):
    cats = categories_data(insp)
    items = flat_items(cats)
    logs = list(insp.change_logs)
    for c in cats:
        for it in c["items"]:
            it["change_logs"] = [{"from": l.from_result, "to": l.to_result, "reason": l.reason, "at": l.changed_at}
                                 for l in logs if l.item_id == it["id"] and l.kind == "change"]
    hist = {}
    if with_history and insp.place:
        idx = repeat.past_ng_index(user, insp.id)
        for it in insp.live_items:
            occ = idx.get(repeat.item_key(insp.place, it.template_item_id, it.name), [])
            if occ:
                hist[it.id] = [repeat.occ_row(p, pit) for p, pit in occ]
    tcats = template_categories(insp)
    s_insp, s_conf = insp.signature("inspector"), insp.signature("confirmer")
    return {
        "id": insp.public_id,
        "report_no": insp.report_no or "",
        "status": insp.status,
        "status_label": insp.status_label,
        "version": insp.version,
        "inspector_id": insp.inspector_id,
        "info": info_data(insp),
        "started_at": insp.started_at,
        "submitted_at": insp.submitted_at,
        "confirmed_at": insp.confirmed_at,
        "confirmer_name": insp.confirmer_name or "",
        "rejected_reason": insp.rejected_reason or "",
        "updated_at": insp.updated_at,
        "opinion": insp.opinion or "",
        "opinion_edited": bool(insp.opinion_edited),
        "composed": insp.is_composed,
        "needs_recompose": bool(insp.needs_recompose),
        "selected_cats": insp.selected_cat_ids,
        "template": [{"id": c.id, "name": c.name, "rule": c.rule, "items": [i.name for i in c.active_items]}
                     for c in tcats],
        "recommended": recommended_ids(insp, tcats),
        "categories": cats,
        "counts": judgment.counts(items),
        "history": hist,
        "signatures": {
            "inspector": bool(s_insp), "inspector_name": s_insp.signer_name if s_insp else "",
            "confirmer": bool(s_conf), "confirmer_name": s_conf.signer_name if s_conf else "",
        },
        "deleted_log": [
            {"name": l.item.name if l.item else "", "reason": l.reason, "at": l.changed_at}
            for l in logs if l.kind == "delete"
        ],
        "perms": perms_for(user, insp),
        "today": today_kst(),
        "repeat_days": current_app.config["REPEAT_DAYS"],
    }


def list_row(insp, user):
    items = [{"result": i.result, "na_reason": i.na_reason, "ng": {"status": i.action.status if i.action else "todo"}}
             for i in insp.live_items]
    c = judgment.counts(items)
    return {
        "id": insp.public_id,
        "report_no": insp.report_no or "",
        "status": insp.status,
        "status_label": insp.status_label,
        "info": {"inspector": insp.inspector_name, "dept": insp.inspector_org, "place": insp.place,
                 "date": insp.inspect_date, "time": insp.inspect_time, "insp_type": insp.insp_type,
                 "target_label": insp.target_label, "vehicle_type": insp.vehicle_type, "vehicle_no": insp.vehicle_no,
                 "equip_name": insp.equip_name},
        "counts": {k: c[k] for k in ("total", "ok", "ng", "na", "none", "valid", "progress", "rate")},
        "undone": judgment.undone_count(items),
        "composed": insp.is_composed,
        "is_mine": insp.inspector_id == user.id,
        "updated_at": insp.updated_at,
        "submitted_at": insp.submitted_at,
        "confirmed_at": insp.confirmed_at,
    }
