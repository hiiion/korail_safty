"""파일 저장소 (로컬: instance/uploads/).

브라우저에는 정적 경로로 노출하지 않고, 항상 권한 확인을 거친 /photos/<id> 경로로만 내려준다.
"""
import os

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


def save(rel, data: bytes, content_type: str = ""):
    _check_rel(rel)
    p = local_path(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def read(rel) -> bytes:
    _check_rel(rel)
    with open(local_path(rel), "rb") as f:
        return f.read()


def delete(rel):
    if not rel:
        return
    try:
        _check_rel(rel)
        os.remove(local_path(rel))
    except (OSError, StorageError):
        pass
