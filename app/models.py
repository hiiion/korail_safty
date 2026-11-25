"""SQLAlchemy 모델 — 작업지시서 4장 스키마 + 스마트 철도차량 안전점검 도메인 확장.

참고 아티팩트(reference/railway-safety.html)의 도메인에 맞춘 변경:
  - 점검 결과: ok(적합) / ng(부적합) / na(해당 없음) / NULL(미점검)
  - 부적합 세부정보(내용·원인·위험도)와 개선조치(내용·담당자·예정일·상태)는 item_actions에 저장
  - 사진 종류: finding(항목 사진) / before(개선 전) / action(개선 후)
  - 점검 기본정보: 일시·유형·대상·작업구역·작업 유형·차량/설비 정보
  - 확정 시점 보고서 전체를 original_snapshot(JSON)으로 보존 → "최초 보고서"
"""
import json
import uuid

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .timeutil import now_iso

ROLES = ("inspector", "confirmer", "admin")
ROLE_LABELS = {"inspector": "점검자", "confirmer": "확인자", "admin": "관리자"}
RESULTS = ("ok", "ng", "na")
RESULT_LABELS = {"ok": "적합", "ng": "부적합", "na": "해당 없음", None: "미점검"}
RISKS = ("h", "m", "l")
RISK_LABELS = {"h": "상", "m": "중", "l": "하"}
STATUSES = ("draft", "submitted", "confirmed", "rejected")
STATUS_LABELS = {"draft": "작성 중", "submitted": "제출됨(확인 대기)", "confirmed": "완료(확정)", "rejected": "반려"}
ACTION_STATUSES = ("todo", "in_progress", "done")
ACTION_LABELS = {"todo": "미조치", "in_progress": "조치 중", "done": "조치 완료"}
PHOTO_KINDS = ("finding", "before", "action")
RULES = ("common", "vehicle", "equip", "heavy", "electric", "fire", "custom")
RULE_LABELS = {"common": "공통", "vehicle": "철도차량", "equip": "정비설비", "heavy": "중량물",
               "electric": "전기", "fire": "화기·소방", "custom": "사용자 추가"}


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, nullable=False, unique=True)
    password_hash = db.Column(db.Text, nullable=False)
    name = db.Column(db.Text, nullable=False)
    org = db.Column(db.Text, nullable=False, default="")
    role = db.Column(db.Text, nullable=False)
    is_active_flag = db.Column("is_active", db.Integer, nullable=False, default=1)
    must_change_password = db.Column(db.Integer, nullable=False, default=1)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.Text)
    last_login_at = db.Column(db.Text)
    created_at = db.Column(db.Text, nullable=False, default=now_iso)
    updated_at = db.Column(db.Text, nullable=False, default=now_iso, onupdate=now_iso)

    __table_args__ = (CheckConstraint("role IN ('inspector','confirmer','admin')", name="ck_users_role"),)

    @property
    def is_active(self):  # Flask-Login
        return bool(self.is_active_flag)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class ChecklistTemplate(db.Model):
    __tablename__ = "checklist_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Integer, nullable=False, default=1)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.Text, nullable=False, default=now_iso)
    updated_at = db.Column(db.Text, nullable=False, default=now_iso, onupdate=now_iso)
    categories = db.relationship(
        "TemplateCategory", backref="template", cascade="all, delete-orphan",
        order_by="TemplateCategory.sort_order, TemplateCategory.id", passive_deletes=True,
    )


class TemplateCategory(db.Model):
    __tablename__ = "template_categories"
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("checklist_templates.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.Text, nullable=False)
    rule = db.Column(db.Text, nullable=False, default="custom")  # 자동 추천 규칙
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Integer, nullable=False, default=1)
    items = db.relationship(
        "TemplateItem", backref="category", cascade="all, delete-orphan",
        order_by="TemplateItem.sort_order, TemplateItem.id", passive_deletes=True,
    )

    @property
    def active_items(self):
        return [i for i in self.items if i.is_active]


