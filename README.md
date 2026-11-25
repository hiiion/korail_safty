# 스마트 철도차량 안전점검 시스템 (Flask 웹앱)

단일 HTML 아티팩트(`reference/railway-safety.html` — 원본: `스마트 철도차량 안전점검 시스템.html`)를
`flask_작업지시서.md`에 따라 **Python Flask + SQLite** 기반 로컬 웹앱으로 옮긴 버전입니다.
데이터는 서버 DB(`instance/app.db`)와 서버 파일 저장소(`instance/uploads/`)에 저장되며,
계정·권한·결재(제출 → 확인 → 확정 / 반려)를 지원합니다.

> ⚠ 실제 개인정보 및 보안이 필요한 철도 시설 정보는 입력하지 마세요.
> 점검 항목·시연 데이터는 실제 기관의 공식 안전점검 기준이 아닌 예시입니다.
> 운영 환경으로 전환하기 전에 반드시 **보안성 검토**를 받으세요. (HTTPS, 서버 구성, 접속 기록 보관 기준 등)

---

## 1. 실행 방법 (Windows 기준, 약 5~10분)

필요: Python 3.11 이상. 화면은 외부 CDN 없이 동작합니다(패키지 설치 시에만 인터넷 필요).

```bash
# 1) 가상환경
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2) 패키지 설치
pip install -r requirements-dev.txt   # 테스트 포함 (운영: requirements.txt)

# 3) 환경설정
cp .env.example .env        # Windows: copy .env.example .env
# .env의 SECRET_KEY를 긴 임의 문자열로 바꾸세요. 생성 예:
#   python -c "import secrets; print(secrets.token_hex(32))"
# SECRET_KEY가 없으면 앱이 시작되지 않습니다.

# 4) DB 초기화 + 관리자 생성
flask init-db               # instance/·DB·uploads 생성 + 마이그레이션 + 기본 체크리스트(7개 분야 38개 항목)
flask create-admin          # 아이디·이름·소속·비밀번호를 대화식으로 입력
flask seed-demo             # (선택, 개발 모드 전용) 시연용 계정 7개 + 샘플 점검 13건

# 5) 실행
flask run                   # http://127.0.0.1:5000
```

> Windows에서 `python` 명령이 Microsoft Store를 열면 설치된 Python 경로로 직접 실행하세요.
> 가상환경을 활성화하지 않았다면 `.venv\Scripts\python.exe -m flask run`처럼 실행할 수 있습니다.

### 시연용 계정 (`flask seed-demo`, 개발 모드 FLASK_DEBUG=1 전용)

비밀번호는 모두 `Demo1234`. 운영에서는 사용하지 마세요.

| 아이디 | 이름 | 역할 |
|---|---|---|
| inspector1 ~ inspector5 | 김민수 · 이서연 · 박준호 · 정다운 · 한상철 | 점검자 |
| confirmer1 | 최지은 | 확인자 |
| admin1 | 관리자 | 관리자 |

시연 데이터는 아티팩트의 시연 시나리오(최근 60일, 반복 지적 2건, 위험도 상 부적합, 개선 전·후 사진)를 그대로 재현합니다.
사진은 Pillow로 그린 **예시 이미지**입니다.

### 휴대폰으로 현장 테스트 (같은 와이파이)

```bash
flask run --host 0.0.0.0
```

- 휴대폰에서 `http://<PC의 IP>:5000` 접속 (PC IP 확인: `ipconfig`의 IPv4 주소)
- PC 방화벽에서 **5000번 포트 인바운드 허용**이 필요합니다.
  (관리자 PowerShell: `New-NetFirewallRule -DisplayName "Flask 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow`)
- 사진 첨부(📷 촬영 / 🖼 갤러리)는 파일 입력 방식이라 http에서도 동작합니다.
- http는 로그인 정보가 암호화되지 않으므로 **사내 테스트망에서만** 사용하세요.

---

## 2. 화면과 주요 기능

