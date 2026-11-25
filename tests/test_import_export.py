import io
import json

from conftest import all_items, confirm_ready, fill_all, jpeg_bytes, new_insp, set_result, submit_ready


def _confirmed_with_photo(c, conf):
    d = fill_all(c, new_insp(c))
    it = all_items(d)[0]
    set_result(c, c.get(f"/api/inspections/{d['id']}").json["data"], it["id"], "ng")
    c.post(f"/api/items/{it['id']}/photos", data={"kind": "before", "file": (io.BytesIO(jpeg_bytes()), "b.jpg")},
           content_type="multipart/form-data")
    d = c.get(f"/api/inspections/{d['id']}").json["data"]
    submit_ready(c, d)
    confirm_ready(conf, d["id"])
    return d


def _strip(d):
    return [(i["name"], i["result"], i["na_reason"], i["ng"]["content"], i["ng"]["risk"], i["ng"]["status"], len(i["before"]))
            for i in all_items(d)]


def test_export_import_roundtrip(make_client):
    c, conf, admin = make_client("insp"), make_client("conf"), make_client("admin")
    d = _confirmed_with_photo(c, conf)
    payload = c.get(f"/api/inspections/{d['id']}/export.json").get_json()
    assert payload["app"] == "railway-safety-inspection" and payload["photos"]
    original = c.get(f"/api/inspections/{d['id']}").json["data"]
    r = admin.post("/api/import", json={"data": payload})
    assert r.json["data"]["preview"] and len(r.json["data"]["conflicts"]) == 1
    r = admin.post("/api/import", json={"data": payload, "mode": "skip"})
    assert r.json["data"] == {"imported": 0, "skipped": 1, "bad": []}
    r = admin.post("/api/import", json={"data": payload, "mode": "overwrite"})
    assert r.json["data"]["imported"] == 1
    again = admin.get(f"/api/inspections/{d['id']}").json["data"]
    assert _strip(again) == _strip(original)
    assert again["status"] == "confirmed" and again["report_no"] == original["report_no"]
    assert admin.get(f"/inspections/{d['id']}/report?mode=original").status_code == 200


def test_invalid_file_rejected(make_client):
    admin = make_client("admin")
    r = admin.post("/api/import", json={"data": {"app": "other"}})
    assert r.status_code == 400 and r.json["error"]["code"] == "INVALID_FILE"
    r = admin.post("/api/import", json={"data": {"app": "railway-safety-inspection", "version": 2, "inspections": [{"id": 1}]}})
    assert r.status_code == 400


def test_import_artifact_backup(make_client):
    """참고 아티팩트(SRSI)의 전체 백업 파일 불러오기."""
    from base64 import b64encode

    ph = "data:image/jpeg;base64," + b64encode(jpeg_bytes()).decode()
    backup = {"app": "SRSI", "schemaVersion": 1, "data": {
        "inspections": [{
            "id": "insp_test1", "status": "completed", "docNo": "SI-20261101-001", "completedAt": 1793500000000,
            "info": {"inspector": "김민수", "dept": "서울본부", "place": "검수고", "datetime": "2026-11-01T09:30",
                     "inspType": "일상점검", "target": "철도차량", "zone": "검수고", "workType": "차량 검수",
                     "vehicleType": "KTX", "vehicleNo": "7008"},
            "categories": [{"id": "env", "name": "작업환경", "rule": "common", "items": [
                {"id": "it1", "tid": "env_1", "text": "작업 통로 및 비상 대피로가 확보되어 있는가"},
                {"id": "it2", "tid": "env_3", "text": "바닥에 기름·물기·장애물이 없도록 정리정돈되어 있는가"}]}],
            "responses": {"it1": {"result": "ok"}, "it2": {"result": "ng", "ng": {
                "content": "기름", "cause": "누유", "risk": "m", "action": "청소", "owner": "김", "due": "2026-11-08",
                "status": "조치 완료", "beforePhotos": ["ph_1"], "afterPhotos": ["ph_2"]}}},
            "original": {"responses": {"it1": {"result": "ok"}, "it2": {"result": "ng", "ng": {
                "content": "기름", "cause": "누유", "risk": "m", "action": "청소", "owner": "김", "due": "2026-11-08",
                "status": "미조치", "beforePhotos": ["ph_1"], "afterPhotos": []}}}, "opinion": "의견"},
            "opinion": "의견", "actionLog": [{"at": 1793600000000, "itemId": "it2", "itemText": "x", "field": "조치 상태", "from": "미조치", "to": "조치 완료"}],
        }],
        "drafts": [], "photos": [{"id": "ph_1", "data": ph}, {"id": "ph_2", "data": ph}], "meta": {}}}
    admin = make_client("admin")
    r = admin.post("/api/import", json={"data": backup})
    assert r.json["data"]["kind"] == "아티팩트 백업" and r.json["data"]["valid"] == 1
    assert admin.post("/api/import", json={"data": backup, "mode": "skip"}).json["data"]["imported"] == 1
    d = admin.get("/api/inspections/insp_test1").json["data"]
    ng = [i for i in all_items(d) if i["result"] == "ng"][0]
    assert d["report_no"] == "SI-20261101-001" and d["info"]["time"] == "09:30"
    assert ng["ng"]["status"] == "done" and len(ng["before"]) == 1 and len(ng["after"]) == 1
    page = admin.get("/inspections/insp_test1/report?mode=original").get_data(as_text=True)
    assert "미조치" in page   # 최초 보고서는 원본 상태


def test_stats_csv_bom(make_client):
    c, conf = make_client("insp"), make_client("conf")
    _confirmed_with_photo(c, conf)
    for kind in ("summary", "detail"):
        r = c.get(f"/export/stats.csv?kind={kind}")
        text = r.data.decode("utf-8")
        assert r.status_code == 200 and text.startswith("﻿")
        assert ("적합률" in text) if kind == "summary" else ("부적합내용" in text)
