"""집계·적합률·종합의견 초안 — 단일 진실 원천.

화면(API 응답), 보고서, 통계, 이력 필터가 모두 이 모듈의 함수를 사용한다.
규칙은 참고 아티팩트와 동일하다.
  - 항목 상태: 미점검 / 입력 미완료 / 적합 / 부적합 / 해당 없음
  - 입력 완료: 적합 · 해당 없음(사유 필수) · 부적합(내용·원인·위험도·개선조치·담당자·예정일 필수)
  - 진행률 = 입력 완료 ÷ 전체 × 100 (실제 안전 판정과 별개)
  - 적합률 = 적합 ÷ (적합 + 부적합) × 100  → 해당 없음·미점검은 제외
  - 종합의견: 위험도 '상' → 기한 초과 → 미완료 조치 → 반복 지적 순으로 반영하고,
    해당 사항이 없을 때만 적합률(95% / 85%)로 양호 여부를 서술한다.

함수들은 모두 "항목 dict"를 입력으로 받는다(services/report.py의 item_data 형식).
  {"result": "ok|ng|na|None", "na_reason": str, "name": str,
   "ng": {"content","cause","risk","action","owner","due","status"}}
"""

NG_REQUIRED = [
    ("content", "부적합 내용"), ("cause", "발생 원인"), ("risk", "위험도"),
    ("action", "개선조치 내용"), ("owner", "조치 담당자"), ("due", "조치 예정일"),
]
RISK_LABELS = {"h": "상", "m": "중", "l": "하"}
STATUS_KO = {"todo": "미조치", "in_progress": "조치 중", "done": "조치 완료"}
REPEAT_DAYS_DEFAULT = 60


def _s(v):
    return str(v or "").strip()


def ng_missing(d):
    g = d.get("ng") or {}
    return [k for k, _ in NG_REQUIRED if not _s(g.get(k))]


def is_valid(d):
    r = d.get("result")
    if not r:
        return False
    if r == "ok":
        return True
    if r == "na":
        return bool(_s(d.get("na_reason")))
    return not ng_missing(d)


def item_state(d):
    r = d.get("result")
    if not r:
        return {"cls": "none", "label": "미점검"}
    if not is_valid(d):
        return {"cls": "warn", "label": "입력 미완료"}
    return {"cls": "none" if r == "na" else r, "label": {"ok": "적합", "ng": "부적합", "na": "해당 없음"}[r]}


def pct(a, b):
    return round(a / b * 1000) / 10 if b > 0 else None


def fmt_pct(v):
    if v is None:
        return "산정 대상 없음"
    return f"{v:g}%"


def counts(items):
    c = {"total": 0, "valid": 0, "ok": 0, "ng": 0, "na": 0, "none": 0, "incomplete": 0}
    for d in items:
        c["total"] += 1
        r = d.get("result")
        if not r:
            c["none"] += 1
        else:
            c[r] += 1
        if is_valid(d):
            c["valid"] += 1
        elif r:
            c["incomplete"] += 1
    c["progress"] = pct(c["valid"], c["total"])
    c["rate"] = pct(c["ok"], c["ok"] + c["ng"])
    return c


def is_overdue(ng, today):
    """조치 예정일이 지났고 조치 완료가 아닌 부적합 (서울 기준 오늘 날짜)."""
    if not ng or ng.get("status") == "done" or not ng.get("due"):
        return False
    return ng["due"] < today


def undone_count(items):
    return sum(1 for d in items if d.get("result") == "ng" and (d.get("ng") or {}).get("status") != "done")


def generate_opinion(info, items, repeat_ids, today, repeat_days=REPEAT_DAYS_DEFAULT):
    """종합의견 초안 (규칙 기반). repeat_ids: 반복 지적 항목 id 집합."""
    c = counts(items)
    highs, overdue, undone, repeats = [], [], [], []
    for d in items:
        g = d.get("ng") or {}
        if d.get("result") != "ng":
            continue
        if g.get("risk") == "h":
            highs.append(d["name"])
        if is_overdue(g, today):
            overdue.append(d["name"])
        if g.get("status") != "done":
            undone.append(g.get("status") or "todo")
        if d.get("id") in repeat_ids:
            repeats.append(d["name"])

    def short(t):
        return t[:28] + "…" if len(t) > 28 else t

    place = f"「{info.get('place')}」" if info.get("place") else "점검 장소"
    lines = [f"{place}에 대한 {info.get('insp_type') or ''} 결과, 전체 {c['total']}개 항목 중 적합 {c['ok']}건, "
             f"부적합 {c['ng']}건, 해당 없음 {c['na']}건으로 적합률은 {fmt_pct(c['rate'])}입니다."]
    if highs:
        lines.append(f"■ 위험도 '상' 부적합 {len(highs)}건({', '.join(map(short, highs))})이 확인되었습니다. "
                     "작업중지 필요 여부를 담당자가 즉시 검토하고, 위험요인이 해소될 때까지 해당 작업에 대한 통제 조치를 시행하시기 바랍니다.")
    if overdue:
        lines.append(f"■ 조치 예정일이 경과한 미완료 개선조치 {len(overdue)}건이 있습니다. 조치 일정과 담당자를 재확인하시기 바랍니다.")
    if undone:
        a = sum(1 for s in undone if s == "todo")
        lines.append(f"■ 미완료 개선조치 {len(undone)}건(미조치 {a}건, 조치 중 {len(undone) - a}건)에 대해 조치 예정일 내 개선을 완료하고, "
                     "개선 전·후 사진으로 결과를 확인하시기 바랍니다.")
    if repeats:
        lines.append(f"■ 최근 {repeat_days}일 이내 동일 장소에서 반복 지적된 항목 {len(repeats)}건({', '.join(map(short, repeats))})이 있습니다. "
                     "근본원인 분석과 재발방지 대책 수립이 필요합니다.")
    if not highs and not undone:
        if c["rate"] is None:
            lines.append("■ 적합·부적합 판정 대상 항목이 없어 적합률을 산정하지 않았습니다.")
        elif c["rate"] >= 95:
            lines.append("■ 전반적으로 안전관리 상태가 양호한 것으로 판단되며, 현 수준의 점검 체계를 유지하시기 바랍니다.")
        elif c["rate"] >= 85:
            lines.append("■ 대체로 양호하나 일부 항목에 대한 지속적인 관리가 필요합니다.")
        else:
            lines.append("■ 안전관리 상태가 미흡한 것으로 판단되며, 전반적인 개선과 재점검이 필요합니다.")
    else:
        lines.append("■ 적합률과 관계없이 위 사항이 해소되기 전까지 '양호' 판정을 보류하며, 개선조치 완료 후 재확인이 필요합니다.")
    lines.append("※ 본 의견은 시스템이 자동 생성한 초안입니다. 위험도·작업중지 필요 여부 등 최종 안전 판단은 점검 담당자가 검토·확정하여야 합니다.")
    return "\n".join(lines)
