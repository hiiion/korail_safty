"""JSON 내보내기·불러오기, 통계 CSV.

내보내기 형식 (app: "railway-safety-inspection", version 2)
  - 사진은 최상위 photos 목록에 base64(data URL)로 한 번만 담고, 항목은 사진 id로 참조한다
    (참고 아티팩트의 백업 형식과 같은 구조)
  - original: 확인(확정) 시점 보고서 스냅샷
불러오기
  - 이 웹앱의 내보내기 파일 + 참고 아티팩트(app: "SRSI")의 전체 백업 파일을 모두 받는다
  - 형식 검증 → 미리보기(충돌 목록) → 덮어쓰기/건너뛰기 선택 후 확정
"""
import csv
import io
import json
import re

from ..extensions import db
from ..models import (
    ACTION_LABELS,
    RISK_LABELS,
    ActionChangeLog,
    Inspection,
    InspectionCategory,
    InspectionItem,
    ItemAction,
    Photo,
    ResultChangeLog,
    Signature,
    TemplateItem,
    User,
    WorkflowLog,
)
from ..timeutil import is_valid_date, iso_to_ms, ms_to_iso, now_iso, parse_iso, to_kst
from . import images, judgment, report

APP_ID = "railway-safety-inspection"
DATA_VERSION = 2
ARTIFACT_APP_ID = "SRSI"
LABEL_TO_ACTION = {v: k for k, v in ACTION_LABELS.items()}
RESULTS = ("ok", "ng", "na")
MAX_PHOTOS = 10


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------
def _pk(pid):
    return f"p{pid}"


def _ng_json(g):
    return {"content": g["content"], "cause": g["cause"], "risk": g["risk"], "action": g["action"],
            "owner": g["owner"], "due": g["due"], "status": g["status"], "doneDate": g["done_date"]}


def _item_json(d, logs=None):
    return {
        "id": f"i{d['id']}", "name": d["name"], "custom": d["is_custom"], "result": d["result"],
        "memo": d["memo"], "naReason": d["na_reason"], "photos": [_pk(x) for x in d["photos"]],
        "ng": dict(_ng_json(d["ng"]), beforePhotos=[_pk(x) for x in d["before"]],
                   afterPhotos=[_pk(x) for x in d["after"]]),
        "changeLog": [{"from": l.from_result, "to": l.to_result, "reason": l.reason, "at": iso_to_ms(l.changed_at) or 0}
                      for l in (logs or []) if l.item_id == d["id"] and l.kind == "change"],
    }


def inspection_to_json(insp, photo_ids):
    logs = list(insp.change_logs)
    cats = report.categories_data(insp)
    for c in cats:
        for d in c["items"]:
            photo_ids.update(d["photos"] + d["before"] + d["after"])
    snap = insp.snapshot
    original = None
    if snap:
        original = {"opinion": snap.get("opinion", ""), "at": iso_to_ms(snap.get("at")),
                    "categories": [{"name": c["name"], "rule": c.get("rule", "custom"),
                                    "items": [_item_json(d) for d in c["items"]]} for c in snap["categories"]]}
        for c in snap["categories"]:
            for d in c["items"]:
                photo_ids.update(d["photos"] + d["before"] + d["after"])

    def sig(role):
        s = insp.signature(role)
        return images.file_to_data_url(s.image_path, "image/png") if s else ""

    i = report.info_data(insp)
    return {
        "id": insp.public_id,
        "reportNo": insp.report_no or "",
        "workflowStatus": insp.status,
        "inspectorUsername": insp.inspector.username if insp.inspector else "",
        "info": {k: i[k] for k in ("inspector", "dept", "place", "date", "time", "insp_type", "target", "target_etc",
                                   "zone", "zone_etc", "work_type", "work_type_etc", "vehicle_type", "vehicle_no",
                                   "equip_name", "equip_no")},
        "opinion": insp.opinion or "",
        "opinionEdited": bool(insp.opinion_edited),
        "startedAt": iso_to_ms(insp.started_at),
        "submittedAt": iso_to_ms(insp.submitted_at),
        "createdAt": iso_to_ms(insp.created_at),
        "confirmedAt": iso_to_ms(insp.confirmed_at),
        "confirmerName": insp.confirmer_name or "",
        "rejectedReason": insp.rejected_reason or "",
        "categories": [{"name": c["name"], "rule": c["rule"], "items": [_item_json(d, logs) for d in c["items"]]}
                       for c in cats],
        "original": original,
        "actionLog": [{"itemId": f"i{l.item_id}", "field": l.field, "from": l.from_value or "", "to": l.to_value or "",
                       "at": iso_to_ms(l.created_at) or 0} for l in insp.action_logs],
        "deletedLog": [
            {"category": l.item.category.name if l.item and l.item.category else "", "name": l.item.name if l.item else "",
             "reason": l.reason, "at": iso_to_ms(l.changed_at) or 0}
            for l in logs if l.kind == "delete"
        ],
        "workflowLog": [{"action": w.action, "reason": w.reason or "", "at": iso_to_ms(w.created_at),
                         "user": w.user.name if w.user else ""} for w in insp.workflow_logs],
        "signatures": {"inspector": sig("inspector"), "confirmer": sig("confirmer"),
                       "confirmerName": insp.confirmer_name or ""},
    }


