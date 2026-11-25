# 작업지시서: 철도 현장 안전점검 도우미 — Flask 웹앱 전환

> 이 문서는 개발자(또는 코딩 에이전트)에게 그대로 전달하는 작업지시서입니다.
> 기존 단일 HTML 아티팩트(`railway-safety.html`)의 기능을 유지하면서, **Python Flask + SQLite** 기반의 **로컬 실행 웹앱**으로 전환합니다.

---

## 0. 목표와 범위

### 목표
- 브라우저 저장소(IndexedDB/localStorage)에만 있던 데이터를 **서버 DB(SQLite)** 와 **서버 파일 저장소**로 옮긴다.
- 시연용 비밀번호(1234)를 **실제 사용자 계정·권한 체계**로 바꾼다.
- 기존 화면 흐름과 기능(1~14번)은 그대로 유지한다.
- 1단계는 **개발자 PC(localhost)에서 구동**되는 것을 완료 기준으로 한다. 같은 와이파이의 휴대폰으로 접속해 테스트할 수 있어야 한다.

### 범위 밖 (이번 작업에서 하지 않음)
- 인터넷 공개 배포, HTTPS 인증서, 운영 서버 구성 (→ 13장에 다음 단계로만 정리)
- 사내 SSO·외부 시스템 연동, 푸시 알림, 네이티브 앱

### 참고 자료
- 기존 아티팩트 HTML을 `reference/railway-safety.html`에 넣어두고, **화면 구성·CSS·문구·판정 로직은 이 파일을 기준**으로 재사용한다.

---

## 1. 기술 스택

| 구분 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.11 이상 | |
| 웹 프레임워크 | Flask 3.x | 앱 팩토리(`create_app`) + 블루프린트 구조 |
| DB | SQLite 3 | `instance/app.db`, WAL 모드, 외래키 ON |
| ORM / 마이그레이션 | Flask-SQLAlchemy 3.x, Flask-Migrate | 스키마 변경 이력 관리 |
| 인증 | Flask-Login + Werkzeug 비밀번호 해시 | |
| 보안 | Flask-WTF (CSRF) | 폼과 JSON API 모두 CSRF 검사 |
| 이미지 처리 | Pillow | 서버 측 재인코딩·리사이즈·EXIF 제거 |
| 환경설정 | python-dotenv | `.env` |
| 화면 | Jinja2 서버 렌더링 + 순수 JavaScript | **외부 CDN 사용 금지** (폐쇄망 대비) |
| 테스트 | pytest | |

`requirements.txt`

```
Flask>=3.0
Flask-SQLAlchemy>=3.1
Flask-Migrate>=4.0
Flask-Login>=0.6
Flask-WTF>=1.2
Pillow>=10.0
python-dotenv>=1.0
pytest>=8.0
```

---

## 2. 실제 운영을 위해 추가하는 개발 기능

아티팩트는 "한 사람이 한 브라우저에서 쓰는 시연용"이었습니다. 여러 사람이 실제로 쓰려면 아래 기능이 필요합니다.

### 2-1. 사용자 계정과 인증 (시연용 비밀번호 대체)
- 비밀번호 1234 로그인을 **삭제**하고, 아이디·비밀번호 로그인으로 바꾼다.
- 비밀번호는 `werkzeug.security.generate_password_hash`로 해시 저장한다. 평문 저장은 금지한다.
- 비밀번호 규칙은 8자 이상, 영문과 숫자 포함으로 한다.
- 최초 로그인 시 비밀번호 변경을 강제한다(`must_change_password`).
- **로그인 5회 연속 실패 시 10분 잠금**을 건다.
- 세션 만료는 기본 8시간(근무 1교대)으로 하고, 로그아웃하면 세션을 즉시 폐기한다.
- 최초 관리자는 CLI 명령(`flask create-admin`)으로만 만든다. 코드에 기본 계정을 하드코딩하지 않는다.

### 2-2. 역할과 권한

| 기능 | 점검자 (inspector) | 확인자 (confirmer) | 관리자 (admin) |
|---|:---:|:---:|:---:|
| 점검 작성·수정 (본인, 작성 중일 때) | ✅ | ✅ | ✅ |
| 다른 사람의 점검 조회 | 소속 내 조회 | 소속 내 조회 | 전체 |
| 점검 제출 (점검자 서명) | ✅ | ✅ | ✅ |
| 확인·승인 (확인자 서명) / 반려 | ❌ | ✅ (본인 점검 제외) | ✅ |
| 개선·사후 조치 입력 | ✅ | ✅ | ✅ |
| 작성 중 점검 삭제 | 본인 것만 | 본인 것만 | ✅ |
| 확정된 점검 삭제 | ❌ | ❌ | ✅ (소프트 삭제, 사유 필수) |
| 사용자 관리 / 체크리스트 템플릿 관리 / 감사로그 조회 | ❌ | ❌ | ✅ |
| 전체 JSON 내보내기·불러오기 | ❌ | ❌ | ✅ |

