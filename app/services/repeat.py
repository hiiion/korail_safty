"""반복 지적사항 · 과거 부적합 이력.

반복 지적사항: 동일 장소 + 동일 점검 항목에서 최근 N일(기본 60일) 이내 부적합 2회 이상.
"동일 항목"은 같은 템플릿 항목(template_item_id)이면 같고, 사용자 추가 항목은 문구(공백 무시)로 비교한다.
대상은 제출·확정된 점검이며, 사용자가 조회 권한을 가진 점검만 본다.
"""
import re
from datetime import date, timedelta

from ..extensions import db
from ..models import Inspection, InspectionItem
from .permissions import visible_inspections

COMPLETED = ("submitted", "confirmed")


def norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def item_key(place, template_item_id, name):
    return norm(place) + "|" + (f"t{template_item_id}" if template_item_id else norm(name))


def _shift(day_iso, days):
    try:
        return (date.fromisoformat(day_iso) - timedelta(days=days)).isoformat()
    except (TypeError, ValueError):
        return "0000-00-00"


def ng_occurrences(user):
    """조회 가능한 제출·확정 점검의 부적합 항목 목록 [(insp, item)]."""
    q = (
        db.session.query(Inspection, InspectionItem)
        .join(InspectionItem, InspectionItem.inspection_id == Inspection.id)
        .filter(Inspection.id.in_(visible_inspections(user).with_entities(Inspection.id)))
        .filter(Inspection.status.in_(COMPLETED), InspectionItem.result == "ng", InspectionItem.is_deleted == 0)
    )
    return q.all()


def repeat_groups(user, today, days):
    since = _shift(today, days)
    groups = {}
    for insp, it in ng_occurrences(user):
        if insp.inspect_date < since:
            continue
        k = item_key(insp.place, it.template_item_id, it.name)
        g = groups.setdefault(k, {"key": k, "place": insp.place, "text": it.name,
                                  "cat": it.category.name if it.category else "", "occ": []})
        g["occ"].append((insp, it))
    out = []
    for g in groups.values():
        if len(g["occ"]) < 2:
            continue
        g["occ"].sort(key=lambda x: (x[0].inspect_date, x[0].inspect_time), reverse=True)
        g["count"] = len(g["occ"])
        g["last"] = g["occ"][0][0].inspect_date
        out.append(g)
    out.sort(key=lambda g: (g["count"], g["last"]), reverse=True)
    return out


def repeat_key_set(user, today, days):
    return {g["key"] for g in repeat_groups(user, today, days)}


def past_ng_index(user, exclude_insp_id=None):
    """item_key → [(insp, item)] (제외 점검 빼고, 최신순)."""
    idx = {}
    for insp, it in ng_occurrences(user):
        if insp.id == exclude_insp_id:
            continue
        idx.setdefault(item_key(insp.place, it.template_item_id, it.name), []).append((insp, it))
    for v in idx.values():
        v.sort(key=lambda x: (x[0].inspect_date, x[0].inspect_time), reverse=True)
    return idx


def repeat_item_ids(insp, user, days, index=None):
    """이번 점검의 부적합 항목 중 반복 지적에 해당하는 항목 id 집합.
    (이번 점검일 이전 N일 내 동일 장소·항목 부적합이 1회 이상 있으면 반복)"""
    index = index if index is not None else past_ng_index(user, insp.id)
    since = _shift(insp.inspect_date, days)
    out = set()
    for it in insp.live_items:
        if it.result != "ng":
            continue
        for p, _pit in index.get(item_key(insp.place, it.template_item_id, it.name), []):
            if since <= p.inspect_date <= insp.inspect_date:
                out.add(it.id)
                break
    return out


def occ_row(insp, it):
    a = it.action
    return {
        "date": insp.inspect_date, "report_no": insp.report_no or "(확정 전)", "insp_id": insp.public_id,
        "content": a.content if a else "", "risk": a.risk if a else None, "action": a.plan if a else "",
        "status": a.status if a else "todo",
    }
