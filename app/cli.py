"""CLI 명령: init-db, create-admin, seed-demo, backup."""
import io
import os
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import click
from flask import current_app

from .extensions import db
from .models import ActionChangeLog, Photo, Signature, User
from .seed import seed_default_template
from .timeutil import KST, today_kst_date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(PROJECT_ROOT, "migrations")


def _db_file():
    return db.engine.url.database


def register(app):
    @app.cli.command("init-db")
    def init_db():
        """instance/·DB·uploads 생성 + 마이그레이션 적용 + 기본 템플릿 시드."""
        from .services.images import upload_root

        os.makedirs(current_app.instance_path, exist_ok=True)
        os.makedirs(upload_root(), exist_ok=True)
        if os.path.isdir(os.path.join(MIGRATIONS_DIR, "versions")) and os.listdir(os.path.join(MIGRATIONS_DIR, "versions")):
            from flask_migrate import upgrade

            upgrade(directory=MIGRATIONS_DIR)
            click.echo("마이그레이션을 적용했습니다.")
        else:
            db.create_all()
            click.echo("테이블을 생성했습니다. (migrations 폴더 없음)")
        if seed_default_template():
            click.echo("기본 체크리스트 템플릿(7개 분야 38개 항목)과 기본 설정을 등록했습니다.")
        click.echo(f"DB 준비 완료: {_db_file()}")

    @app.cli.command("create-admin")
    @click.option("--username", prompt="관리자 아이디")
    @click.option("--name", prompt="이름")
    @click.option("--org", prompt="소속 부서", default="", show_default=False)
    @click.option("--password", prompt="비밀번호 (8자 이상, 영문+숫자)", hide_input=True, confirmation_prompt="비밀번호 확인")
    def create_admin(username, name, org, password):
        """관리자 계정을 대화식으로 생성합니다."""
        from .auth import PW_RULE_MSG, password_ok

        username = username.strip()
        if not username or not name.strip():
            raise click.ClickException("아이디와 이름은 필수입니다.")
        if not password_ok(password):
            raise click.ClickException(PW_RULE_MSG)
        if User.query.filter_by(username=username).first():
            raise click.ClickException("이미 존재하는 아이디입니다.")
        u = User(username=username, name=name.strip(), org=org.strip(), role="admin", must_change_password=0)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"관리자 '{username}' 계정을 만들었습니다.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """(개발 모드 전용) 시연용 사용자와 샘플 점검(아티팩트 시연 데이터 기준) 생성."""
        if not (current_app.debug or os.environ.get("FLASK_DEBUG") == "1"):
            raise click.ClickException("seed-demo는 개발 모드(FLASK_DEBUG=1)에서만 실행할 수 있습니다.")
        seed_default_template()
        _seed_demo()

    @app.cli.command("backup")
    def backup():
        """DB 온라인 백업 + uploads 폴더를 backups/YYYYMMDD_HHMMSS.zip으로 저장."""
        path = make_backup()
        click.echo(f"백업 완료: {path}")


def make_backup(out_dir=None):
    from .services.images import upload_root

    if not current_app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        raise click.ClickException("flask backup은 SQLite 전용입니다.")
    out_dir = out_dir or os.path.join(PROJECT_ROOT, "backups")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zpath = os.path.join(out_dir, f"{stamp}.zip")
    n = 1
    while os.path.exists(zpath):
        zpath = os.path.join(out_dir, f"{stamp}_{n}.zip")
        n += 1
    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = os.path.join(tmp, "app.db")
        src = sqlite3.connect(_db_file())
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)  # SQLite 온라인 백업 API
        finally:
            dst.close()
            src.close()
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_db, "app.db")
            root = upload_root()
            if os.path.isdir(root):
                for dp, _dn, files in os.walk(root):
                    for f in files:
                        full = os.path.join(dp, f)
                        z.write(full, os.path.join("uploads", os.path.relpath(full, root)))
            z.writestr("RESTORE.txt", "복원 방법: 앱을 중지한 뒤 app.db를 instance/app.db로, "
                                      "uploads/ 폴더를 instance/uploads/로 복사하세요.\n")
    return zpath


# ---------------------------------------------------------------------------
# 시연 데이터 (참고 아티팩트 seedDemo와 같은 시나리오)
# ---------------------------------------------------------------------------
def _demo_signature_png():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (300, 120), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.line([(20, 80), (70, 30), (110, 90), (160, 40), (220, 85), (270, 50)], fill=(17, 17, 17, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _add_signature(insp, role, user, at):
    from .services.images import save_raw

    rel = f"signatures/{uuid.uuid4().hex}.png"
    save_raw(rel, _demo_signature_png(), "image/png")
    insp.signatures.append(Signature(role=role, signer_id=user.id, signer_name=user.name, image_path=rel, signed_at=at))
    db.session.flush()


def _add_photo(item, kind, scene, scene_kind, when, user):
    from .demo_images import render
    from .services import images

    meta = images.process_photo(render(scene, scene_kind, when.strftime("%Y/%m/%d %H:%M"), uuid.uuid4().hex))
    p = Photo(kind=kind, original_name=f"demo_{scene}_{scene_kind}.jpg", uploaded_by=user.id, created_at=_iso(when), **meta)
    item.photos.append(p)
    db.session.flush()
    return p


CAT_CODES = {"personal": "개인 안전관리", "env": "작업환경", "vehicle": "철도차량 정비", "tools": "공구 및 설비",
             "heavy": "중량물 취급 및 인양장비", "electric": "전기 안전", "fire": "소방 안전"}
NG = {
    "A": ("oil", "env", 2, "검수고 2번선 하부 바닥에 유압유 누유로 인한 기름 얼룩 및 미끄럼 위험",
          "유압잭 호스 연결부 미세 누설 및 작업 후 즉시 청소 미흡", "누유 부위 흡착포 처리 및 유압 호스 교체, 작업 종료 시 바닥 청소 확인 강화", "김민수"),
    "B": ("pit", "env", 3, "피트 3번 진입부 안전난간 1개소 탈락 및 덮개 미설치", "부품 반출 작업 후 안전난간 미복구",
          "안전난간 재설치 및 고정 볼트 보강, 작업 후 복구 확인 절차 수립", "박준호"),
    "C": ("loto", "electric", 1, "분전반 차단기 잠금장치 미체결 상태에서 전기 작업 진행", "개인 잠금장치 수량 부족 및 작업 절차 미준수",
          "개인별 잠금장치 추가 지급 및 LOTO 절차 재교육 실시", "이서연"),
    "D": ("rope", "heavy", 1, "천장크레인 와이어로프 일부 소선 단선 확인", "교체 주기 도래 후 교체 지연",
          "와이어로프 교체 및 사용 전 점검표 항목 보완", "정다운"),
    "E": ("ext", "fire", 0, "자재 보관소 분말소화기 2대 압력계 지침 저압(적색) 표시", "월간 소화기 점검 누락",
          "소화기 교체 및 월간 점검 일정 등록", "한상철"),
    "F": ("helmet", "personal", 0, "하부 검수 작업자 1명 안전모 턱끈 미체결", "TBM 시 보호구 상호 확인 미흡",
          "현장 즉시 시정 및 TBM 보호구 상호 확인 절차 추가", "김민수"),
}
PLAN = [
    dict(d=58, h=10, who="choi", place="대전철도차량정비단 부품 작업장", target="정비 작업장", zone="부품 작업장", work="부품 점검 및 교체",
         type="정기점검", na=[("env", 3, "해당 작업장에 피트 설비 없음")], photo=("env", 0, "aisle")),
    dict(d=50, h=9, who="park", place="부산철도차량정비단 피트 3번", target="철도차량", zone="피트(Pit)", work="차량 검수", type="일상점검",
         veh=("수도권 광역전철 전동차", "341-08"), ng=[("B", "h", 3, "done")]),
    dict(d=44, h=14, who="lee", place="서울본부 전기 작업장 B동", target="정비 작업장", zone="전기 작업장", work="전기·전자 작업",
         type="정기점검", na=[("env", 3, "해당 작업장에 피트 설비 없음"), ("electric", 0, "전차선 미설치 구역")]),
    dict(d=40, h=9, who="kim", place="수도권철도차량정비단 검수고", target="철도차량", zone="검수고", work="차량 검수", type="일상점검",
         veh=("KTX-산천", "140013"), ng=[("A", "m", 7, "done")], photo=("vehicle", 0, "chock")),
    dict(d=33, h=13, who="jung", place="대전철도차량정비단 정비고", target="정비설비", zone="정비고", work="기계설비 정비", type="정기점검",
         equip=("차륜 전삭기", "EQ-WL-002")),
    dict(d=25, h=10, who="lee", place="서울본부 전기 작업장 B동", target="정비 작업장", zone="전기 작업장", work="전기·전자 작업",
         type="특별점검", ng=[("C", "h", 2, "done")], na=[("env", 3, "해당 작업장에 피트 설비 없음")]),
    dict(d=18, h=15, who="jung", place="대전철도차량정비단 정비고", target="정비설비", zone="정비고", work="중량물 취급", type="정기점검",
         equip=("10톤 천장크레인", "EQ-CR-010"), ng=[("D", "m", 25, "in_progress")]),
    dict(d=12, h=9, who="kim", place="수도권철도차량정비단 검수고", target="철도차량", zone="검수고", work="차량 검수", type="일상점검",
         veh=("무궁화호", "10313"), ng=[("A", "m", 7, "in_progress")]),
    dict(d=9, h=11, who="han", place="대전충청본부 자재 보관소 2동", target="공용시설", zone="자재 보관소", work="시설물 안전점검",
         type="정기점검", ng=[("E", "l", 14, "todo")],
         na=[("env", 3, "피트 설비 없음"), ("fire", 3, "점검 시 화기 작업 없음"), ("fire", 4, "점검 시 용접 작업 없음")]),
    dict(d=6, h=9, who="park", place="부산철도차량정비단 피트 3번", target="철도차량", zone="피트(Pit)", work="차량 검수", type="일상점검",
         veh=("수도권 광역전철 전동차", "341-11"), ng=[("B", "h", 3, "todo")]),
    dict(d=4, h=14, who="choi", place="수도권철도차량정비단 용접 작업장", target="정비 작업장", zone="정비고", work="용접 및 화기 작업",
         type="특별점검", na=[("env", 3, "해당 작업장에 피트 설비 없음")], photo=("fire", 4, "weld")),
    dict(d=3, h=10, who="kim", place="수도권철도차량정비단 검수고", target="철도차량", zone="검수고", work="차량 검수", type="일상점검",
         veh=("KTX", "7008"), ng=[("F", "l", 7, "todo")], submit_only=True),
]
DEMO_ORG = "수도권철도차량정비단"
PEOPLE = {  # key: (username, 이름, 역할, 점검 시 소속 부서)
    "kim": ("inspector1", "김민수", "inspector", "수도권철도차량정비단"),
    "lee": ("inspector2", "이서연", "inspector", "서울본부"),
    "park": ("inspector3", "박준호", "inspector", "부산철도차량정비단"),
    "jung": ("inspector4", "정다운", "inspector", "대전철도차량정비단"),
    "han": ("inspector5", "한상철", "inspector", "대전충청본부"),
    "choi": ("confirmer1", "최지은", "confirmer", "안전본부"),
    "admin": ("admin1", "관리자", "admin", "안전본부"),
}


def _seed_demo():
    from .inspections.core import compose, create_new, default_template, recommended_ids
    from .services import report, workflow

    pw = "Demo1234"
    users = {}
    for key, (uname, name, role, _dept) in PEOPLE.items():
        u = User.query.filter_by(username=uname).first()
        if not u:
            # 시연에서는 모두 같은 소속(계정 기준)으로 두어 서로의 점검을 조회할 수 있게 한다
            u = User(username=uname, name=name, org=DEMO_ORG, role=role, must_change_password=0)
            u.set_password(pw)
            db.session.add(u)
        users[key] = u
    db.session.commit()
    tpl = default_template()
    today = today_kst_date()
    made = 0
    for p in PLAN:
        user = users[p["who"]]
        day = today - timedelta(days=p["d"])
        dt = datetime(day.year, day.month, day.day, p["h"], 30, tzinfo=KST)
        insp = create_new(user, tpl)
        insp.inspector_org = PEOPLE[p["who"]][3]
        insp.inspect_date, insp.inspect_time = day.isoformat(), f"{p['h']:02d}:30"
        insp.place, insp.target, insp.zone, insp.work_type, insp.insp_type = p["place"], p["target"], p["zone"], p["work"], p["type"]
        if p.get("veh"):
            insp.vehicle_type, insp.vehicle_no = p["veh"]
        if p.get("equip"):
            insp.equip_name, insp.equip_no = p["equip"]
        insp.created_at = _iso(dt)
        insp.started_at = _iso(dt)
        db.session.flush()
        compose(insp, recommended_ids(insp))
        db.session.flush()

        def find(code, idx):
            cat = next((c for c in insp.categories if c.name == CAT_CODES[code]), None)
            return cat.live_items[idx] if cat and idx < len(cat.live_items) else None

        for it in insp.live_items:
            it.result = "ok"
        for code, idx, why in p.get("na", []):
            it = find(code, idx)
            if it:
                it.result, it.na_reason = "na", why
        if p.get("photo"):
            code, idx, scene = p["photo"]
            it = find(code, idx)
            if it:
                _add_photo(it, "finding", scene, "normal", dt + timedelta(minutes=15), user)
                it.memo = "이상 없음 확인, 현장 사진 첨부"
        finals = []
        for key, risk, due_add, final in p.get("ng", []):
            scene, code, idx, content, cause, action, owner = NG[key]
            it = find(code, idx)
            if not it:
                continue
            it.result = "ng"
            a = it.action
            a.content, a.cause, a.risk, a.plan, a.owner_name = content, cause, risk, action, owner
            a.due_date, a.status = (day + timedelta(days=due_add)).isoformat(), "todo"
            _add_photo(it, "before", scene, "before", dt + timedelta(minutes=20), user)
            finals.append((it, final, due_add, scene))
        db.session.flush()
        insp.opinion = report.opinion_for(insp, user)
        end = dt + timedelta(minutes=50)
        _add_signature(insp, "inspector", user, _iso(end))
        workflow.submit(insp, user)
        insp.submitted_at = _iso(end)
        if not p.get("submit_only"):
            conf = users["choi"] if p["who"] != "choi" else users["admin"]
            _add_signature(insp, "confirmer", conf, _iso(end + timedelta(hours=2)))
            workflow.confirm(insp, conf, on_date=day.isoformat())
            insp.confirmed_at = _iso(end + timedelta(hours=2))
            for w in insp.workflow_logs:
                w.created_at = insp.submitted_at if w.action == "submit" else insp.confirmed_at
            # 확정 이후 개선조치 진행 이력
            for it, final, due_add, scene in finals:
                a = it.action
                if final in ("in_progress", "done"):
                    at = dt + timedelta(days=1)
                    db.session.add(ActionChangeLog(inspection_id=insp.id, item_id=it.id, field="조치 상태",
                                                   from_value="미조치", to_value="조치 중", user_id=conf.id, created_at=_iso(at)))
                    a.status = "in_progress"
                if final == "done":
                    at = dt + timedelta(days=max(1, due_add - 1))
                    _add_photo(it, "action", scene, "after", at - timedelta(hours=1), user)
                    db.session.add(ActionChangeLog(inspection_id=insp.id, item_id=it.id, field="개선 후 사진",
                                                   from_value="0장", to_value="1장", user_id=user.id,
                                                   created_at=_iso(at - timedelta(minutes=60))))
                    db.session.add(ActionChangeLog(inspection_id=insp.id, item_id=it.id, field="조치 상태",
                                                   from_value="조치 중", to_value="조치 완료", user_id=user.id, created_at=_iso(at)))
                    a.status, a.done_date = "done", (at.date()).isoformat()
        else:
            for w in insp.workflow_logs:
                w.created_at = insp.submitted_at
        insp.updated_at = insp.confirmed_at or insp.submitted_at
        db.session.flush()
        made += 1
    # 작성 중 점검 1건 (이어서 작성 시연용)
    kim = users["kim"]
    draft = create_new(kim, tpl)
    draft.inspector_org = PEOPLE["kim"][3]
    draft.place, draft.insp_type = "수도권철도차량정비단 검수고 3번선", "일상점검"
    draft.target, draft.zone, draft.work_type = "철도차량", "검수고", "차량 검수"
    draft.vehicle_type, draft.vehicle_no = "ITX-청춘", "18104"
    db.session.flush()
    compose(draft, recommended_ids(draft))
    db.session.flush()
    for it in draft.live_items[:5]:
        it.result = "ok"
    db.session.commit()
    click.echo(f"시연용 계정 (비밀번호 {pw}, 개발 모드 전용):")
    for key, (uname, name, role, _d) in PEOPLE.items():
        click.echo(f"  {uname:12s} {name} ({role})")
    click.echo(f"샘플 점검 {made}건(확정 {made - 1}·확인 대기 1)과 작성 중 1건을 만들었습니다.")