- 권한 검사는 **반드시 서버에서** 한다. 화면에서 버튼을 숨기는 것만으로는 부족하다.

### 2-3. 결재 흐름 (확정 절차 강화)
아티팩트의 "보고서 확정"을 실제 결재 흐름으로 바꾼다.

```
작성 중(draft) ──제출──▶ 제출됨(submitted) ──확인──▶ 확정(confirmed)
      ▲                         │
      └────────반려(사유 필수)───┘  → rejected 상태로 표시, 점검자가 수정 후 재제출
```

- **제출**: 미완료 항목 검증을 통과하고 점검자 서명이 있어야 한다. 제출 시각을 **종료 시간**으로 기록하고, 이때부터 점검 결과가 잠긴다.
- **확인**: 확인자 서명이 필요하다. 이때 **관리번호를 발급**하고 최초 점검 결과를 보존한다.
- **반려**: 사유 입력이 필수다. 상태를 `rejected`로 바꾸고 결과 잠금을 해제한다. 반려 이력은 보고서와 감사로그에 남긴다.
- 확정 이후에는 **개선·사후 조치 정보만** 수정할 수 있다(아티팩트와 동일).

### 2-4. 서버 측 검증과 판정 (클라이언트 검증은 편의용)
아래 규칙은 **서버에서 다시 검사**하고, 위반하면 400 오류를 돌려준다.
- 기본정보 4개 필수: 점검자, 소속, 장소, 일자
- 미점검 항목이 남아 있으면 제출할 수 없다.
- 주의·위험 항목은 이상 사항 메모가 필수다.
- 해당 없음 항목은 제외 사유가 필수다.
- 위험 → 다른 결과로 변경하거나, 위험 항목을 삭제할 때는 사유가 필수다(`reason` 누락 시 400). 이력은 `result_change_logs`에 남긴다.
- 확정·제출된 점검의 결과·메모·사진 변경은 거부한다(409).
- **종합 판정 로직은 `services/judgment.py` 한 곳에만 둔다.** 화면·보고서·통계가 모두 이 함수를 쓰며, 아티팩트와 같은 규칙을 따른다.
  - 항목 0개 → 판정 불가
  - 위험 1건 이상 → 즉시 조치 필요
  - 주의 1건 이상 → 개선 필요
  - 미점검 있음 → 점검 중
  - 모두 해당 없음 → 판정 불가
  - 그 외 → 양호
  - 비율은 해당 없음을 제외한 건수로 계산한다.

### 2-5. 사진 저장 (서버 파일 저장소)
- 사진은 DB가 아니라 `instance/uploads/YYYY/MM/<uuid>.jpg`에 저장하고, DB에는 메타정보만 저장한다.
- 업로드 처리 순서:
  1. 클라이언트에서 긴 변 1280px로 줄인 JPEG를 업로드한다(기존 로직 재사용, 통신량 절감).
  2. 서버에서 Pillow로 다시 열어 실제 이미지인지 확인한다. 확장자나 MIME만으로 판단하지 않는다.
  3. `ImageOps.exif_transpose`로 회전을 보정한 뒤 **EXIF를 제거**하고 재저장한다(GPS 위치정보 노출 방지).
  4. 긴 변 최대 1920px, JPEG 품질 80으로 저장하고, 썸네일(320px)을 별도로 만든다.
- 제한: 요청 1건 15MB(`MAX_CONTENT_LENGTH`), 항목당 사진 10장, 허용 형식은 JPEG·PNG·WebP다.
- 파일명은 서버가 UUID로 생성한다. 원래 파일명은 표시용으로만 저장한다(경로 조작 방지).
- 사진 조회는 정적 경로로 노출하지 않는다. `GET /photos/<id>`에서 **권한을 확인한 뒤** `send_file`로 내려준다.
- 사진 삭제는 소프트 삭제 후, 확정 전 점검만 실제 파일을 정리한다.

### 2-6. 관리번호 발급
- 형식: `RSI-YYYYMMDD-NNN` (예: `RSI-20261124-003`)
- `report_sequences` 테이블에서 날짜별 일련번호를 **트랜잭션 안에서** 증가시킨다. SQLite는 `BEGIN IMMEDIATE`를 사용한다.
- `inspections.report_no`에 UNIQUE 제약을 건다. 아티팩트의 랜덤 접미사는 더 이상 필요 없다.