| 메뉴 | 내용 |
|---|---|
| 대시보드 | 전체 점검·적합·부적합·미조치 KPI, 개선조치 완료율(도넛), 분야별 부적합 건수, 반복 지적사항 TOP 5, 업무시간 절감 효과, 작성 중 점검 "이어서 작성" |
| 점검 작성 | ① 기본정보(점검자·소속 부서·일시·장소·유형·대상·작업구역·작업 유형·차량/설비) → ② 항목 구성(조건별 분야 자동 추천) → ③ 점검 수행(적합/부적합/해당 없음, 부적합 세부정보·위험도·개선조치, 개선 전·후 사진, 특이사항, 항목 추가·수정·삭제, 과거 부적합 이력) → ④ 보고서 검토(종합의견 초안 자동 생성·수정, 서명, 제출) |
| 부적합 관리 | 제출·확정된 점검의 부적합 목록, 상태·위험도·기한 초과·반복 지적 필터, 조치 상태 변경·개선 후 사진·조치 내용 수정(변경 이력 기록) |
| 점검 이력 | 기간·점검자·소속·장소·유형·대상·부적합 유무·결재 상태 검색, 점검 요약 CSV / 항목별 상세 CSV(UTF-8 BOM) |
| 보고서 | A4 보고서 미리보기, **최초 보고서(확정 시점 보존)** / **최신 개선조치 현황** 전환, 인쇄 전용 페이지(PDF 저장), JSON 내보내기, 복사해서 새 점검 |
| 설정 | 내 계정, 업무시간 절감 기준(관리자 변경), 전체 JSON 내보내기·불러오기(관리자) |
| 관리자 | 사용자 관리(생성·역할·소속·사용 중지·잠금 해제·비밀번호 초기화), 체크리스트 템플릿(분야·항목·추천 규칙·순서·비활성화), 감사로그 조회 |

### 아티팩트 대비 추가된 운영 기능 (작업지시서 2장)

- **계정·권한**: 시연용 비밀번호(1234) 삭제 → 아이디·비밀번호 로그인, 해시 저장, 최초 로그인 시 비밀번호 변경 강제, 5회 실패 시 10분 잠금, 세션 8시간. 같은 **소속**끼리 조회, 관리자는 전체.
- **결재 흐름**: 제출(점검자 서명, 종료 시간 기록, 결과 잠금) → 확인(확인자 서명, 관리번호 `RSI-YYYYMMDD-NNN` 발급, 최초 보고서 보존) / 반려(사유 필수 → 수정 후 재제출). 본인 점검은 확인할 수 없음.
- **서버 검증**: 기본정보 필수값, 미점검·해당 없음 사유·부적합 세부정보 누락 시 제출 거부(미완료 목록 반환 → 화면이 첫 미완료 항목으로 이동), 제출·확정 후 결과 수정 409.
- **부적합 변경·삭제 사유**: 부적합 → 다른 결과로 변경하거나 부적합 항목을 삭제하려면 사유 필수(누락 시 400). 보고서와 감사로그에 기록.
- **자동저장**: 800ms 디바운스 후 서버 저장, "마지막 저장 HH:MM:SS"(서버 시각), 네트워크 실패 시 "오프라인 — 미전송 N건" 대기열 후 재전송, `version` 기반 낙관적 잠금(409 → 새로고침 안내).
- **사진**: 실제 이미지 검증 → 회전 보정 → **EXIF(GPS) 제거** → 긴 변 1920px·품질 80 재저장 + 썸네일 320px, 권한 확인 후 `/photos/<id>`로만 전송. 업로드 진행률·재시도.
- **감사로그**: 로그인 성공·실패·잠금, 비밀번호 변경, 점검 생성·제출·확인·반려·삭제, 관리번호 발급, 부적합 변경·삭제, 조치 상태 변경, 불러오기·전체 내보내기, 템플릿·설정 변경.
- **백업**: `flask backup` → SQLite 온라인 백업 + uploads를 `backups/YYYYMMDD_HHMMSS.zip`으로 저장 (복원 방법은 zip 안 `RESTORE.txt`).

### 판정·집계 규칙 (`app/services/judgment.py` 한 곳에만 존재)

- 적합률 = 적합 ÷ (적합 + 부적합) × 100 (해당 없음·미점검 제외), 진행률 = 입력 완료 ÷ 전체
- 종합의견 초안: 위험도 '상' → 기한 초과 → 미완료 조치 → 반복 지적 순으로 반영, 해당 없을 때만 적합률(95%/85%)로 양호 여부 서술
- 반복 지적: 동일 장소 + 동일 항목, 최근 60일 이내 부적합 2회 이상 (`app/services/repeat.py`)
- 기한 초과: 서울 기준 오늘 날짜 > 조치 예정일, 조치 완료 아님
- **판정·종합의견은 참고용**이며, 실제 안전 판단은 관련 규정과 담당자의 판단에 따릅니다.

---

## 2-1. Vercel + Supabase 배포

Vercel은 요청마다 서버리스 함수로 Flask를 실행하고(`api/index.py`, `vercel.json`), 파일시스템이 유지되지 않으므로
DB는 **Supabase Postgres**, 사진·서명은 **Supabase Storage 비공개 버킷**에 저장합니다.
사진은 항상 앱의 `/photos/<id>`(권한 확인)를 거쳐 내려가며, Supabase 서비스 키는 서버 환경변수에만 둡니다.

