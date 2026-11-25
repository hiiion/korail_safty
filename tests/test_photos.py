import io

from PIL import Image

from app.models import Photo
from app.services.images import abs_path
from conftest import all_items, jpeg_bytes, new_insp, set_result


def _item(c, ng=False):
    d = new_insp(c)
    item = all_items(d)[0]
    if ng:
        set_result(c, d, item["id"], "ng")
    return d, item


def _up(c, item_id, raw, kind="finding", name="a.jpg"):
    return c.post(f"/api/items/{item_id}/photos", data={"kind": kind, "file": (io.BytesIO(raw), name)},
                  content_type="multipart/form-data")


def test_reject_non_image(make_client):
    c = make_client("insp")
    d, item = _item(c)
    r = _up(c, item["id"], b"not an image", name="x.jpg")
    assert r.status_code == 400 and r.json["error"]["code"] == "INVALID_IMAGE"


def test_exif_removed(app, make_client):
    c = make_client("insp")
    d, item = _item(c)
    raw = jpeg_bytes(exif_gps=True)
    assert Image.open(io.BytesIO(raw)).getexif()  # 원본에는 EXIF 존재
    r = _up(c, item["id"], raw, name="gps.jpg")
    assert r.status_code == 200, r.json
    pid = r.json["data"]["photo"]["id"]
    with app.app_context():
        from app.extensions import db

        p = db.session.get(Photo, pid)
        saved = Image.open(abs_path(p.stored_path))
        assert len(saved.getexif()) == 0 and "exif" not in saved.info
        assert p.stored_path.endswith(".jpg") and "gps" not in p.stored_path
    img = c.get(f"/photos/{pid}")
    assert img.status_code == 200 and img.mimetype == "image/jpeg"
    assert c.get(f"/photos/{pid}/thumb").status_code == 200


def test_too_large_413(make_client):
    c = make_client("insp")
    d, item = _item(c)
    r = _up(c, item["id"], b"\xff" * (15 * 1024 * 1024 + 10), name="big.jpg")
    assert r.status_code == 413


def test_before_after_only_for_ng(make_client):
    c = make_client("insp")
    d, item = _item(c)
    assert _up(c, item["id"], jpeg_bytes(), kind="before").status_code == 400
    d, item = _item(c, ng=True)
    assert _up(c, item["id"], jpeg_bytes(), kind="before").status_code == 200
    assert _up(c, item["id"], jpeg_bytes(), kind="action").status_code == 200


def test_photo_view_permission(make_client):
    c = make_client("insp")
    d, item = _item(c)
    pid = _up(c, item["id"], jpeg_bytes()).json["data"]["photo"]["id"]
    assert make_client("other").get(f"/photos/{pid}").status_code == 403
    assert make_client("insp2").get(f"/photos/{pid}").status_code == 200
    assert make_client().get(f"/photos/{pid}").status_code == 401
