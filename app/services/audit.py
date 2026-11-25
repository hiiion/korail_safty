"""감사로그 기록."""
import json

from flask import has_request_context, request
from flask_login import current_user

from ..extensions import db
from ..models import AuditLog
from ..timeutil import now_iso

ACTION_LABELS = {
    "login.success": "로그인 성공",
    "login.fail": "로그인 실패",
    "login.locked": "계정 잠금",
    "logout": "로그아웃",
    "password.change": "비밀번호 변경",
    "password.reset": "비밀번호 초기화",
    "user.create": "사용자 생성",
    "user.update": "사용자 수정",
    "user.unlock": "잠금 해제",
    "inspection.create": "점검 생성",
    "inspection.submit": "점검 제출",
    "inspection.confirm": "점검 확인(확정)",
    "inspection.reject": "점검 반려",
    "inspection.delete": "점검 삭제",
    "report_no.issue": "관리번호 발급",
    "item.ng_change": "부적합 결과 변경",
    "item.ng_delete": "부적합 항목 삭제",
    "action.status": "조치 상태 변경",
    "import.json": "JSON 불러오기",
    "export.all": "전체 내보내기",
    "template.update": "템플릿 수정",
    "settings.update": "설정 변경",
}


def client_ip():
    if not has_request_context():
        return None
    return request.remote_addr


def log(action, target_type=None, target_id=None, detail=None, user=None, commit=False):
    uid = None
    if user is not None:
        uid = user.id
    elif has_request_context() and current_user and current_user.is_authenticated:
        uid = current_user.id
    entry = AuditLog(
        user_id=uid,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail is not None else None,
        ip=client_ip(),
        user_agent=(request.headers.get("User-Agent", "")[:300] if has_request_context() else None),
        created_at=now_iso(),
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry
