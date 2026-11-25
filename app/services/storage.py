"""파일 저장소.

- 로컬: instance/uploads/ (기본)
- Supabase Storage: SUPABASE_URL·SUPABASE_SERVICE_KEY가 설정되면 비공개 버킷(SUPABASE_BUCKET)에 저장
  (Vercel처럼 파일시스템이 유지되지 않는 환경용). 서비스 키는 서버에서만 사용한다.

브라우저에는 정적 경로로 노출하지 않고, 항상 권한 확인을 거친 /photos/<id> 경로로만 내려준다.
"""
import os
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app


class StorageError(Exception):
    pass


def _local_root():
    d = current_app.config["UPLOAD_DIR"]
    if not os.path.isabs(d):
        d = os.path.join(current_app.instance_path, d)
    return d


def local_path(rel):
    root = os.path.realpath(_local_root())
    p = os.path.realpath(os.path.join(root, rel))
    if not p.startswith(root + os.sep):
        raise StorageError("잘못된 경로")
    return p


def _check_rel(rel):
    if not rel or rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
        raise StorageError("잘못된 경로")


def _supabase():
    cfg = current_app.config
    if cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_SERVICE_KEY"):
        return cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_KEY"], cfg.get("SUPABASE_BUCKET") or "photos"
    return None


def is_remote():
    return _supabase() is not None


def _sb_request(method, rel, data=None, content_type=None):
    base, key, bucket = _supabase()
    url = f"{base}/storage/v1/object/{urllib.parse.quote(bucket)}/{urllib.parse.quote(rel)}"
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    if data is not None:
        headers["Content-Type"] = content_type or "application/octet-stream"
        headers["x-upsert"] = "true"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (400, 404) and method == "GET":
            raise FileNotFoundError(rel)
        raise StorageError(f"Supabase Storage {method} {e.code}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise StorageError(f"Supabase Storage 연결 실패: {e}")


def ensure_bucket():
    """Supabase 비공개 버킷이 없으면 만든다 (init-db에서 호출). 만들었으면 True."""
    import json

    base, key, bucket = _supabase()
    headers = {"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": "application/json"}
    req = urllib.request.Request(f"{base}/storage/v1/bucket/{urllib.parse.quote(bucket)}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            info = json.loads(r.read() or b"{}")
        if info.get("public"):
            raise StorageError(f"버킷 '{bucket}'이 공개(public) 상태입니다. Supabase에서 비공개로 바꾸세요.")
        return False
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404):
            raise StorageError(f"버킷 확인 실패 ({e.code})")
    body = json.dumps({"id": bucket, "name": bucket, "public": False}).encode()
    req = urllib.request.Request(f"{base}/storage/v1/bucket", data=body, method="POST", headers=headers)
    try:
        urllib.request.urlopen(req, timeout=20).close()
    except urllib.error.HTTPError as e:
        raise StorageError(f"버킷 생성 실패 ({e.code})")
    return True


def save(rel, data: bytes, content_type: str = ""):
    _check_rel(rel)
    if is_remote():
        _sb_request("POST", rel, data, content_type)
        return
    p = local_path(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def read(rel) -> bytes:
    _check_rel(rel)
    if is_remote():
        return _sb_request("GET", rel)
    with open(local_path(rel), "rb") as f:
        return f.read()


def delete(rel):
    if not rel:
        return
    try:
        _check_rel(rel)
        if is_remote():
            _sb_request("DELETE", rel)
            return
        os.remove(local_path(rel))
    except (OSError, StorageError):
        pass