### 2-7. 자동 임시저장 (서버 저장 + 오프라인 대비)
- 입력이 바뀌면 800ms 디바운스 후 `PATCH` API로 저장한다. 상단의 "마지막 저장 HH:MM:SS"는 **서버 응답 시각**으로 표시한다.
- 네트워크가 실패하면 변경분을 `localStorage` 대기열에 쌓고 "오프라인 — 미전송 N건"을 표시한다. 연결이 돌아오면 순서대로 재전송한다.
- **동시 수정 방지(낙관적 잠금)**: `inspections.version` 값을 요청에 함께 보낸다. 서버 값과 다르면 409를 돌려주고, 화면은 "다른 곳에서 수정되었습니다. 새로고침" 안내를 띄운다.
- 브라우저를 다시 열면 서버에서 최신 작성 중 점검을 불러온다("이어서 작성" 안내는 유지).

### 2-8. 체크리스트 템플릿 관리
- 기본 항목 3개 분야 18개를 하드코딩하지 않고 `checklist_templates` 테이블에 둔다. 최초 실행 시 시드로 넣는다.
- 관리자는 분야·항목을 추가·수정·순서 변경·비활성화할 수 있다.
- 새 점검은 선택한 템플릿을 **복사**해서 만든다. 이후 템플릿을 바꿔도 기존 점검에는 영향이 없다.
- 점검 중 항목 추가·삭제 기능은 유지한다(해당 점검에만 적용).

### 2-9. 감사로그 (audit log)
아래 동작을 `audit_logs`에 기록한다. 기록 내용은 사용자, 시각, IP, 대상, 상세(JSON)다.
- 로그인 성공·실패, 계정 잠금, 비밀번호 변경
- 점검 생성·제출·확인·반려·삭제, 관리번호 발급
- 위험 결과 변경·위험 항목 삭제(사유 포함)
- 조치 상태 변경, JSON 불러오기, 전체 내보내기

관리자 화면에서 기간·사용자·동작으로 조회할 수 있어야 한다.

### 2-10. 백업·내보내기
- 기존 JSON 내보내기·불러오기 형식을 유지한다(`app: "railway-safety-inspection"`). 사진은 base64로 포함하고, 서버 불러오기 시 파일로 다시 저장한다.
  - 불러오기 시 형식 검증, ID 충돌 시 덮어쓰기·건너뛰기 선택 기능을 유지한다.
- **통계 CSV 내보내기**: 기간별 점검 목록과 이상 항목 목록을 엑셀에서 열 수 있도록 UTF-8 BOM으로 내보낸다.
- **DB 백업 CLI**: `flask backup` 명령으로 SQLite 온라인 백업 API(`sqlite3.Connection.backup`)와 uploads 폴더를 `backups/YYYYMMDD_HHMMSS.zip`에 저장한다.

### 2-11. 보고서 출력
- 보고서는 서버가 렌더링하는 전용 페이지(`/inspections/<id>/report/print`)로 만든다. 기존 `reportCss`를 `static/css/report.css`로 옮긴다.
- 로컬 웹앱은 iframe 제약이 없으므로 **[인쇄] 버튼에서 `window.print()`가 바로 동작**한다. PDF는 브라우저의 "PDF로 저장"을 사용한다.
- 표와 사진이 페이지 중간에서 잘리지 않도록 하는 페이지 나눔 규칙(`break-inside: avoid`)을 유지한다.
- 보고서에 결재 정보(제출 시각, 확인자, 확인 시각, 반려 이력)를 추가한다.

### 2-12. 보안 기본 설정
- `SECRET_KEY`는 `.env`에서 읽는다. 값이 없으면 앱이 시작되지 않게 한다.
- 쿠키 설정: `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`. HTTPS 환경에서는 `SESSION_COOKIE_SECURE=True`로 바꾼다.
- 응답 헤더: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, 기본 CSP `default-src 'self'; img-src 'self' data: blob:`
- 사용자 입력은 Jinja 자동 이스케이프로 출력한다. JavaScript에서 `innerHTML`에 사용자 값을 넣을 때는 반드시 `esc()`를 거친다(기존 유틸 유지).
- 모든 POST·PATCH·DELETE는 CSRF 토큰을 검사한다. JSON API는 `X-CSRFToken` 헤더로 받는다.
- 디버그 모드는 개발 환경에서만 켠다.
- 화면 안내 문구 "실제 개인정보 및 보안이 필요한 철도 시설 정보는 입력하지 마세요"를 유지한다. 운영 전환 시 보안성 검토를 받도록 README에 명시한다.

### 2-13. 시간 처리
- DB에는 **UTC ISO 8601 문자열**로 저장하고, 화면과 보고서에는 **Asia/Seoul**로 표시한다.
- 점검 일자(`inspect_date`)와 조치 예정일·완료일은 날짜 문자열(`YYYY-MM-DD`)로 저장한다.
- 기한 초과 판단은 **서울 기준 오늘 날짜**로 한다.

---

## 3. 폴더 구조

```
railway-safety/
├─ app/
│  ├─ __init__.py            # create_app(), 블루프린트 등록, 보안 헤더
│  ├─ config.py              # Dev/Test 설정
│  ├─ extensions.py          # db, migrate, login_manager, csrf
│  ├─ models.py              # SQLAlchemy 모델 (4장 스키마)
│  ├─ cli.py                 # init-db, create-admin, seed, backup 명령
│  ├─ auth/                  # 로그인, 로그아웃, 비밀번호 변경
│  ├─ inspections/
│  │  ├─ views.py            # 화면 라우트 (Jinja)
│  │  └─ api.py              # JSON API (/api/...)
│  ├─ admin/                 # 사용자·템플릿·감사로그 관리
│  ├─ services/
│  │  ├─ judgment.py         # 집계·종합 판정 (단일 진실 원천)
│  │  ├─ validation.py       # 제출 전 검증
│  │  ├─ report_no.py        # 관리번호 발급
│  │  ├─ images.py           # 사진 검증·재인코딩·썸네일
│  │  ├─ workflow.py         # 제출/확인/반려 상태 전이
│  │  ├─ export_import.py    # JSON·CSV
│  │  ├─ permissions.py      # 권한 검사 함수
│  │  └─ audit.py            # 감사로그 기록
│  ├─ templates/
│  │  ├─ base.html
│  │  ├─ auth/login.html, password.html
│  │  ├─ inspections/info.html, check.html, report.html, print.html
│  │  ├─ history.html        # 이력·대시보드
│  │  └─ admin/users.html, templates.html, audit.html
│  └─ static/
│     ├─ css/app.css, report.css   # 기존 아티팩트 CSS 이전
│     └─ js/common.js (esc, toast, modal, api 래퍼)
│        check.js (체크리스트·자동저장·사진), signature.js, history.js
├─ instance/                 # app.db, uploads/  ← .gitignore
├─ migrations/
├─ backups/                  # ← .gitignore
├─ reference/railway-safety.html
├─ tests/
├─ .env.example
├─ requirements.txt
├─ run.py                    # from app import create_app; app = create_app()
└─ README.md
```

---

## 4. SQLite 데이터베이스 설계

### 4-1. 연결 설정
연결할 때마다 아래 PRAGMA를 적용한다(SQLAlchemy `connect` 이벤트 사용).

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

### 4-2. 테이블 (DDL 기준; SQLAlchemy 모델로 동일하게 구현)