def export_payload(inspections):
    photo_ids = set()
    lst = [inspection_to_json(i, photo_ids) for i in inspections]
    photos = []
    for p in Photo.query.filter(Photo.id.in_(photo_ids)).order_by(Photo.id).all() if photo_ids else []:
        u = images.file_to_data_url(p.stored_path, p.mime)
        if u:
            photos.append({"id": _pk(p.id), "data": u})
    from datetime import datetime, timezone

    return {
        "app": APP_ID, "version": DATA_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(lst), "inspections": lst, "photos": photos,
    }


# ---------------------------------------------------------------------------
# 불러오기 — 형식 검증 및 정리 (두 형식 → 공통 구조)
# ---------------------------------------------------------------------------
def _s(v, n=4000):
    return v[:n] if isinstance(v, str) else ""


def _keys(a):
    return [x for x in a if isinstance(x, str)][:50] if isinstance(a, list) else []


def _status_code(v):
    return v if v in ACTION_LABELS else LABEL_TO_ACTION.get(v, "todo")


def _ng(g):
    g = g if isinstance(g, dict) else {}
    return {
        "content": _s(g.get("content")), "cause": _s(g.get("cause")),
        "risk": g.get("risk") if g.get("risk") in RISK_LABELS else None,
        "action": _s(g.get("action")), "owner": _s(g.get("owner"), 60),
        "due": g.get("due") if is_valid_date(g.get("due")) else None,
        "status": _status_code(g.get("status")),
        "done_date": g.get("doneDate") if is_valid_date(g.get("doneDate")) else None,
        "before": _keys(g.get("beforePhotos")), "after": _keys(g.get("afterPhotos")),
    }


def _norm_item(key, name, tid, custom, r):
    """r: 응답 dict (result, memo/note, naReason, photos, ng)."""
    r = r if isinstance(r, dict) else {}
    return {
        "key": str(key), "name": name[:200], "tid": tid, "custom": bool(custom),
        "result": r.get("result") if r.get("result") in RESULTS else None,
        "memo": _s(r.get("memo", r.get("note"))), "na_reason": _s(r.get("naReason")),
        "photos": _keys(r.get("photos")), "ng": _ng(r.get("ng")),
        "change_log": [
            {"from": l["from"], "to": l["to"], "reason": _s(l.get("reason"), 1000), "at": ms_to_iso(l.get("at"))}
            for l in (r.get("changeLog") or []) if isinstance(l, dict) and l.get("from") in RESULTS and l.get("to") in RESULTS
        ],
    }


def _norm_cats_native(cats):
    out = []
    for c in cats:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("items"), list):
            raise ValueError
        items = []
        for it in c["items"]:
            if not isinstance(it, dict) or not isinstance(it.get("name"), str):
                raise ValueError
            items.append(_norm_item(it.get("id", ""), it["name"], None, it.get("custom"), it))
        out.append({"name": c["name"][:100], "rule": _s(c.get("rule"), 20) or "custom", "items": items})
    return out


