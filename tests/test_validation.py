from conftest import NG, all_items, fill_all, new_insp, set_result, sig_png


def test_compose_recommends_by_rules(make_client):
    c = make_client("insp")
    d = new_insp(c, target="철도차량", zone="전기 작업장", work_type="차량 검수", vehicle_type="KTX", vehicle_no="7008")
    names = [x["name"] for x in d["categories"]]
    assert names == ["개인 안전관리", "작업환경", "철도차량 정비", "전기 안전"]
    # 동일 문구 항목은 중복되지 않는다
    texts = [i["name"] for i in all_items(d)]
    assert len(texts) == len(set(texts))


def test_submit_rejects_incomplete_and_returns_items(make_client):
    c = make_client("insp")
    d = new_insp(c)
    items = all_items(d)
    v = d["version"]
    v = set_result(c, v, items[0]["id"], "ok")
    r = c.patch(f"/api/items/{items[1]['id']}", json={"version": v, "result": "na"})  # 사유 없음
    v = r.json["data"]["version"]
    r = c.patch(f"/api/items/{items[2]['id']}", json={"version": v, "result": "ng"})  # 세부정보 없음
    c.post(f"/api/inspections/{d['id']}/signatures", json={"role": "inspector", "image": sig_png()})
    r = c.post(f"/api/inspections/{d['id']}/submit")
    assert r.status_code == 400 and r.json["error"]["code"] == "INCOMPLETE"
    reasons = {x["item_id"]: x["reason"] for x in r.json["error"]["items"]}
    assert reasons[items[1]["id"]] == "na_reason_required"
    assert reasons[items[2]["id"]] == "ng_detail_required"
    assert reasons[items[3]["id"]] == "result_required"
    assert items[0]["id"] not in reasons
    first = r.json["error"]["items"][0]
    assert first["item_id"] == items[1]["id"] and first["category_id"]


def test_submit_requires_info_and_signature(make_client):
    c = make_client("insp")
    d = new_insp(c, target="철도차량", work_type="차량 검수")  # 차량 종류·번호 누락
    d = fill_all(c, d)
    c.post(f"/api/inspections/{d['id']}/signatures", json={"role": "inspector", "image": sig_png()})
    r = c.post(f"/api/inspections/{d['id']}/submit")
    assert r.status_code == 400 and set(r.json["error"]["fields"]) == {"vehicle_type", "vehicle_no"}

    d2 = fill_all(c, new_insp(c))
    r = c.post(f"/api/inspections/{d2['id']}/submit")
    assert r.status_code == 400 and r.json["error"]["code"] == "SIGNATURE"


def test_ng_detail_all_fields_required(make_client):
    c = make_client("insp")
    d = fill_all(c, new_insp(c))
    it = all_items(d)[0]
    r = c.patch(f"/api/items/{it['id']}", json={"version": d["version"], "result": "ng"})
    v = r.json["data"]["version"]
    partial = dict(NG, owner="")
    c.patch(f"/api/items/{it['id']}/action", json=dict(partial, version=v))
    c.post(f"/api/inspections/{d['id']}/signatures", json={"role": "inspector", "image": sig_png()})
    r = c.post(f"/api/inspections/{d['id']}/submit")
    assert r.status_code == 400
    assert r.json["error"]["items"][0]["missing"] == ["owner"]
