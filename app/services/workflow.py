"""결재 흐름: 작성 중 → 제출 → 확인(확정) / 반려."""
import json

from ..extensions import db
from ..models import WorkflowLog
from ..timeutil import now_iso
from . import audit, images, report, report_no
from .permissions import EDITABLE_STATUSES
from .validation import incomplete_items, missing_info


class WorkflowError(Exception):
    def __init__(self, code, message, status=400, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


def submit(insp, user):
    if insp.status not in EDITABLE_STATUSES:
        raise WorkflowError("STATE", "이미 제출되었거나 확정된 점검입니다.", 409)
    missing = missing_info(insp)
    if missing:
        raise WorkflowError("VALIDATION", f"기본정보 필수 항목 {len(missing)}개가 비어 있습니다: " + ", ".join(missing.values()),
                            400, fields=missing)
    if insp.needs_recompose or not insp.live_items:
        raise WorkflowError("VALIDATION", "체크리스트가 구성되지 않았습니다. 항목 구성을 먼저 확정하세요.", 400)
    inc = incomplete_items(insp)
    if inc:
        raise WorkflowError("INCOMPLETE", f"미완료 항목 {len(inc)}건", 400, items=inc)
    if not insp.signature("inspector"):
        raise WorkflowError("SIGNATURE", "점검자 서명이 필요합니다. 서명란에 서명한 뒤 제출하세요.", 400)
    if not insp.opinion_edited or not (insp.opinion or "").strip():
        insp.opinion = report.opinion_for(insp, user)
    now = now_iso()
    insp.status = "submitted"
    insp.submitted_at = now  # 종료 시간
    if not insp.started_at:
        insp.started_at = now
    insp.bump()
    db.session.add(WorkflowLog(inspection_id=insp.id, action="submit", user_id=user.id, created_at=now))
    audit.log("inspection.submit", "inspection", insp.public_id, {"place": insp.place, "date": insp.inspect_date})


def confirm(insp, user, on_date=None):
    if insp.status != "submitted":
        raise WorkflowError("STATE", "제출된 점검만 확인할 수 있습니다.", 409)
    sig = insp.signature("confirmer")
    if not sig or sig.signer_id != user.id:
        raise WorkflowError("SIGNATURE", "확인자 서명이 필요합니다. 서명란에 서명한 뒤 확인하세요.", 400)
    now = now_iso()
    no = report_no.issue(on_date)
    insp.report_no = no
    insp.status = "confirmed"
    insp.confirmer_id = user.id
    insp.confirmer_name = user.name
    insp.confirmed_at = now
    insp.rejected_reason = None
    # 최초 점검 결과 보존 (항목별 + 보고서 전체 스냅샷)
    for it in insp.items:
        it.original_result = it.result
        it.original_memo = it.memo
        it.original_na_reason = it.na_reason
        it.original_saved_at = now
    insp.original_snapshot = json.dumps(report.make_snapshot(insp), ensure_ascii=False)
    insp.bump()
    db.session.add(WorkflowLog(inspection_id=insp.id, action="confirm", user_id=user.id, created_at=now))
    audit.log("inspection.confirm", "inspection", insp.public_id, {"report_no": no})
    audit.log("report_no.issue", "inspection", insp.public_id, {"report_no": no})
    return no


def reject(insp, user, reason):
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("VALIDATION", "반려 사유를 입력하세요.", 400, fields={"reason": "필수 입력 항목입니다."})
    if insp.status != "submitted":
        raise WorkflowError("STATE", "제출된 점검만 반려할 수 있습니다.", 409)
    now = now_iso()
    insp.status = "rejected"
    insp.rejected_reason = reason
    sig = insp.signature("confirmer")
    if sig:
        images.remove_file(sig.image_path)
        db.session.delete(sig)
    insp.bump()
    db.session.add(WorkflowLog(inspection_id=insp.id, action="reject", reason=reason, user_id=user.id, created_at=now))
    audit.log("inspection.reject", "inspection", insp.public_id, {"reason": reason})
