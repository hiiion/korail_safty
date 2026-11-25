from conftest import all_items, new_insp


def test_version_mismatch_409(make_client):
    c = make_client("insp")
    d = new_insp(c)
    it = all_items(d)[0]
    r = c.patch(f"/api/items/{it['id']}", json={"version": d["version"], "result": "ok"})
    assert r.status_code == 200
    # 다른 탭이 예전 version으로 저장 시도
    r = c.patch(f"/api/items/{all_items(d)[1]['id']}", json={"version": d["version"], "result": "ok"})
    assert r.status_code == 409 and r.json["error"]["code"] == "CONFLICT"
    r = c.patch(f"/api/inspections/{d['id']}", json={"version": d["version"], "place": "x"})
    assert r.status_code == 409
