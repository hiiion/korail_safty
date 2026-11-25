from conftest import all_items, fill_all, new_insp, sig_png, submit_ready


def test_other_user_cannot_edit(make_client):
    c = make_client("insp")
    d = new_insp(c)
    it = all_items(d)[0]
    c2 = make_client("insp2")  # 같은 소속: 조회 가능, 수정 불가
    assert c2.get(f"/api/inspections/{d['id']}").status_code == 200
    assert c2.patch(f"/api/items/{it['id']}", json={"version": d["version"], "result": "ok"}).status_code == 403
    assert c2.patch(f"/api/inspections/{d['id']}", json={"version": d["version"], "place": "x"}).status_code == 403
    # 다른 소속: 조회도 불가
    assert make_client("other").get(f"/api/inspections/{d['id']}").status_code == 403


def test_inspector_cannot_confirm(make_client):
    c = make_client("insp")
    d = fill_all(c, new_insp(c))
    submit_ready(c, d)
    c2 = make_client("insp2")
    assert c2.post(f"/api/inspections/{d['id']}/confirm").status_code == 403
    assert c2.post(f"/api/inspections/{d['id']}/reject", json={"reason": "x"}).status_code == 403


def test_cannot_confirm_own(make_client):
    c = make_client("conf")
    d = fill_all(c, new_insp(c))
    submit_ready(c, d)
    assert c.post(f"/api/inspections/{d['id']}/signatures", json={"role": "confirmer", "image": sig_png()}).status_code == 403
    assert c.post(f"/api/inspections/{d['id']}/confirm").status_code == 403


def test_admin_template_only(make_client):
    assert make_client("insp").get("/admin/templates").status_code == 403
    assert make_client("insp").get("/api/export/all.json").status_code == 403
    assert make_client("admin").get("/admin/templates").status_code == 200


def test_visible_lists_scoped_by_org(make_client):
    c = make_client("insp")
    d = fill_all(c, new_insp(c))
    submit_ready(c, d)
    ids = lambda cl: [x["id"] for x in cl.get("/api/inspections").json["data"]["items"]]
    assert d["id"] in ids(make_client("insp2"))
    assert d["id"] not in ids(make_client("other"))
    assert d["id"] in ids(make_client("admin"))