def _info_native(info):
    keys = ("inspector", "dept", "place", "date", "time", "insp_type", "target", "target_etc", "zone", "zone_etc",
            "work_type", "work_type_etc", "vehicle_type", "vehicle_no", "equip_name", "equip_no")
    out = {k: _s(info.get(k), 100) for k in keys}
    if not is_valid_date(out["date"]):
        out["date"] = ""
    if not re.fullmatch(r"\d{2}:\d{2}", out["time"] or ""):
        out["time"] = ""
    return out


def normalize_native(x):
    try:
        if not isinstance(x, dict) or not isinstance(x.get("id"), str) or not x["id"].strip():
            return None
        if not isinstance(x.get("info"), dict) or not isinstance(x.get("categories"), list):
            return None
        wf = x.get("workflowStatus")
        o = x.get("original") if isinstance(x.get("original"), dict) else None
        sigs = x.get("signatures") if isinstance(x.get("signatures"), dict) else {}
        return {
            "id": x["id"].strip()[:100], "report_no": _s(x.get("reportNo"), 60),
            "status": wf if wf in ("draft", "submitted", "confirmed", "rejected") else "draft",
            "inspector_username": _s(x.get("inspectorUsername"), 100),
            "info": _info_native(x["info"]),
            "opinion": _s(x.get("opinion"), 8000), "opinion_edited": bool(x.get("opinionEdited")),
            "started_at": ms_to_iso(x.get("startedAt")), "submitted_at": ms_to_iso(x.get("submittedAt")),
            "created_at": ms_to_iso(x.get("createdAt")), "confirmed_at": ms_to_iso(x.get("confirmedAt")),
            "confirmer_name": _s(x.get("confirmerName"), 60), "rejected_reason": _s(x.get("rejectedReason"), 1000),
            "categories": _norm_cats_native(x["categories"]),
            "original": ({"opinion": _s(o.get("opinion"), 8000), "categories": _norm_cats_native(o.get("categories") or [])}
                         if o else None),
            "action_log": [{"item": str(l.get("itemId")), "field": _s(l.get("field"), 40), "from": _s(l.get("from"), 400),
                            "to": _s(l.get("to"), 400), "at": ms_to_iso(l.get("at"))}
                           for l in (x.get("actionLog") or []) if isinstance(l, dict)],
            "deleted_log": [{"category": _s(l.get("category"), 100), "name": _s(l.get("name"), 200),
                             "reason": _s(l.get("reason"), 1000), "at": ms_to_iso(l.get("at"))}
                            for l in (x.get("deletedLog") or []) if isinstance(l, dict) and isinstance(l.get("name"), str)],
            "sig_inspector": sigs.get("inspector") if isinstance(sigs.get("inspector"), str) else "",
            "sig_confirmer": sigs.get("confirmer") if isinstance(sigs.get("confirmer"), str) else "",
        }
    except (TypeError, KeyError, AttributeError, ValueError):
        return None


def _kst_split(ms_or_local):
    """아티팩트 점검 일시('YYYY-MM-DDTHH:MM', 현장 기준) → (date, time)."""
    s = ms_or_local if isinstance(ms_or_local, str) else ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", s)
    if m and is_valid_date(m.group(1)):
        return m.group(1), m.group(2)
    return "", ""


