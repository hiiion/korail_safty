"""Supabase Storage 백엔드: 가짜 Storage API 서버로 업로드·조회·삭제 경로를 검사한다."""
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import all_items, jpeg_bytes, new_insp

STORE = {}
KEY = "service-key-test"


class FakeStorage(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok_auth(self):
        if self.headers.get("Authorization") != f"Bearer {KEY}" or self.headers.get("apikey") != KEY:
            self.send_response(403)
            self.end_headers()
            return False
        return True

    def do_POST(self):
        if not self._ok_auth():
            return
        n = int(self.headers.get("Content-Length", 0))
        STORE[self.path] = (self.headers.get("Content-Type"), self.rfile.read(n))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def do_GET(self):
        if not self._ok_auth():
            return
        if self.path not in STORE:
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(STORE[self.path][1])

    def do_DELETE(self):
        if not self._ok_auth():
            return
        STORE.pop(self.path, None)
        self.send_response(200)
        self.end_headers()


@pytest.fixture()
def fake_supabase(app):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeStorage)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    STORE.clear()
    app.config.update(SUPABASE_URL=f"http://127.0.0.1:{srv.server_port}", SUPABASE_SERVICE_KEY=KEY, SUPABASE_BUCKET="photos")
    yield
    srv.shutdown()
    app.config.update(SUPABASE_URL="", SUPABASE_SERVICE_KEY="")


def test_photo_roundtrip_via_supabase(make_client, fake_supabase, app):
    c = make_client("insp")
    d = new_insp(c)
    it = all_items(d)[0]
    r = c.post(f"/api/items/{it['id']}/photos", data={"kind": "finding", "file": (io.BytesIO(jpeg_bytes()), "a.jpg")},
               content_type="multipart/form-data")
    assert r.status_code in (200, 201), r.data
    pid = r.json["data"]["photo"]["id"]
    keys = list(STORE)
    assert len(keys) == 2 and all(k.startswith("/storage/v1/object/photos/") for k in keys)
    assert all(v[0] == "image/jpeg" for v in STORE.values())
    # 로컬 업로드 폴더에는 아무것도 쓰지 않는다
    import os
    assert not os.path.exists(app.config["UPLOAD_DIR"]) or not any(os.scandir(app.config["UPLOAD_DIR"]))
    img = c.get(f"/photos/{pid}")
    assert img.status_code == 200 and img.data[:2] == b"\xff\xd8"
    assert c.get(f"/photos/{pid}/thumb").status_code == 200
    d = c.get(f"/api/inspections/{d['id']}").json["data"]
    assert c.delete(f"/api/photos/{pid}", json={"version": d["version"]}).status_code == 200
    assert STORE == {}


def test_init_db_creates_private_bucket(app, fake_supabase, monkeypatch):
    from app.services import storage

    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append((req.get_method(), req.full_url, req.data))
        if req.get_method() == "GET":
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(storage.urllib.request, "urlopen", fake_urlopen)
    with app.app_context():
        assert storage.ensure_bucket() is True
    assert calls[1][0] == "POST" and b'"public": false' in calls[1][2]
