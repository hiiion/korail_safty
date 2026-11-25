"""부적합 결과 변경·부적합 항목 삭제 시 사유 필수 (지시서의 '위험 변경·삭제' 규칙을 새 도메인에 적용)."""
from app.models import AuditLog, InspectionItem, ResultChangeLog
from conftest import all_items, new_insp, set_result


def test_change_from_ng_requires_reason(app, make_client):
    c = make_client("insp")
    d = new_insp(c)
    it = all_items(d)[0]
    v = set_result(c, d, it["id"], "ng")
    r = c.patch(f"/api/items/{it['id']}", json={"version": v, "result": "ok"})
    assert r.status_code == 400 and r.json["error"]["code"] == "REASON_REQUIRED"
    r = c.patch(f"/api/items/{it['id']}", json={"version": v, "result": "ok", "reason": "재확인 결과 이상 없음"})
    assert r.status_code == 200
    assert r.json["data"]["item"]["change_logs"][0]["reason"] == "재확인 결과 이상 없음"
    with app.app_context():
        log = ResultChangeLog.query.one()
        assert (log.kind, log.from_result, log.to_result) == ("change", "ng", "ok")
        assert AuditLog.query.filter_by(action="item.ng_change").count() == 1


def test_delete_ng_item_requires_reason_soft_delete(app, make_client):
    c = make_client("insp")
    d = new_insp(c)
    it = all_items(d)[0]
    set_result(c, d, it["id"], "ng")
    assert c.delete(f"/api/items/{it['id']}", json={}).status_code == 400
    r = c.delete(f"/api/items/{it['id']}", json={"reason": "중복 항목"})
    assert r.status_code == 200
    with app.app_context():
        from app.extensions import db

        row = db.session.get(InspectionItem, it["id"])
        assert row.is_deleted == 1 and row.deleted_reason == "중복 항목"
        assert ResultChangeLog.query.filter_by(kind="delete").count() == 1
    data = c.get(f"/api/inspections/{d['id']}").json["data"]
    assert it["id"] not in [i["id"] for i in all_items(data)]
    assert data["deleted_log"][0]["reason"] == "중복 항목"


def test_delete_normal_item_no_reason(make_client):
    c = make_client("insp")
    d = new_insp(c)
    it = all_items(d)[0]
    assert c.delete(f"/api/items/{it['id']}", json={}).status_code == 200
