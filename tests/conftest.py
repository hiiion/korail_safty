import base64
import io
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402
from app.seed import seed_default_template  # noqa: E402

PW = "Passw0rd1"


@pytest.fixture()
def app(tmp_path):
    # TEST_DATABASE_URL=postgresql://... 를 주면 Postgres(Supabase와 같은 엔진)로 같은 테스트를 돌린다.
    pg = os.environ.get("TEST_DATABASE_URL")
    if pg:
        from app.config import database_url, engine_options

        os.environ["DATABASE_URL"] = pg
        uri = database_url()
        extra = {"SQLALCHEMY_ENGINE_OPTIONS": engine_options(uri)}
    else:
        uri = "sqlite:///" + str(tmp_path / "test.db").replace("\\", "/")
        extra = {}
    app = create_app({
        **extra,
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": uri,
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "WTF_CSRF_ENABLED": False,
    })
    with app.app_context():
        if pg:
            db.drop_all()
        db.create_all()
        seed_default_template()
        for uname, name, role, org in (
            ("insp", "점검자A", "inspector", "시설팀"),
            ("insp2", "점검자B", "inspector", "시설팀"),
            ("other", "타소속", "inspector", "다른팀"),
            ("conf", "확인자", "confirmer", "시설팀"),
            ("admin", "관리자", "admin", "시설팀"),
        ):
            u = User(username=uname, name=name, role=role, org=org, must_change_password=0)
            u.set_password(PW)
            db.session.add(u)
        db.session.commit()
    # 요청마다 앱 컨텍스트가 새로 열리고 닫히도록 컨텍스트 밖에서 yield (운영과 동일한 세션 수명)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def login(client, username, pw=PW):
    return client.post("/login", data={"username": username, "password": pw})


@pytest.fixture()
def make_client(app):
    def _make(username=None):
        c = app.test_client()
        if username:
            r = login(c, username)
            assert r.status_code == 302, r.data
        return c
    return _make


def sig_png():
    img = Image.new("RGBA", (200, 80), (255, 255, 255, 0))
    img.putpixel((10, 10), (0, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def jpeg_bytes(exif_gps=False, size=(400, 300)):
    img = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    if exif_gps:
        exif = Image.Exif()
        exif[0x010F] = "TestCam"  # Make
        exif[0x8825] = {1: "N", 2: (37.0, 33.0, 0.0)}  # GPSInfo
        img.save(buf, "JPEG", exif=exif.tobytes())
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


INFO = {"place": "테스트 검수고", "insp_type": "일상점검", "target": "정비 작업장", "zone": "검수고", "work_type": "청소 및 환경정비"}
NG = {"content": "부적합 내용", "cause": "원인", "risk": "m", "action": "개선조치", "owner": "담당자", "due": "2099-12-31"}


def new_insp(client, compose=True, **info):
    r = client.post("/api/inspections", json={})
    assert r.status_code == 201, r.json
    d = r.json["data"]
    r = client.patch(f"/api/inspections/{d['id']}", json=dict(INFO, version=d["version"], **info))
    assert r.status_code == 200, r.json
    d = client.get(f"/api/inspections/{d['id']}").json["data"]
    if compose:
        r = client.post(f"/api/inspections/{d['id']}/compose", json={"version": d["version"], "category_ids": d["recommended"]})
        assert r.status_code == 200, r.json
        d = r.json["data"]
    return d


def all_items(d):
    return [it for c in d["categories"] for it in c["items"]]


def set_result(client, d_or_version, item_id, result, **extra):
    v = d_or_version["version"] if isinstance(d_or_version, dict) else d_or_version
    body = {"version": v, "result": result}
    if result == "na":
        body["na_reason"] = "사유"
    body.update(extra)
    r = client.patch(f"/api/items/{item_id}", json=body)
    assert r.status_code == 200, r.json
    if result == "ng":
        r = client.patch(f"/api/items/{item_id}/action", json=dict(NG, version=r.json["data"]["version"]))
        assert r.status_code == 200, r.json
    return r.json["data"]["version"]


def fill_all(client, d, result="ok"):
    """모든 항목을 결과로 채우고 최신 데이터를 반환."""
    v = d["version"]
    for it in all_items(d):
        v = set_result(client, v, it["id"], result)
    return client.get(f"/api/inspections/{d['id']}").json["data"]


def submit_ready(client, d):
    pid = d["id"]
    assert client.post(f"/api/inspections/{pid}/signatures", json={"role": "inspector", "image": sig_png()}).status_code == 200
    r = client.post(f"/api/inspections/{pid}/submit")
    assert r.status_code == 200, r.json
    return r


def confirm_ready(client, pid):
    assert client.post(f"/api/inspections/{pid}/signatures", json={"role": "confirmer", "image": sig_png()}).status_code == 200
    return client.post(f"/api/inspections/{pid}/confirm")