def normalize_artifact(x, status):
    try:
        if not isinstance(x, dict) or not isinstance(x.get("id"), str) or not isinstance(x.get("info"), dict):
            return None
        if not isinstance(x.get("categories"), list) or not isinstance(x.get("responses"), dict):
            return None
        i = x["info"]
        d, t = _kst_split(i.get("datetime"))
        info = {
            "inspector": _s(i.get("inspector"), 60), "dept": _s(i.get("dept"), 60), "place": _s(i.get("place"), 100),
            "date": d, "time": t, "insp_type": _s(i.get("inspType"), 20),
            "target": _s(i.get("target"), 40), "target_etc": _s(i.get("targetEtc"), 60),
            "zone": _s(i.get("zone"), 40), "zone_etc": _s(i.get("zoneEtc"), 60),
            "work_type": _s(i.get("workType"), 40), "work_type_etc": _s(i.get("workTypeEtc"), 60),
            "vehicle_type": _s(i.get("vehicleType"), 60), "vehicle_no": _s(i.get("vehicleNo"), 30),
            "equip_name": _s(i.get("equipName"), 60), "equip_no": _s(i.get("equipNo"), 30),
        }

        def cats_with(resps):
            out = []
            for c in x["categories"]:
                if not isinstance(c, dict) or not isinstance(c.get("items"), list):
                    raise ValueError
                items = [_norm_item(it.get("id", ""), _s(it.get("text"), 200), it.get("tid"), it.get("custom"),
                                    resps.get(it.get("id")))
                         for it in c["items"] if isinstance(it, dict) and isinstance(it.get("text"), str)]
                out.append({"name": _s(c.get("name"), 100), "rule": _s(c.get("rule"), 20) or "custom", "items": items})
            return out

        o = x.get("original") if isinstance(x.get("original"), dict) else None
        done = ms_to_iso(x.get("completedAt"))
        return {
            "id": x["id"][:100], "report_no": _s(x.get("docNo"), 60), "status": status,
            "inspector_username": "", "info": info,
            "opinion": _s(x.get("opinion"), 8000), "opinion_edited": bool(x.get("opinionEdited")),
            "started_at": ms_to_iso(x.get("createdAt")), "submitted_at": done,
            "created_at": ms_to_iso(x.get("createdAt")), "confirmed_at": done,
            "confirmer_name": "", "rejected_reason": "",
            "categories": cats_with(x["responses"]),
            "original": ({"opinion": _s(o.get("opinion"), 8000), "categories": cats_with(o.get("responses") or {})}
                         if o and isinstance(o.get("responses"), dict) else None),
            "action_log": [{"item": str(l.get("itemId")), "field": _s(l.get("field"), 40), "from": _s(l.get("from"), 400),
                            "to": _s(l.get("to"), 400), "at": ms_to_iso(l.get("at"))}
                           for l in (x.get("actionLog") or []) if isinstance(l, dict)],
            "deleted_log": [], "sig_inspector": "", "sig_confirmer": "",
        }
    except (TypeError, KeyError, AttributeError, ValueError):
        return None


def _photo_map(lst):
    out = {}
    for p in lst if isinstance(lst, list) else []:
        if isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("data"), str) \
                and p["data"].startswith("data:image/"):
            out[p["id"]] = p["data"]
    return out


def parse_file(obj):
    """반환: (valid 목록, bad 번호 목록, 사진 map, 형식 이름) 또는 오류 메시지 문자열."""
    if not isinstance(obj, dict):
        return "올바른 JSON 파일이 아닙니다."
    valid, bad = [], []
    if obj.get("app") == APP_ID and isinstance(obj.get("inspections"), list):
        if not isinstance(obj.get("version"), int) or obj["version"] > DATA_VERSION:
            return "지원하지 않는 데이터 구조 버전입니다."
        for i, x in enumerate(obj["inspections"]):
            n = normalize_native(x)
            (valid.append(n) if n else bad.append(i + 1))
        photos, kind = _photo_map(obj.get("photos")), "웹앱 내보내기"
    elif obj.get("app") == ARTIFACT_APP_ID and isinstance(obj.get("data"), dict):
        d = obj["data"]
        if not isinstance(obj.get("schemaVersion"), int) or obj["schemaVersion"] < 1 or obj["schemaVersion"] > 1:
            return "지원하지 않는 아티팩트 백업 버전입니다."
        if not all(isinstance(d.get(k), list) for k in ("inspections", "drafts", "photos")):
            return "아티팩트 백업 파일의 필수 데이터가 없습니다."
        for i, x in enumerate(d["inspections"]):
            n = normalize_artifact(x, "confirmed")
            (valid.append(n) if n else bad.append(i + 1))
        for i, x in enumerate(d["drafts"]):
            n = normalize_artifact(x, "draft")
            (valid.append(n) if n else bad.append(len(d["inspections"]) + i + 1))
        photos, kind = _photo_map(d.get("photos")), "아티팩트 백업"
    else:
        return "스마트 철도차량 안전점검 시스템에서 내보낸 파일이 아닙니다."
    if not valid:
        return "파일에 올바른 형식의 점검 데이터가 없습니다."
    return valid, bad, photos, kind