class TemplateItem(db.Model):
    __tablename__ = "template_items"
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("template_categories.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Integer, nullable=False, default=1)


class Inspection(db.Model):
    __tablename__ = "inspections"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.Text, nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    report_no = db.Column(db.Text, unique=True)
    status = db.Column(db.Text, nullable=False, default="draft")
    inspector_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    inspector_name = db.Column(db.Text, nullable=False)          # 작성 시점 스냅샷 (점검자 성명)
    inspector_org = db.Column(db.Text, nullable=False)           # 소속 부서
    place = db.Column(db.Text, nullable=False, default="")
    inspect_date = db.Column(db.Text, nullable=False)            # YYYY-MM-DD
    inspect_time = db.Column(db.Text, nullable=False, default="")  # HH:MM (현장 기준 시각)
    insp_type = db.Column(db.Text, nullable=False, default="")   # 일상점검/정기점검/특별점검
    target = db.Column(db.Text, nullable=False, default="")
    target_etc = db.Column(db.Text, nullable=False, default="")
    zone = db.Column(db.Text, nullable=False, default="")
    zone_etc = db.Column(db.Text, nullable=False, default="")
    work_type = db.Column(db.Text, nullable=False, default="")
    work_type_etc = db.Column(db.Text, nullable=False, default="")
    vehicle_type = db.Column(db.Text, nullable=False, default="")
    vehicle_no = db.Column(db.Text, nullable=False, default="")
    equip_name = db.Column(db.Text, nullable=False, default="")
    equip_no = db.Column(db.Text, nullable=False, default="")
    selected_cats = db.Column(db.Text)                           # JSON: 선택한 템플릿 분야 id 목록
    needs_recompose = db.Column(db.Integer, nullable=False, default=0)
    opinion = db.Column(db.Text, nullable=False, default="")
    opinion_edited = db.Column(db.Integer, nullable=False, default=0)
    template_id = db.Column(db.Integer, db.ForeignKey("checklist_templates.id"))
    copied_from_id = db.Column(db.Integer, db.ForeignKey("inspections.id", ondelete="SET NULL"))
    started_at = db.Column(db.Text)
    submitted_at = db.Column(db.Text)
    confirmer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    confirmer_name = db.Column(db.Text)
    confirmed_at = db.Column(db.Text)
    rejected_reason = db.Column(db.Text)
    original_snapshot = db.Column(db.Text)                       # JSON: 확정 시점 보고서 데이터
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.Text, nullable=False, default=now_iso)
    updated_at = db.Column(db.Text, nullable=False, default=now_iso)
    deleted_at = db.Column(db.Text)
    deleted_reason = db.Column(db.Text)

    inspector = db.relationship("User", foreign_keys=[inspector_id])
    categories = db.relationship(
        "InspectionCategory", backref="inspection", cascade="all, delete-orphan",
        order_by="InspectionCategory.sort_order, InspectionCategory.id", passive_deletes=True,
    )
    items = db.relationship(
        "InspectionItem", backref="inspection", cascade="all, delete-orphan",
        order_by="InspectionItem.sort_order, InspectionItem.id", passive_deletes=True, overlaps="items",
    )
    signatures = db.relationship("Signature", backref="inspection", cascade="all, delete-orphan", passive_deletes=True)
    change_logs = db.relationship(
        "ResultChangeLog", backref="inspection", cascade="all, delete-orphan",
        order_by="ResultChangeLog.changed_at, ResultChangeLog.id", passive_deletes=True,
    )
    action_logs = db.relationship(
        "ActionChangeLog", backref="inspection", cascade="all, delete-orphan",
        order_by="ActionChangeLog.created_at, ActionChangeLog.id", passive_deletes=True,
    )
    workflow_logs = db.relationship(
        "WorkflowLog", backref="inspection", cascade="all, delete-orphan",
        order_by="WorkflowLog.created_at, WorkflowLog.id", passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft','submitted','confirmed','rejected')", name="ck_insp_status"),
        Index("ix_insp_date", "inspect_date"),
        Index("ix_insp_status", "status"),
        Index("ix_insp_inspector", "inspector_id"),
    )

    @property
    def live_items(self):
        return [i for i in self.items if not i.is_deleted]

    @property
    def selected_cat_ids(self):
        try:
            v = json.loads(self.selected_cats) if self.selected_cats else None
            return [int(x) for x in v] if isinstance(v, list) else None
        except (ValueError, TypeError):
            return None

    @property
    def is_composed(self):
        return bool(self.categories)

    @property
    def snapshot(self):
        try:
            return json.loads(self.original_snapshot) if self.original_snapshot else None
        except ValueError:
            return None

    @staticmethod
    def _label(v, etc):
        return (etc or "기타") if v == "기타" else (v or "")

    @property
    def target_label(self):
        return self._label(self.target, self.target_etc)

    @property
    def zone_label(self):
        return self._label(self.zone, self.zone_etc)

    @property
    def work_type_label(self):
        return self._label(self.work_type, self.work_type_etc)

    @property
    def inspect_dt(self):
        return f"{self.inspect_date} {self.inspect_time}".strip()

    def signature(self, role):
        for s in self.signatures:
            if s.role == role:
                return s
        return None

    def bump(self):
        self.version = (self.version or 0) + 1
        self.updated_at = now_iso()

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)


