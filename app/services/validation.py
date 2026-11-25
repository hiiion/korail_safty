"""제출 전 검증 (서버 측). 클라이언트 검증은 편의용일 뿐이다."""
from . import judgment
from .report import item_data

# (필드 key, 화면 표기) — 아티팩트 infoMissing과 같은 순서
INFO_LABELS = {
    "inspector": "점검자 성명", "dept": "소속 부서", "place": "점검 장소", "date": "점검 일시", "insp_type": "점검 유형",
    "target": "점검 대상", "target_etc": "점검 대상(직접 입력)", "zone": "작업구역", "zone_etc": "작업구역(직접 입력)",
    "work_type": "작업 유형", "work_type_etc": "작업 유형(직접 입력)", "vehicle_type": "차량 종류",
    "vehicle_no": "차량번호", "equip_name": "설비명", "equip_no": "설비 관리번호",
}

REASON_MESSAGES = {
    "result_required": "점검 결과를 선택하세요.",
    "na_reason_required": "해당 없음 사유를 입력하세요.",
    "ng_detail_required": "부적합 세부정보(내용·원인·위험도·개선조치·담당자·예정일)를 모두 입력하세요.",
}


def missing_info(insp):
    v = {
        "inspector": insp.inspector_name, "dept": insp.inspector_org, "place": insp.place,
        "date": insp.inspect_date, "insp_type": insp.insp_type, "target": insp.target,
        "zone": insp.zone, "work_type": insp.work_type,
    }
    need = ["inspector", "dept", "place", "date", "insp_type", "target"]
    if insp.target == "기타":
        need.append("target_etc")
        v["target_etc"] = insp.target_etc
    need.append("zone")
    if insp.zone == "기타":
        need.append("zone_etc")
        v["zone_etc"] = insp.zone_etc
    need.append("work_type")
    if insp.work_type == "기타":
        need.append("work_type_etc")
        v["work_type_etc"] = insp.work_type_etc
    if insp.target == "철도차량":
        need += ["vehicle_type", "vehicle_no"]
        v.update(vehicle_type=insp.vehicle_type, vehicle_no=insp.vehicle_no)
    if insp.target == "정비설비":
        need += ["equip_name", "equip_no"]
        v.update(equip_name=insp.equip_name, equip_no=insp.equip_no)
    return {k: INFO_LABELS[k] for k in need if not str(v.get(k) or "").strip()}


def item_problem(d):
    if not d.get("result"):
        return "result_required"
    if d["result"] == "na" and not str(d.get("na_reason") or "").strip():
        return "na_reason_required"
    if d["result"] == "ng" and judgment.ng_missing(d):
        return "ng_detail_required"
    return None


def incomplete_items(insp):
    out = []
    for cat in insp.categories:
        for it in cat.live_items:
            d = item_data(it)
            p = item_problem(d)
            if p:
                extra = {"missing": judgment.ng_missing(d)} if p == "ng_detail_required" else {}
                out.append({"item_id": it.id, "category_id": cat.id, "reason": p,
                            "message": REASON_MESSAGES[p], "name": it.name, **extra})
    return out
