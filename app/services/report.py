"""점검 데이터 직렬화 + 보고서 구성.

- item_data / info_data: API 응답·최초 보고서 스냅샷·보고서 렌더링이 공통으로 쓰는 dict 형식
- build_report: 보고서 화면·인쇄 페이지가 쓰는 컨텍스트 (모드: draft / original / latest)
  * original(최초 보고서): 확인(확정) 시점에 저장한 스냅샷으로 출력 — 이후 조치 변경이 반영되지 않는다
  * latest(최신 개선조치 현황): 현재 조치 상태·사진 + 변경 이력
  * draft(확정 전 미리보기): 현재 입력 내용
"""
from flask import current_app

from ..models import ACTION_LABELS, RESULT_LABELS, RISK_LABELS, STATUS_LABELS
from ..timeutil import now_iso, today_kst
from . import judgment, repeat


def action_data(a):
    if not a:
        return {"content": "", "cause": "", "risk": "", "action": "", "owner": "", "due": "",
                "status": "todo", "done_date": ""}
    return {
        "content": a.content or "", "cause": a.cause or "", "risk": a.risk or "",
        "action": a.plan or "", "owner": a.owner_name or "", "due": a.due_date or "",
        "status": a.status or "todo", "done_date": a.done_date or "",
    }


def item_data(it):
    return {
        "id": it.id,
        "category_id": it.category_id,
        "template_item_id": it.template_item_id,
        "is_custom": bool(it.is_custom),
        "name": it.name,
        "result": it.result,
        "memo": it.memo or "",
        "na_reason": it.na_reason or "",
        "ng": action_data(it.action),
        "photos": [p.id for p in it.live_photos("finding")],
        "before": [p.id for p in it.live_photos("before")],
        "after": [p.id for p in it.live_photos("action")],
    }


def info_data(insp):
    return {
        "inspector": insp.inspector_name, "dept": insp.inspector_org, "place": insp.place,
        "date": insp.inspect_date, "time": insp.inspect_time, "insp_type": insp.insp_type,
        "target": insp.target, "target_etc": insp.target_etc, "zone": insp.zone, "zone_etc": insp.zone_etc,
        "work_type": insp.work_type, "work_type_etc": insp.work_type_etc,
        "vehicle_type": insp.vehicle_type, "vehicle_no": insp.vehicle_no,
        "equip_name": insp.equip_name, "equip_no": insp.equip_no,
        "target_label": insp.target_label, "zone_label": insp.zone_label, "work_type_label": insp.work_type_label,
    }


def categories_data(insp):
    return [
        {"id": c.id, "name": c.name, "rule": c.rule, "template_category_id": c.template_category_id,
         "items": [item_data(i) for i in c.live_items]}
        for c in insp.categories
    ]


def flat_items(cats):
    return [it for c in cats for it in c["items"]]


def make_snapshot(insp):
    return {"info": info_data(insp), "categories": categories_data(insp), "opinion": insp.opinion or "",
            "at": now_iso()}


def opinion_for(insp, user):
    days = current_app.config["REPEAT_DAYS"]
    items = flat_items(categories_data(insp))
    rep = repeat.repeat_item_ids(insp, user, days)
    return judgment.generate_opinion({"place": insp.place, "insp_type": insp.insp_type}, items, rep, today_kst(), days)


def build_report(insp, mode, user):
    snap = insp.snapshot
    if mode == "original" and not snap:
        mode = "latest" if insp.status == "confirmed" else "draft"
    if mode == "original":
        info, cats, opinion = snap["info"], snap["categories"], snap.get("opinion", "")
    else:
        info, cats, opinion = info_data(insp), categories_data(insp), insp.opinion or ""
    days = current_app.config["REPEAT_DAYS"]
    today = today_kst()
    rep_ids = repeat.repeat_item_ids(insp, user, days)
    items = flat_items(cats)
    c = judgment.counts(items)

    rows, ng_list, photos, no = [], [], [], 0
    cat_rows = []
    for cat in cats:
        cc = {"ok": 0, "ng": 0, "na": 0}
        for it in cat["items"]:
            no += 1
            r = it["result"]
            if r in cc:
                cc[r] += 1
            remark = []
            if r == "na" and it["na_reason"]:
                remark.append("사유: " + it["na_reason"])
            if it["memo"]:
                remark.append(it["memo"])
            rows.append({"no": no, "cat": cat["name"], "name": it["name"], "result": r,
                         "label": RESULT_LABELS.get(r, "미점검"), "remark": remark})
            if r == "ng":
                g = it["ng"]
                ng_list.append({
                    "it": it, "cat": cat["name"], "g": g,
                    "risk_label": RISK_LABELS.get(g.get("risk"), "-"),
                    "status_label": ACTION_LABELS.get(g.get("status"), g.get("status")),
                    "overdue": judgment.is_overdue(g, today),
                    "repeat": it["id"] in rep_ids,
                })
            for pid in it["photos"]:
                photos.append({"id": pid, "cap": f"[{cat['name']}] {it['name']} · {RESULT_LABELS.get(r, '')}"})
        cat_rows.append({"name": cat["name"], "total": len(cat["items"]), **cc})

    pairs = [x for x in ng_list if x["it"]["before"] or x["it"]["after"]]
    logs = []
    if mode == "latest":
        logs = [{"at": l.created_at, "item": l.item.name if l.item else "", "field": l.field,
                 "from": l.from_value or "-", "to": l.to_value or "-"} for l in insp.action_logs]
    s_insp, s_conf = insp.signature("inspector"), insp.signature("confirmer")
    total = c["total"]
    return {
        "mode": mode,
        "mode_label": {"draft": "확정 전 미리보기", "original": "최초 보고서(확정본)",
                       "latest": "최신 개선조치 현황 반영본"}[mode],
        "insp": insp, "info": info, "counts": c,
        "pct_total": {k: judgment.pct(c[k], total) for k in ("ok", "ng", "na")},
        "bar": {k: (c[k] / total * 100 if total else 0) for k in ("ok", "ng", "na")},
        "fmt_pct": judgment.fmt_pct,
        "cat_rows": cat_rows, "rows": rows, "ng_list": ng_list, "pairs": pairs, "photos": photos,
        "opinion": opinion, "logs": logs,
        "sig_inspector": s_insp, "sig_confirmer": s_conf,
        "workflow": insp.workflow_logs,
        "change_logs": insp.change_logs,
        "status_labels": STATUS_LABELS, "result_labels": RESULT_LABELS,
        "now": now_iso(),
    }
