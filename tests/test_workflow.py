import json
import re

from app.extensions import db
from app.models import ActionChangeLog, Inspection
from conftest import all_items, confirm_ready, fill_all, new_insp, set_result, submit_ready


def _ng_inspection(c):
    d = fill_all(c, new_insp(c))
    it = all_items(d)[0]
    set_result(c, c.get(f"/api/inspections/{d['id']}").json["data"], it["id"], "ng")
    return c.get(f"/api/inspections/{d['id']}").json["data"], it


def test_submit_confirm_issues_report_no_and_preserves_original(app, make_client):
    c = make_client("insp")
    d, it = _ng_inspection(c)
    r = submit_ready(c, d)
    assert r.json["data"]["status"] == "submitted"
    r = confirm_ready(make_client("conf"), d["id"])
    assert r.status_code == 200, r.json
    assert re.fullmatch(r"RSI-\d{8}-\d{3}", r.json["data"]["report_no"])
    with app.app_context():
        insp = Inspection.query.filter_by(public_id=d["id"]).first()
        assert insp.submitted_at and insp.confirmed_at and insp.opinion
        snap = json.loads(insp.original_snapshot)
        items = [i for cat in snap["categories"] for i in cat["items"]]
        assert any(i["result"] == "ng" and i["ng"]["status"] == "todo" for i in items)
        assert all(i.original_result == i.result for i in insp.items)


def test_locked_after_submit_but_action_allowed(app, make_client):
    c = make_client("insp")
    d, it = _ng_inspection(c)
    submit_ready(c, d)
    v = c.get(f"/api/inspections/{d['id']}").json["data"]["version"]
    r = c.patch(f"/api/items/{all_items(d)[1]['id']}", json={"version": v, "result": "na", "na_reason": "x"})
    assert r.status_code == 409
    r = c.patch(f"/api/items/{it['id']}/action", json={"content": "변경"})
    assert r.status_code == 409  # 부적합 내용은 점검 결과의 일부
    confirm_ready(make_client("conf"), d["id"])
    # 확정 후 개선조치는 같은 소속 사용자도 수정 가능, 이력 기록
    r = make_client("insp2").patch(f"/api/items/{it['id']}/action", json={"status": "done"})
    assert r.status_code == 200 and r.json["data"]["auto_done_date"]
    assert make_client("insp2").patch(f"/api/items/{it['id']}/action", json={"owner": ""}).status_code == 400
    with app.app_context():
        logs = ActionChangeLog.query.filter_by(item_id=it["id"]).all()
        assert any(l.field == "조치 상태" and l.to_value == "조치 완료" for l in logs)
        insp = Inspection.query.filter_by(public_id=d["id"]).first()
        snap = json.loads(insp.original_snapshot)  # 최초 보고서는 그대로
        assert [i for cat in snap["categories"] for i in cat["items"] if i["id"] == it["id"]][0]["ng"]["status"] == "todo"
    page = c.get(f"/inspections/{d['id']}/report?mode=latest").get_data(as_text=True)
    assert "개선조치 변경 이력" in page and "조치 완료" in page


def test_reject_then_resubmit(make_client):
    c = make_client("insp")
    d = fill_all(c, new_insp(c))
    submit_ready(c, d)
    conf = make_client("conf")
    assert conf.post(f"/api/inspections/{d['id']}/reject", json={"reason": ""}).status_code == 400
    r = conf.post(f"/api/inspections/{d['id']}/reject", json={"reason": "보완 필요"})
    assert r.status_code == 200 and r.json["data"]["status"] == "rejected"
    d2 = c.get(f"/api/inspections/{d['id']}").json["data"]
    assert d2["rejected_reason"] == "보완 필요" and d2["perms"]["edit"]
    set_result(c, d2, all_items(d2)[0]["id"], "na")
    r = c.post(f"/api/inspections/{d['id']}/submit")
    assert r.status_code == 200
    page = c.get(f"/inspections/{d['id']}/report").get_data(as_text=True)
    assert "반려" in page and "보완 필요" in page


def test_template_change_does_not_affect_existing(app, make_client):
    c = make_client("insp")
    d = new_insp(c)
    before = [i["name"] for i in all_items(d)]
    a = make_client("admin")
    with app.app_context():
        from app.models import TemplateItem

        ti = TemplateItem.query.filter_by(name=before[0]).first()
        tid, cat_id, tpl_id = ti.id, ti.category_id, ti.category.template_id
    a.post("/admin/templates", data={"act": "rename_item", "template_id": tpl_id, "item_id": tid, "name": "바뀐 항목"})
    a.post("/admin/templates", data={"act": "toggle_item", "template_id": tpl_id, "item_id": all_items(d)[1]["template_item_id"]})
    after = [i["name"] for i in all_items(c.get(f"/api/inspections/{d['id']}").json["data"])]
    assert after == before
    d_new = new_insp(c)
    assert all_items(d_new)[0]["name"] == "바뀐 항목"