def remove_inspection_files(insp):
    for it in insp.items:
        for p in it.photos:
            images.remove_file(p.stored_path)
            images.remove_file(p.thumb_path)
    for s in insp.signatures:
        images.remove_file(s.image_path)


def _template_item_id(name, cache):
    from .repeat import norm

    if "map" not in cache:
        cache["map"] = {norm(t.name): t.id for t in TemplateItem.query.filter_by(is_active=1).all()}
    return cache["map"].get(norm(name))


def import_one(n, photos, user, existing=None, cache=None):
    cache = cache if cache is not None else {}
    owner = None
    if n["inspector_username"]:
        owner = User.query.filter_by(username=n["inspector_username"]).first()
    if not owner and existing is not None:
        owner = existing.inspector
    owner = owner or user
    if existing is not None:
        remove_inspection_files(existing)
        db.session.delete(existing)
        db.session.flush()

    now = now_iso()
    info = n["info"]
    report_no = n["report_no"] or None
    if report_no and Inspection.query.filter_by(report_no=report_no).first():
        report_no = None
    status = n["status"]
    if status == "confirmed" and not report_no:
        from . import report_no as rn

        report_no = rn.issue((n["confirmed_at"] and to_kst(n["confirmed_at"]).date().isoformat()) or None)
    insp = Inspection(
        public_id=n["id"], report_no=report_no, status=status,
        inspector_id=owner.id, inspector_name=info["inspector"] or owner.name, inspector_org=info["dept"],
        place=info["place"], inspect_date=info["date"] or now[:10], inspect_time=info["time"],
        insp_type=info["insp_type"], target=info["target"], target_etc=info["target_etc"],
        zone=info["zone"], zone_etc=info["zone_etc"], work_type=info["work_type"], work_type_etc=info["work_type_etc"],
        vehicle_type=info["vehicle_type"], vehicle_no=info["vehicle_no"],
        equip_name=info["equip_name"], equip_no=info["equip_no"],
        opinion=n["opinion"], opinion_edited=1 if n["opinion_edited"] else 0,
        started_at=n["started_at"], submitted_at=n["submitted_at"] if status != "draft" else None,
        confirmed_at=n["confirmed_at"] if status == "confirmed" else None,
        confirmer_name=(n["confirmer_name"] or (user.name if status == "confirmed" else None)),
        rejected_reason=n["rejected_reason"] or None,
        created_at=n["created_at"] or now, updated_at=now,
    )
    if status == "confirmed":
        insp.confirmer_id = user.id
    db.session.add(insp)
    db.session.flush()

    saved = {}  # 원본 사진 key → Photo

    def add_photo(item, kind, key, deleted=False):
        if key in saved:
            return saved[key]
        raw = images.decode_data_url(photos.get(key))
        if not raw:
            return None
        try:
            meta = images.process_photo(raw)
        except images.ImageError:
            return None
        p = Photo(kind=kind, uploaded_by=user.id, original_name="imported.jpg", created_at=now,
                  is_deleted=1 if deleted else 0, **meta)
        item.photos.append(p)
        saved[key] = p
        return p

    item_by_key = {}
    for ci, c in enumerate(n["categories"]):
        cat = InspectionCategory(name=c["name"], rule=c["rule"], sort_order=ci)
        insp.categories.append(cat)
        for ii, d in enumerate(c["items"]):
            it = InspectionItem(name=d["name"], sort_order=ii, result=d["result"], memo=d["memo"],
                                na_reason=d["na_reason"], updated_at=now, is_custom=1 if d["custom"] else 0,
                                template_item_id=None if d["custom"] else _template_item_id(d["name"], cache))
            with db.session.no_autoflush:
                insp.items.append(it)
                cat.items.append(it)
            g = d["ng"]
            it.action = ItemAction(content=g["content"], cause=g["cause"], risk=g["risk"], plan=g["action"],
                                   owner_name=g["owner"], due_date=g["due"], status=g["status"],
                                   done_date=g["done_date"], updated_by=user.id, updated_at=now)
            db.session.flush()
            item_by_key[d["key"]] = it
            for k in d["photos"][:MAX_PHOTOS]:
                add_photo(it, "finding", k)
            for k in g["before"][:MAX_PHOTOS]:
                add_photo(it, "before", k)
            for k in g["after"][:MAX_PHOTOS]:
                add_photo(it, "action", k)
            for l in d["change_log"]:
                db.session.add(ResultChangeLog(inspection_id=insp.id, item_id=it.id, kind="change", from_result=l["from"],
                                               to_result=l["to"], reason=l["reason"] or "(사유 없음)", changed_by=user.id,
                                               changed_at=l["at"] or now))
    db.session.flush()

    for l in n["deleted_log"]:
        cat = next((c for c in insp.categories if c.name == l["category"]), None) or (insp.categories[0] if insp.categories else None)
        if cat is None:
            cat = InspectionCategory(name=l["category"] or "기타", sort_order=99)
            insp.categories.append(cat)
        it = InspectionItem(name=l["name"], result="ng", is_deleted=1, deleted_reason=l["reason"], deleted_by=user.id,
                            deleted_at=l["at"] or now, updated_at=now)
        with db.session.no_autoflush:
            insp.items.append(it)
            cat.items.append(it)
        db.session.flush()
        db.session.add(ResultChangeLog(inspection_id=insp.id, item_id=it.id, kind="delete", from_result="ng",
                                       to_result=None, reason=l["reason"] or "(사유 없음)", changed_by=user.id,
                                       changed_at=l["at"] or now))

    for l in n["action_log"]:
        it = item_by_key.get(l["item"]) or item_by_key.get(l["item"].lstrip("i"))
        if it:
            db.session.add(ActionChangeLog(inspection_id=insp.id, item_id=it.id, field=l["field"] or "변경",
                                           from_value=l["from"], to_value=l["to"], user_id=user.id,
                                           created_at=l["at"] or now))

    for role, data in (("inspector", n["sig_inspector"]), ("confirmer", n["sig_confirmer"])):
        if data:
            try:
                rel = images.save_signature(data)
            except images.ImageError:
                continue
            signer = owner if role == "inspector" else user
            name = insp.inspector_name if role == "inspector" else (insp.confirmer_name or user.name)
            insp.signatures.append(Signature(role=role, signer_id=signer.id, signer_name=name, image_path=rel, signed_at=now))
    if status in ("submitted", "confirmed"):
        db.session.add(WorkflowLog(inspection_id=insp.id, action="submit", user_id=owner.id,
                                   created_at=insp.submitted_at or now))
    if status == "confirmed":
        db.session.add(WorkflowLog(inspection_id=insp.id, action="confirm", user_id=user.id,
                                   created_at=insp.confirmed_at or now))
    db.session.flush()

    # 최초 보고서 스냅샷: 원본 데이터가 있으면 그 결과로, 없으면 현재 상태로 보존
    if status == "confirmed":
        snap = report.make_snapshot(insp)
        o = n.get("original")
        if o:
            ocats = []
            for c in o["categories"]:
                items = []
                for d in c["items"]:
                    it = item_by_key.get(d["key"])
                    if not it:
                        continue
                    g = d["ng"]

                    def ids(keys, kind, _it=it):
                        out = []
                        for k in keys[:MAX_PHOTOS]:
                            p = saved.get(k) or add_photo(_it, kind, k, deleted=True)
                            if p is not None:
                                db.session.flush()
                                out.append(p.id)
                        return out

                    items.append({
                        "id": it.id, "category_id": it.category_id, "template_item_id": it.template_item_id,
                        "is_custom": bool(it.is_custom), "name": d["name"], "result": d["result"],
                        "memo": d["memo"], "na_reason": d["na_reason"],
                        "ng": {"content": g["content"], "cause": g["cause"], "risk": g["risk"] or "",
                               "action": g["action"], "owner": g["owner"], "due": g["due"] or "",
                               "status": g["status"], "done_date": g["done_date"] or ""},
                        "photos": ids(d["photos"], "finding"), "before": ids(g["before"], "before"),
                        "after": ids(g["after"], "action"),
                    })
                ocats.append({"id": None, "name": c["name"], "rule": c["rule"], "template_category_id": None, "items": items})
            snap["categories"] = ocats
            snap["opinion"] = o["opinion"] or snap["opinion"]
        snap["at"] = insp.confirmed_at or now
        insp.original_snapshot = json.dumps(snap, ensure_ascii=False)
        for it in insp.items:
            it.original_result, it.original_memo, it.original_na_reason = it.result, it.memo, it.na_reason
            it.original_saved_at = insp.confirmed_at or now
    return insp