class InspectionCategory(db.Model):
    __tablename__ = "inspection_categories"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    template_category_id = db.Column(db.Integer)   # 참조용(템플릿이 바뀌어도 점검본은 독립)
    name = db.Column(db.Text, nullable=False)
    rule = db.Column(db.Text, nullable=False, default="custom")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    items = db.relationship(
        "InspectionItem", backref="category",
        order_by="InspectionItem.sort_order, InspectionItem.id", overlaps="inspection,items",
    )

    @property
    def live_items(self):
        return [i for i in self.items if not i.is_deleted]


class InspectionItem(db.Model):
    __tablename__ = "inspection_items"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("inspection_categories.id", ondelete="CASCADE"), nullable=False)
    template_item_id = db.Column(db.Integer)       # 반복 지적 판단용 (같은 템플릿 항목)
    name = db.Column(db.Text, nullable=False)
    is_custom = db.Column(db.Integer, nullable=False, default=0)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    result = db.Column(db.Text)
    memo = db.Column(db.Text, nullable=False, default="")   # 특이사항
    na_reason = db.Column(db.Text, nullable=False, default="")
    original_result = db.Column(db.Text)
    original_memo = db.Column(db.Text)
    original_na_reason = db.Column(db.Text)
    original_saved_at = db.Column(db.Text)
    is_deleted = db.Column(db.Integer, nullable=False, default=0)
    deleted_reason = db.Column(db.Text)
    deleted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    deleted_at = db.Column(db.Text)
    updated_at = db.Column(db.Text, nullable=False, default=now_iso)

    action = db.relationship("ItemAction", backref="item", uselist=False, cascade="all, delete-orphan", passive_deletes=True)
    photos = db.relationship(
        "Photo", backref="item", cascade="all, delete-orphan",
        order_by="Photo.created_at, Photo.id", passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("result IN ('ok','ng','na')", name="ck_item_result"),
        Index("ix_item_insp_result", "inspection_id", "result"),
    )

    @property
    def is_ng(self):
        return self.result == "ng"

    def live_photos(self, kind):
        return [p for p in self.photos if p.kind == kind and not p.is_deleted]