```sql
-- 사용자
CREATE TABLE users (
  id                    INTEGER PRIMARY KEY,
  username              TEXT NOT NULL UNIQUE,
  password_hash         TEXT NOT NULL,
  name                  TEXT NOT NULL,
  org                   TEXT NOT NULL DEFAULT '',
  role                  TEXT NOT NULL CHECK (role IN ('inspector','confirmer','admin')),
  is_active             INTEGER NOT NULL DEFAULT 1,
  must_change_password  INTEGER NOT NULL DEFAULT 1,
  failed_login_count    INTEGER NOT NULL DEFAULT 0,
  locked_until          TEXT,
  last_login_at         TEXT,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL
);

-- 체크리스트 템플릿
CREATE TABLE checklist_templates (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  is_default  INTEGER NOT NULL DEFAULT 0,
  is_active   INTEGER NOT NULL DEFAULT 1,
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE TABLE template_categories (
  id          INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL REFERENCES checklist_templates(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE template_items (
  id          INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES template_categories(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  is_active   INTEGER NOT NULL DEFAULT 1
);

-- 점검 (보고서 1건)
CREATE TABLE inspections (
  id               INTEGER PRIMARY KEY,
  public_id        TEXT NOT NULL UNIQUE,          -- UUID, URL·JSON 교환용
  report_no        TEXT UNIQUE,                   -- 확인 시 발급
  status           TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft','submitted','confirmed','rejected')),
  inspector_id     INTEGER NOT NULL REFERENCES users(id),
  inspector_name   TEXT NOT NULL,                 -- 작성 시점 스냅샷
  inspector_org    TEXT NOT NULL,
  place            TEXT NOT NULL DEFAULT '',
  inspect_date     TEXT NOT NULL,                 -- YYYY-MM-DD
  template_id      INTEGER REFERENCES checklist_templates(id),
  copied_from_id   INTEGER REFERENCES inspections(id),
  started_at       TEXT,                          -- 점검 시작 시간
  submitted_at     TEXT,                          -- 종료 시간 (제출 시)
  confirmer_id     INTEGER REFERENCES users(id),
  confirmer_name   TEXT,
  confirmed_at     TEXT,
  rejected_reason  TEXT,
  version          INTEGER NOT NULL DEFAULT 1,    -- 낙관적 잠금
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  deleted_at       TEXT,                          -- 소프트 삭제
  deleted_reason   TEXT
);
CREATE INDEX ix_insp_date      ON inspections(inspect_date);
CREATE INDEX ix_insp_status    ON inspections(status);
CREATE INDEX ix_insp_inspector ON inspections(inspector_id);

-- 점검별 분야 / 항목 (템플릿에서 복사)
CREATE TABLE inspection_categories (
  id             INTEGER PRIMARY KEY,
  inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
  name           TEXT NOT NULL,
  sort_order     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE inspection_items (
  id                  INTEGER PRIMARY KEY,
  inspection_id       INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
  category_id         INTEGER NOT NULL REFERENCES inspection_categories(id) ON DELETE CASCADE,
  name                TEXT NOT NULL,
  sort_order          INTEGER NOT NULL DEFAULT 0,
  result              TEXT CHECK (result IN ('ok','caution','danger','na')),  -- NULL = 미점검
  memo                TEXT NOT NULL DEFAULT '',
  na_reason           TEXT NOT NULL DEFAULT '',
  original_result     TEXT,          -- 확인(확정) 시점 결과 보존
  original_memo       TEXT,
  original_na_reason  TEXT,
  original_saved_at   TEXT,
  is_deleted          INTEGER NOT NULL DEFAULT 0,  -- 위험 항목 삭제 이력 보존용
  deleted_reason      TEXT,
  deleted_by          INTEGER REFERENCES users(id),
  deleted_at          TEXT,
  updated_at          TEXT NOT NULL
);
CREATE INDEX ix_item_insp_result ON inspection_items(inspection_id, result);

-- 개선 및 사후 조치 (주의·위험 항목 1:1)
CREATE TABLE item_actions (
  id          INTEGER PRIMARY KEY,
  item_id     INTEGER NOT NULL UNIQUE REFERENCES inspection_items(id) ON DELETE CASCADE,
  plan        TEXT NOT NULL DEFAULT '',
  owner_name  TEXT NOT NULL DEFAULT '',
  due_date    TEXT,                          -- YYYY-MM-DD
  status      TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','in_progress','done')),
  done_date   TEXT,
  updated_by  INTEGER REFERENCES users(id),
  updated_at  TEXT NOT NULL
);
CREATE INDEX ix_action_status_due ON item_actions(status, due_date);

-- 사진 (현장 사진 / 조치 완료 사진)
CREATE TABLE photos (
  id             INTEGER PRIMARY KEY,
  item_id        INTEGER NOT NULL REFERENCES inspection_items(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN ('finding','action')),
  stored_path    TEXT NOT NULL UNIQUE,       -- uploads 기준 상대경로
  thumb_path     TEXT NOT NULL,
  original_name  TEXT,
  mime           TEXT NOT NULL,
  size_bytes     INTEGER NOT NULL,
  width          INTEGER, height INTEGER,
  sha256         TEXT NOT NULL,
  uploaded_by    INTEGER NOT NULL REFERENCES users(id),
  created_at     TEXT NOT NULL,
  is_deleted     INTEGER NOT NULL DEFAULT 0
);

-- 전자서명
CREATE TABLE signatures (
  id             INTEGER PRIMARY KEY,
  inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
  role           TEXT NOT NULL CHECK (role IN ('inspector','confirmer')),
  signer_id      INTEGER NOT NULL REFERENCES users(id),
  signer_name    TEXT NOT NULL,
  image_path     TEXT NOT NULL,              -- PNG 파일
  signed_at      TEXT NOT NULL,
  ip             TEXT,
  UNIQUE (inspection_id, role)
);

-- 위험 결과 변경·삭제 이력 (보고서 출력용)
CREATE TABLE result_change_logs (
  id             INTEGER PRIMARY KEY,
  inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
  item_id        INTEGER NOT NULL REFERENCES inspection_items(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN ('change','delete')),
  from_result    TEXT NOT NULL,
  to_result      TEXT,                       -- 삭제 시 NULL
  reason         TEXT NOT NULL,
  changed_by     INTEGER NOT NULL REFERENCES users(id),
  changed_at     TEXT NOT NULL
);

-- 결재 이력 (제출·확인·반려)
CREATE TABLE workflow_logs (
  id             INTEGER PRIMARY KEY,
  inspection_id  INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
  action         TEXT NOT NULL CHECK (action IN ('submit','confirm','reject')),
  reason         TEXT,
  user_id        INTEGER NOT NULL REFERENCES users(id),
  created_at     TEXT NOT NULL
);

-- 관리번호 일련번호
CREATE TABLE report_sequences (
  date_key  TEXT PRIMARY KEY,                -- YYYYMMDD
  last_seq  INTEGER NOT NULL DEFAULT 0
);

-- 감사로그
CREATE TABLE audit_logs (
  id           INTEGER PRIMARY KEY,
  user_id      INTEGER REFERENCES users(id),
  action       TEXT NOT NULL,                -- 예: login.fail, inspection.confirm
  target_type  TEXT,
  target_id    TEXT,
  detail_json  TEXT,
  ip           TEXT,
  user_agent   TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX ix_audit_created ON audit_logs(created_at);
```

### 4-3. 코드값 ↔ 화면 표기

