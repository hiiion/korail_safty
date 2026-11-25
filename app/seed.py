"""기본 체크리스트 템플릿·설정 시드 (7개 분야 38개 항목)."""
from .domain import DEFAULT_TEMPLATE
from .extensions import db
from .models import AppSetting, ChecklistTemplate, TemplateCategory, TemplateItem
from .timeutil import now_iso

DEFAULT_SETTINGS = {"before_min": "90", "after_min": "43"}


def build_default_template(name="기본 체크리스트 (시연용 예시)"):
    now = now_iso()
    t = ChecklistTemplate(name=name, is_default=1, is_active=1, created_at=now, updated_at=now)
    for ci, (cname, rule, items) in enumerate(DEFAULT_TEMPLATE):
        c = TemplateCategory(name=cname, rule=rule, sort_order=ci)
        for ii, iname in enumerate(items):
            c.items.append(TemplateItem(name=iname, sort_order=ii))
        t.categories.append(c)
    return t


def seed_default_template():
    changed = False
    if not ChecklistTemplate.query.first():
        db.session.add(build_default_template())
        changed = True
    for k, v in DEFAULT_SETTINGS.items():
        if not db.session.get(AppSetting, k):
            db.session.add(AppSetting(key=k, value=v))
            changed = True
    if changed:
        db.session.commit()
    return changed


def get_setting(key, default=None):
    s = db.session.get(AppSetting, key)
    return s.value if s else (DEFAULT_SETTINGS.get(key, default))


def set_setting(key, value):
    s = db.session.get(AppSetting, key)
    if s:
        s.value = str(value)
    else:
        db.session.add(AppSetting(key=key, value=str(value)))