**현재 배포본:** https://korail-safty.vercel.app — Vercel 마켓플레이스 Supabase 연동(서울 리전)으로 만들어
`POSTGRES_URL`·`SUPABASE_URL`·`SUPABASE_SERVICE_ROLE_KEY`가 Vercel에 자동 등록되어 있고 앱이 그대로 읽습니다.
`vercel env pull .env.vercel --environment production`으로 내려받아 로컬에서 `init-db` 등을 운영 DB에 실행할 수 있습니다.
Supabase 공개 API(anon 키)로 테이블이 노출되지 않도록 **모든 테이블에 RLS를 켜 두었습니다** — 마이그레이션으로 테이블을 추가하면 새 테이블도 RLS를 켜세요.
코드 수정 후 재배포: `vercel deploy --prod`

(수동으로 Supabase를 직접 만드는 경우)
1. Supabase에서 프로젝트 생성 → 다음 값을 확인
   - **Connect → Transaction pooler** 연결 문자열(포트 6543) → `DATABASE_URL`
   - **Project Settings → API**: Project URL → `SUPABASE_URL`, `service_role` 키 → `SUPABASE_SERVICE_KEY`
2. 로컬에 `.env.production` 파일을 만들고(깃·Vercel 업로드 제외됨) 위 값과 `SECRET_KEY`, `SESSION_COOKIE_SECURE=1` 입력
3. 스키마·기본 템플릿·버킷 생성 후 관리자 계정 만들기 (PowerShell)
   ```powershell
   Get-Content .env.production | ForEach-Object { if ($_ -match '^\s*([^#=]+)=(.*)$') { Set-Item "env:$($matches[1].Trim())" $matches[2].Trim() } }
   .venv\Scripts\python.exe -m flask --app run.py init-db
   .venv\Scripts\python.exe -m flask --app run.py create-admin
   ```
4. Vercel 프로젝트 환경변수(Production)에 같은 값 등록 후 `vercel deploy --prod`

제약: Vercel은 요청 본문이 **4.5MB**로 제한됩니다. 사진은 브라우저에서 1280px JPEG로 줄여 올리므로 문제없지만,
사진이 많이 든 **JSON 불러오기**는 실패할 수 있습니다(로컬 실행본에서 불러온 뒤 같은 DB를 쓰세요).
`flask backup`은 SQLite 전용이며, Supabase는 대시보드의 백업 기능을 사용합니다.
Postgres로 같은 테스트를 돌리려면 `TEST_DATABASE_URL=postgresql://... pytest`.

## 3. 폴더 구조

```
korail_safty/
├─ app/
│  ├─ __init__.py          # create_app(), 블루프린트 등록, 보안 헤더(CSP 등)
│  ├─ config.py · extensions.py · models.py · domain.py(선택지·추천 규칙) · seed.py
│  ├─ cli.py               # init-db, create-admin, seed-demo, backup
│  ├─ demo_images.py       # 시연용 예시 사진 생성
│  ├─ auth/ · admin/
│  ├─ inspections/         # views.py(화면) · api.py(JSON API) · core.py(생성·구성·직렬화)
│  ├─ services/            # judgment · repeat · validation · report · report_no · images · storage
│  │                       # workflow · export_import · permissions · audit
│  ├─ templates/ · static/ # Jinja + 순수 JS (외부 CDN 없음)
├─ migrations/             # Flask-Migrate
├─ reference/railway-safety.html
├─ tests/                  # pytest
├─ .env.example · requirements.txt · run.py
```

## 4. 테스트

```bash
pytest
```

판정·검증·인증·권한·결재·부적합 변경 사유·관리번호·사진(EXIF 제거, 15MB 초과 413, 권한)·동시 수정(409)·
JSON 내보내기/불러오기(아티팩트 백업 포함)·CSV를 검사합니다.

## 5. JSON 불러오기 형식

- 이 웹앱의 내보내기 파일(`app: "railway-safety-inspection"`, version 2 — 사진은 base64로 포함)
- 참고 아티팩트의 **전체 백업 파일**(`app: "SRSI"`) — 아티팩트에서 쓰던 데이터를 그대로 옮길 수 있습니다.
  아티팩트의 문서번호(`SI-…`)는 그대로 유지되고, 확정본·최초 보고서·개선조치 이력이 함께 들어옵니다.
- 형식 검증 → 미리보기(충돌 목록) → 같은 ID가 있으면 **덮어쓰기 / 건너뛰기** 선택

## 6. 다음 단계 (이번 범위 밖)

- 운영 서버: Waitress(Windows) 또는 Gunicorn(Linux) + Nginx, **HTTPS 적용 후 `SESSION_COOKIE_SECURE=1`**
- 동시 사용자 증가 시 PostgreSQL 이전, 사내 계정 연동(SSO/LDAP), 위험 발생 알림
- 정기 백업 스케줄러와 외부 보관, 개인정보·보안성 검토 및 접속 기록 보관 기준 수립