| 컬럼 | 코드 | 화면 표기 (아이콘 + 텍스트) |
|---|---|---|
| result | ok / caution / danger / na / NULL | ✓ 정상 / ▲ 주의 / ✕ 위험 / — 해당 없음 / ○ 미점검 |
| action.status | todo / in_progress / done | 미조치 / 진행 중 / 완료 |
| inspection.status | draft / submitted / confirmed / rejected | 작성 중 / 제출됨(확인 대기) / 완료(확정) / 반려 |

---

## 5. 화면(페이지) 라우트

| URL | 화면 | 권한 |
|---|---|---|
| `GET/POST /login`, `POST /logout` | 로그인 / 로그아웃 | 공개 / 로그인 |
| `GET/POST /password` | 비밀번호 변경 (최초 로그인 시 강제) | 로그인 |
| `GET /` | 이력·통계 대시보드 (검색·필터 포함) | 로그인 |
| `POST /inspections/new` | 새 점검 생성 (템플릿 선택 또는 `copy_from`) | 로그인 |
| `GET /inspections/<pid>/info` | 기본정보 입력 | 작성자 |
| `GET /inspections/<pid>/check` | 체크리스트 (탭, 필터, 위험 배너, 조치 관리) | 조회 권한자 |
| `GET /inspections/<pid>/report` | 보고서 미리보기 + 서명 + 제출/확인/반려 | 조회 권한자 |
| `GET /inspections/<pid>/report/print` | 인쇄 전용 페이지 | 조회 권한자 |
| `GET /admin/users` | 사용자 관리 (생성·역할·잠금 해제·비밀번호 초기화) | 관리자 |
| `GET /admin/templates` | 체크리스트 템플릿 관리 | 관리자 |
| `GET /admin/audit` | 감사로그 조회 | 관리자 |

- 주간/야간 모드는 `localStorage`에 유지한다(사용자 개인 설정).
- 상단의 위험 경고 배너, "판정은 참고용" 안내, 개인정보 입력 주의 안내는 그대로 유지한다.

---

## 6. JSON API 명세

공통 규칙:
- 경로 접두사는 `/api`다.
- 인증은 세션으로 하고, `X-CSRFToken` 헤더가 필수다.
- 성공 응답: `{"ok": true, "data": {...}}`
- 실패 응답: `{"ok": false, "error": {"code": "VALIDATION", "message": "...", "fields": {...}}}`
- 상태코드: 400 검증 실패, 401 미로그인, 403 권한 없음, 404, 409 상태·버전 충돌, 413 파일 초과

| 메서드 · 경로 | 설명 |
|---|---|
| `GET /api/inspections?q=&from=&to=&judgment=&status=&page=` | 이력 검색·필터 (판정 필터 포함, 페이지당 20건) |
| `POST /api/inspections` | 생성 `{template_id}` 또는 `{copy_from}` (결과 초기화 복사) |
| `GET /api/inspections/<pid>` | 점검 전체 (분야·항목·조치·사진 메타·서명 여부·집계·판정) |
| `PATCH /api/inspections/<pid>` | 기본정보 수정 `{version, name, org, place, inspect_date}` |
| `DELETE /api/inspections/<pid>` | 작성 중 삭제 / 관리자 소프트 삭제 `{reason}` |
| `POST /api/inspections/<pid>/start` | 시작 시간 기록 (최초 1회) |
| `POST /api/inspections/<pid>/categories/<cid>/items` | 항목 추가 `{name}` |
| `PATCH /api/items/<id>` | `{version, result?, memo?, na_reason?, reason?}` — 위험에서 변경 시 `reason` 필수 |
| `DELETE /api/items/<id>` | 항목 삭제 — 위험 항목이면 `{reason}` 필수, 소프트 삭제 |
| `PATCH /api/items/<id>/action` | 조치 정보 수정 (확정 후에도 허용). `done`으로 바꿀 때 완료일이 없으면 오늘로 설정 |
| `POST /api/items/<id>/photos` | multipart `file`, `kind=finding|action` |
| `DELETE /api/photos/<id>` | 사진 삭제 (확정 후 현장 사진은 불가) |
| `GET /photos/<id>` , `GET /photos/<id>/thumb` | 권한 확인 후 이미지 전송 |
| `POST /api/inspections/<pid>/signatures` | `{role, image: "data:image/png;base64,..."}` (최대 300KB) |
| `POST /api/inspections/<pid>/submit` | 검증 → 제출 (종료 시간 기록, 결과 잠금) |
| `POST /api/inspections/<pid>/confirm` | 확인자 서명 확인 → 관리번호 발급 → 최초 결과 보존 |
| `POST /api/inspections/<pid>/reject` | `{reason}` 필수 |
| `GET /api/dashboard?from=&to=` | 전체 점검 수, 위험 건수, 미조치·진행 중·기한 초과, 조치 완료율, 분야별 이상 빈도 |
| `GET /api/inspections/<pid>/export.json` | 1건 JSON (사진 base64 포함) |
| `GET /api/export/all.json` | 전체 JSON (관리자) |
| `POST /api/import` | JSON 불러오기 → 미리보기(충돌 목록) 응답 → `{mode: overwrite|skip}`로 확정 |
| `GET /export/stats.csv?from=&to=` | 통계 CSV (UTF-8 BOM) |

