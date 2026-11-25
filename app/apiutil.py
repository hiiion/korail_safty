"""JSON API 공통 응답 형식."""
from flask import jsonify, request

from .timeutil import now_iso


def ok(data=None, status=200):
    payload = {"ok": True, "data": data if data is not None else {}, "server_time": now_iso()}
    return jsonify(payload), status


def fail(code, message, status=400, **extra):
    err = {"code": code, "message": message}
    err.update({k: v for k, v in extra.items() if v is not None})
    return jsonify({"ok": False, "error": err}), status


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def wants_json():
    return request.path.startswith("/api/") or request.path.startswith("/photos/") or request.is_json