# ---------------------------------------------------------------------------
# 통계 CSV (UTF-8 BOM — 엑셀에서 바로 열림)
# ---------------------------------------------------------------------------
def _cell(v):
    if isinstance(v, (int, float)):
        return v
    s = "" if v is None else str(v)
    if re.match(r"^[=+\-@\t\r]", s):  # 엑셀 수식 삽입 방지
        s = "'" + s
    return s


def _csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\r\n")
    for r in rows:
        w.writerow([_cell(v) for v in r])
    return "﻿" + buf.getvalue()


def _kst_text(iso):
    d = to_kst(iso) if parse_iso(iso) else None
    return d.strftime("%Y-%m-%d %H:%M") if d else ""


def summary_csv(inspections, today):
    rows = [["관리번호", "상태", "점검일시", "점검자", "소속", "점검장소", "점검유형", "점검대상", "작업구역", "작업유형", "차량종류",
             "차량번호", "설비명", "설비관리번호", "전체항목", "적합", "부적합", "해당없음", "미점검", "적합률(%)", "미완료조치",
             "기한초과", "제출일시", "확정일시"]]
    for insp in inspections:
        items = report.flat_items(report.categories_data(insp))
        c = judgment.counts(items)
        od = sum(1 for d in items if d["result"] == "ng" and judgment.is_overdue(d["ng"], today))
        rows.append([insp.report_no or "", insp.status_label, insp.inspect_dt, insp.inspector_name, insp.inspector_org,
                     insp.place, insp.insp_type, insp.target_label, insp.zone_label, insp.work_type_label,
                     insp.vehicle_type, insp.vehicle_no, insp.equip_name, insp.equip_no, c["total"], c["ok"], c["ng"],
                     c["na"], c["none"], "산정 대상 없음" if c["rate"] is None else c["rate"], judgment.undone_count(items),
                     od, _kst_text(insp.submitted_at), _kst_text(insp.confirmed_at)])
    return _csv(rows)