`POST /api/inspections/<pid>/submit`이 검증에 실패하면 프런트가 **첫 번째 미완료 항목으로 자동 이동**할 수 있도록, 미완료 목록을 함께 돌려준다.

```json
{"ok": false, "error": {"code": "INCOMPLETE", "message": "미완료 항목 3건",
  "items": [{"item_id": 12, "category_id": 2, "reason": "memo_required"}]}}
```

---

## 7. 프런트엔드 전환 지침

- 기존 아티팩트의 CSS, 아이콘·색상 규칙, 버튼 크기(48px 이상), 모바일 우선 레이아웃을 그대로 옮긴다.
- 기존 JS에서 `Store`(IndexedDB/localStorage) 계층을 **`api.js` 래퍼(fetch + CSRF + 오류 처리)** 로 교체한다. 렌더링 함수(`itemCard`, `buildReport` 등)는 가능한 한 재사용한다.
- 브라우저 기본 `alert`/`confirm` 대신 기존 커스텀 모달을 계속 쓴다.
- 차트는 기존처럼 CSS 막대 그래프를 쓴다. 외부 차트 라이브러리나 CDN은 쓰지 않는다.
- 카메라 촬영(`capture="environment"`)과 갤러리 선택 버튼을 분리한 구성을 유지한다.
- 업로드 중 진행 표시와 실패 시 재시도 버튼을 추가한다.
- 서명 캔버스는 기존 `signature.js` 로직을 쓰고, 저장 시 서버 API로 전송한다.

---

## 8. 로컬 구동 구성

### 8-1. `.env.example`

```
FLASK_APP=run.py
FLASK_DEBUG=1
SECRET_KEY=change-this-to-a-long-random-string
DATABASE_URL=sqlite:///app.db        # instance/ 폴더 기준
UPLOAD_DIR=uploads                   # instance/ 폴더 기준
MAX_CONTENT_LENGTH_MB=15
SESSION_HOURS=8
TIMEZONE=Asia/Seoul
```

### 8-2. CLI 명령 (`app/cli.py`)

| 명령 | 동작 |
|---|---|
| `flask init-db` | `instance/` 폴더·DB·uploads 폴더 생성 + 마이그레이션 적용 + 기본 템플릿 시드 |
| `flask create-admin` | 아이디·이름·비밀번호를 대화식으로 입력받아 관리자 생성 |
| `flask seed-demo` | (선택) 시연용 사용자 3명(점검자·확인자·관리자)과 샘플 점검 5건 생성. **개발 모드에서만 동작** |
| `flask backup` | DB 온라인 백업 + uploads를 zip으로 저장 |

### 8-3. 실행 순서 (README에 그대로 기재)

```bash
# 1) 가상환경
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2) 패키지 설치
pip install -r requirements.txt

# 3) 환경설정
cp .env.example .env        # Windows: copy .env.example .env
# SECRET_KEY 생성 예: python -c "import secrets; print(secrets.token_hex(32))"

# 4) DB 초기화 + 관리자 생성
flask init-db
flask create-admin
flask seed-demo             # 선택

# 5) 실행
flask run                   # http://127.0.0.1:5000
```

### 8-4. 휴대폰으로 현장 테스트 (같은 와이파이)
- `flask run --host 0.0.0.0` 으로 실행하고, 휴대폰에서 `http://<PC의 IP>:5000`에 접속한다.
- PC 방화벽에서 5000번 포트 인바운드를 허용해야 한다(README에 안내).
- 사진 첨부는 파일 입력 방식이라 http에서도 동작한다. 로그인 정보가 암호화되지 않으므로 **사내 테스트망에서만** 사용하도록 안내한다.

---

## 9. 테스트 (pytest)

`tests/`에 최소 아래 테스트를 작성하고, 모두 통과해야 한다. 테스트 DB는 임시 SQLite 파일을 쓴다.

