"""화면 라우트 (Jinja)."""
from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..domain import client_constants
from ..models import Inspection
from ..services import report as report_svc
from ..services.permissions import can_view, perms_for
from .api import create_inspection_from

bp = Blueprint("views", __name__)


def load(pid):
    insp = Inspection.query.filter_by(public_id=pid).first()
    if not insp or insp.deleted_at:
        abort(404)
    if not can_view(current_user, insp):
        abort(403)
    return insp


@bp.get("/")
@login_required
def home():
    return render_template("dashboard.html", page="dashboard")


@bp.get("/history")
@login_required
def history():
    return render_template("history.html", page="history", consts=client_constants())


@bp.get("/ng")
@login_required
def ng():
    return render_template("ng.html", page="ng")


@bp.get("/settings")
@login_required
def settings():
    return render_template("settings.html", page="settings")


@bp.post("/inspections/new")
@login_required
def new_inspection():
    data = {"template_id": request.form.get("template_id") or None, "copy_from": request.form.get("copy_from") or None}
    insp = create_inspection_from(data)
    return redirect(url_for("views.info", pid=insp.public_id))


@bp.get("/inspections/<pid>")
@login_required
def open_inspection(pid):
    """상태에 맞는 화면으로 이동 (작성 중 → 이어서 작성, 그 외 → 보고서)."""
    insp = load(pid)
    perms = perms_for(current_user, insp)
    if perms["edit"]:
        if not insp.is_composed or insp.needs_recompose:
            return redirect(url_for("views.info", pid=pid))
        return redirect(url_for("views.check", pid=pid))
    return redirect(url_for("views.report", pid=pid))


def _inspect_page(pid, step):
    insp = load(pid)
    perms = perms_for(current_user, insp)
    if not perms["edit"] and step in (1, 2):
        return redirect(url_for("views.check" if insp.is_composed else "views.report", pid=pid))
    return render_template("inspections/inspect.html", insp=insp, perms=perms, step=step, page="inspect",
                           consts=client_constants())


@bp.get("/inspections/<pid>/info")
@login_required
def info(pid):
    return _inspect_page(pid, 1)


@bp.get("/inspections/<pid>/compose")
@login_required
def compose(pid):
    return _inspect_page(pid, 2)


@bp.get("/inspections/<pid>/check")
@login_required
def check(pid):
    insp = load(pid)
    if perms_for(current_user, insp)["edit"] and (not insp.is_composed or insp.needs_recompose):
        return redirect(url_for("views.compose", pid=pid))
    return _inspect_page(pid, 3)


def _mode(insp, requested):
    if requested in ("original", "latest") and insp.status in ("submitted", "confirmed"):
        return "original" if requested == "original" and insp.original_snapshot else "latest"
    if insp.status == "confirmed":
        return "original"
    return "latest" if insp.status == "submitted" else "draft"


@bp.get("/inspections/<pid>/report")
@login_required
def report(pid):
    insp = load(pid)
    perms = perms_for(current_user, insp)
    mode = _mode(insp, request.args.get("mode"))
    ctx = report_svc.build_report(insp, mode, current_user)
    return render_template("inspections/report.html", page="inspect" if perms["edit"] else "history",
                           perms=perms, r=ctx, step=4)


@bp.get("/inspections/<pid>/report/fragment")
@login_required
def report_fragment(pid):
    insp = load(pid)
    mode = _mode(insp, request.args.get("mode"))
    ctx = report_svc.build_report(insp, mode, current_user)
    return render_template("inspections/_report.html", r=ctx)


@bp.get("/inspections/<pid>/report/print")
@login_required
def report_print(pid):
    insp = load(pid)
    mode = _mode(insp, request.args.get("mode"))
    ctx = report_svc.build_report(insp, mode, current_user)
    return render_template("inspections/print.html", r=ctx)