class ItemAction(db.Model):
    """부적합 세부정보 + 개선·사후 조치 (항목 1:1)."""
    __tablename__ = "item_actions"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("inspection_items.id", ondelete="CASCADE"), nullable=False, unique=True)
    content = db.Column(db.Text, nullable=False, default="")   # 부적합 내용
    cause = db.Column(db.Text, nullable=False, default="")     # 발생 원인
    risk = db.Column(db.Text)                                  # h/m/l (담당자 판단)
    plan = db.Column(db.Text, nullable=False, default="")      # 개선조치 내용
    owner_name = db.Column(db.Text, nullable=False, default="")
    due_date = db.Column(db.Text)
    status = db.Column(db.Text, nullable=False, default="todo")
    done_date = db.Column(db.Text)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.Text, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("status IN ('todo','in_progress','done')", name="ck_action_status"),
        CheckConstraint("risk IS NULL OR risk IN ('h','m','l')", name="ck_action_risk"),
        Index("ix_action_status_due", "status", "due_date"),
    )


class Photo(db.Model):
    __tablename__ = "photos"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("inspection_items.id", ondelete="CASCADE"), nullable=False)
    kind = db.Column(db.Text, nullable=False)
    stored_path = db.Column(db.Text, nullable=False, unique=True)
    thumb_path = db.Column(db.Text, nullable=False)
    original_name = db.Column(db.Text)
    mime = db.Column(db.Text, nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    sha256 = db.Column(db.Text, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.Text, nullable=False, default=now_iso)
    is_deleted = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (CheckConstraint("kind IN ('finding','before','action')", name="ck_photo_kind"),)


class Signature(db.Model):
    __tablename__ = "signatures"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.Text, nullable=False)
    signer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    signer_name = db.Column(db.Text, nullable=False)
    image_path = db.Column(db.Text, nullable=False)
    signed_at = db.Column(db.Text, nullable=False, default=now_iso)
    ip = db.Column(db.Text)

    __table_args__ = (
        CheckConstraint("role IN ('inspector','confirmer')", name="ck_sig_role"),
        UniqueConstraint("inspection_id", "role", name="uq_sig_insp_role"),
    )


class ResultChangeLog(db.Model):
    """부적합 결과 변경·부적합 항목 삭제 이력 (사유 필수)."""
    __tablename__ = "result_change_logs"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("inspection_items.id", ondelete="CASCADE"), nullable=False)
    kind = db.Column(db.Text, nullable=False)
    from_result = db.Column(db.Text, nullable=False)
    to_result = db.Column(db.Text)
    reason = db.Column(db.Text, nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    changed_at = db.Column(db.Text, nullable=False, default=now_iso)

    item = db.relationship("InspectionItem")

    __table_args__ = (CheckConstraint("kind IN ('change','delete')", name="ck_rcl_kind"),)


class ActionChangeLog(db.Model):
    """확정(제출) 이후 개선조치 변경 이력 — "최신 개선조치 현황" 보고서에 출력."""
    __tablename__ = "action_change_logs"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("inspection_items.id", ondelete="CASCADE"), nullable=False)
    field = db.Column(db.Text, nullable=False)        # 화면 표기 (조치 상태, 개선 후 사진 등)
    from_value = db.Column(db.Text)
    to_value = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.Text, nullable=False, default=now_iso)

    item = db.relationship("InspectionItem")
    user = db.relationship("User")


class WorkflowLog(db.Model):
    __tablename__ = "workflow_logs"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    action = db.Column(db.Text, nullable=False)
    reason = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.Text, nullable=False, default=now_iso)

    user = db.relationship("User")

    __table_args__ = (CheckConstraint("action IN ('submit','confirm','reject')", name="ck_wf_action"),)


class ReportSequence(db.Model):
    __tablename__ = "report_sequences"
    date_key = db.Column(db.Text, primary_key=True)
    last_seq = db.Column(db.Integer, nullable=False, default=0)


class AppSetting(db.Model):
    """앱 설정 (업무시간 절감 기준 등)."""
    __tablename__ = "app_settings"
    key = db.Column(db.Text, primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.Text, nullable=False)
    target_type = db.Column(db.Text)
    target_id = db.Column(db.Text)
    detail_json = db.Column(db.Text)
    ip = db.Column(db.Text)
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.Text, nullable=False, default=now_iso)

    user = db.relationship("User")

    __table_args__ = (Index("ix_audit_created", "created_at"),)