- `test_judgment.py`: 판정 6가지 경우, 해당 없음 제외 비율 계산
- `test_validation.py`: 미점검·메모 누락·제외 사유 누락 시 제출 거부, 미완료 목록 반환
- `test_auth.py`: 로그인 성공·실패, 5회 실패 잠금, 비밀번호 해시 저장, 최초 비밀번호 변경 강제
- `test_permissions.py`: 다른 사람 점검 수정 403, 점검자의 확인 시도 403, 본인 점검 자기 확인 403
- `test_workflow.py`: 제출 → 확인 시 관리번호 발급·최초 결과 보존, 반려 → 수정 → 재제출, 확정 후 결과 수정 409, 조치 수정 허용
- `test_danger_change.py`: 위험 변경·삭제 시 사유 누락 400, 이력 기록
- `test_report_no.py`: 같은 날짜 연속 발급 시 001, 002…, 중복 없음
- `test_photos.py`: 이미지가 아닌 파일 거부, EXIF 제거 확인, 15MB 초과 413, 권한 없는 사진 조회 403
- `test_concurrency.py`: version 불일치 시 409
- `test_import_export.py`: 내보낸 JSON을 다시 불러오면 동일한 결과, 형식 오류 파일 거부, 충돌 시 덮어쓰기·건너뛰기

---

## 10. 개발 단계 (마일스톤)

| 단계 | 내용 | 완료 확인 |
|---|---|---|
| M1 | 프로젝트 골격, 설정, DB 모델·마이그레이션, CLI, 로그인·권한 | `flask init-db`, `create-admin` 후 로그인 가능 |
| M2 | 기본정보·체크리스트·결과 선택·필터·탭, 서버 자동저장, 낙관적 잠금 | 새로고침해도 입력 유지, 두 탭 동시 수정 시 409 안내 |
| M3 | 사진 업로드·썸네일·삭제·권한 조회 | 휴대폰 촬영 사진이 첨부되고 EXIF 제거됨 |
| M4 | 보고서·서명·제출/확인/반려·관리번호·인쇄 페이지 | A4 인쇄 시 표·사진 잘림 없음 |
| M5 | 개선·사후 조치, 기한 초과, 위험 배너·변경 이력 | 예정일이 지난 미완료 조치가 "기한 초과"로 표시 |
| M6 | 이력 검색·필터, 대시보드, 분야별 그래프, CSV | 통계 수치가 DB 수동 집계와 일치 |
| M7 | JSON 내보내기·불러오기, 백업 CLI | 백업 zip으로 복원 가능 |
| M8 | 관리자: 사용자·템플릿·감사로그 | 템플릿 수정이 기존 점검에 영향 없음 |
| M9 | 테스트 정리, README, 보안 헤더 점검 | `pytest` 전부 통과 |

각 단계가 끝날 때마다 실행 화면 캡처와 변경 사항 요약을 보고한다.

---

## 11. 최종 완료 기준 (체크리스트)

- [ ] 아티팩트의 1~14번 기능이 모두 웹앱에서 동작한다 (시연용 비밀번호 → 계정 로그인으로 대체).
- [ ] 모든 데이터가 SQLite와 `instance/uploads`에 저장되고, 브라우저를 바꿔도 같은 데이터가 보인다.
- [ ] 미완료 항목이 있으면 서버가 제출을 거부하고, 화면은 해당 항목으로 이동한다.
- [ ] 위험 변경·삭제는 사유 없이 처리되지 않고, 보고서와 감사로그에 남는다.
- [ ] 제출 → 확인 → 확정 흐름과 반려 흐름이 동작하고, 확정 후에는 조치 정보만 수정된다.
- [ ] 관리번호가 `RSI-YYYYMMDD-NNN` 형식으로 중복 없이 발급된다.
- [ ] 다른 사용자의 점검과 사진에 권한 없이 접근할 수 없다.
- [ ] 보고서 인쇄·PDF 저장이 동작한다.
- [ ] 외부 CDN 없이(인터넷 차단 상태) 로컬에서 모든 화면이 정상 표시된다.
- [ ] 모바일·태블릿·PC에서 화면이 깨지지 않는다.
- [ ] `README.md`만 보고 새 PC에서 10분 안에 실행할 수 있다.
- [ ] `pytest`가 모두 통과한다.

---

## 12. 유지할 안내 문구

- 로그인 화면: "실제 개인정보 및 보안이 필요한 철도 시설 정보는 입력하지 마세요."
  - 운영 승인 전까지 유지한다.
- 판정 영역과 보고서 하단: "본 앱의 종합 판정은 참고용이며, 실제 안전 판정은 관련 규정과 담당자의 판단에 따릅니다."
- 위험 선택 시: "즉시 해당 작업을 중지하고 현장 안전을 확보한 뒤, 내부 안전관리 절차에 따라 관리자에게 보고하세요."

---

## 13. 다음 단계 (이번 범위 밖, 참고)

- 운영 서버: Waitress(Windows) 또는 Gunicorn(Linux), 앞단에 Nginx와 **HTTPS 적용**. 그 후 `SESSION_COOKIE_SECURE=True`로 바꾼다.
- 동시 사용자가 많아지면 PostgreSQL로 이전한다(SQLAlchemy 모델 재사용).
- 사내 계정 연동(SSO/LDAP), 위험 발생 시 관리자 알림(메일·메신저)
- 정기 백업 스케줄러와 백업 파일 외부 보관
- 개인정보·보안성 검토 및 접속 기록 보관 기준 수립