def detail_csv(inspections, today):
    rows = [["관리번호", "상태", "점검일시", "점검장소", "점검자", "분야", "점검항목", "결과", "해당없음사유", "특이사항", "부적합내용",
             "발생원인", "위험도", "개선조치", "조치담당자", "조치예정일", "조치상태(현재)", "조치완료일", "기한초과", "사진수"]]
    for insp in inspections:
        for c in report.categories_data(insp):
            for d in c["items"]:
                g = d["ng"]
                ng = d["result"] == "ng"
                rows.append([insp.report_no or "", insp.status_label, insp.inspect_dt, insp.place, insp.inspector_name,
                             c["name"], d["name"], {"ok": "적합", "ng": "부적합", "na": "해당 없음"}.get(d["result"], "미점검"),
                             d["na_reason"], d["memo"], g["content"] if ng else "", g["cause"] if ng else "",
                             RISK_LABELS.get(g["risk"], "") if ng else "", g["action"] if ng else "",
                             g["owner"] if ng else "", g["due"] if ng else "",
                             ACTION_LABELS.get(g["status"], "") if ng else "", g["done_date"] if ng else "",
                             ("Y" if judgment.is_overdue(g, today) else "N") if ng else "",
                             len(d["photos"]) + len(d["before"]) + len(d["after"])])
    return _csv(rows)
