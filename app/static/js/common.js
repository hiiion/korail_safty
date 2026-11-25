'use strict';
/* =========================================================
   공통: 유틸 · 모달 · 토스트 · 라이트박스 · API 래퍼 · 자동저장 · 사진 업로드
   (참고 아티팩트의 유틸·모달을 그대로 옮기고, IndexedDB 저장 계층을 서버 API로 교체)
   ========================================================= */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = (n, l = 2) => String(n).padStart(l, '0');
const norm = s => String(s || '').replace(/\s+/g, '').toLowerCase();
const sleep = ms => new Promise(r => setTimeout(r, ms));
const BOOT = (() => { try { const el = document.getElementById('boot'); return el ? JSON.parse(el.textContent) : {}; } catch (e) { return {}; } })();

// 시간 표시는 항상 Asia/Seoul 기준 (DB는 UTC ISO 문자열)
const KST_FMT = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
function kst(ts) { if (!ts) return null; const d = ts instanceof Date ? ts : new Date(ts); return isNaN(d) ? null : KST_FMT.format(d).replace('T', ' '); }
const fmtDT = ts => { const s = kst(ts); return s ? s.slice(0, 16) : '-'; };
const fmtDate = ts => { const s = kst(ts); return s ? s.slice(0, 10) : '-'; };
const fmtTime = ts => { const s = kst(ts); return s ? s.slice(11, 19) : '-'; };
const todayStr = () => kst(new Date()).slice(0, 10);
const fmtPct = v => (v == null ? '산정 대상 없음' : v + '%');

const RES_LABEL = { ok: '적합', ng: '부적합', na: '해당 없음' };
const RISK = { h: '상', m: '중', l: '하' };
const ST = { todo: '미조치', in_progress: '조치 중', done: '조치 완료' };
const ST_ORDER = ['todo', 'in_progress', 'done'];
const stIdx = s => Math.max(0, ST_ORDER.indexOf(s));
const NG_REQ = [['content', '부적합 내용'], ['cause', '발생 원인'], ['risk', '위험도'], ['action', '개선조치 내용'], ['owner', '조치 담당자'], ['due', '조치 예정일']];
const photoUrl = id => '/photos/' + id;
const thumbUrl = id => '/photos/' + id + '/thumb';

/* ---------- 토스트 ---------- */
function toast(msg, type = '', ms = 2800) {
  const t = document.createElement('div'); t.className = 'toast ' + type; t.textContent = msg;
  $('#toasts').appendChild(t); setTimeout(() => t.remove(), ms);
}

/* ---------- 모달: 브라우저 alert/confirm 대신 자체 대화상자 사용 ---------- */
function modal({ title, html = '', buttons = [{ label: '확인', cls: 'primary', value: true }], wide = false, onOpen }) {
  return new Promise(resolve => {
    const bg = document.createElement('div'); bg.className = 'modal-bg';
    bg.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><h3>${esc(title)}</h3><div class="body">${html}</div><div class="foot"></div></div>`;
    const foot = $('.foot', bg); const m = $('.modal', bg);
    const prev = document.activeElement;
    const close = v => { bg.remove(); document.removeEventListener('keydown', onKey); try { prev && prev.focus && prev.focus({ preventScroll: true }); } catch (e) { } resolve(v); };
    const onKey = e => { if (e.key === 'Escape') close(null); };
    buttons.forEach(b => {
      const el = document.createElement('button'); el.type = 'button'; el.className = 'btn ' + (b.cls || ''); el.textContent = b.label;
      el.addEventListener('click', async () => { if (b.onClick) { const r = await b.onClick(m); if (r === false) return; close(r === undefined ? b.value : r); } else close(b.value); });
      foot.appendChild(el);
    });
    bg.addEventListener('click', e => { if (e.target === bg) close(null); });
    document.addEventListener('keydown', onKey);
    $('#modalRoot').appendChild(bg);
    if (onOpen) onOpen(m, close);
    const f = $('input:not([type=hidden]),textarea,select', m); if (f) setTimeout(() => f.focus(), 30);
  });
}
const confirmBox = (title, html, ok = '확인', danger = false) => modal({ title, html, buttons: [{ label: '취소', value: false }, { label: ok, cls: danger ? 'danger' : 'primary', value: true }] }).then(v => v === true);
const alertBox = (title, html) => modal({ title, html, buttons: [{ label: '확인', cls: 'primary', value: true }] });
// 사유 입력 모달 (부적합 변경·삭제, 반려, 확정 점검 삭제)
function reasonBox(title, html, ok = '확인', placeholder = '사유를 입력하세요') {
  return modal({
    title, html: `${html}<label class="f mt12" for="rb-text">사유<span class="req">*</span></label><textarea class="inp" id="rb-text" rows="3" placeholder="${esc(placeholder)}"></textarea><div class="err-msg hidden" id="rb-err">사유를 입력해야 진행할 수 있습니다.</div>`,
    buttons: [{ label: '취소', value: null }, { label: ok, cls: 'danger', onClick: m => { const v = $('#rb-text', m).value.trim(); if (!v) { $('#rb-err', m).classList.remove('hidden'); return false; } return v; } }]
  });
}

function lightbox(src) {
  if (!src) return;
  const lb = document.createElement('div'); lb.className = 'lightbox';
  lb.innerHTML = `<img alt="첨부 사진 확대"><button type="button" aria-label="닫기">✕</button>`;
  $('img', lb).src = src; lb.addEventListener('click', () => lb.remove());
  document.body.appendChild(lb);
}

/* ---------- API 래퍼 (fetch + CSRF + 오류 처리) ---------- */
const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
class NetworkError extends Error { }
async function api(method, url, body, opts = {}) {
  const headers = { 'X-CSRFToken': CSRF, 'Accept': 'application/json' };
  let payload;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch(url, { method, headers, body: payload, credentials: 'same-origin', cache: 'no-store' }); }
  catch (e) { throw new NetworkError('network'); }
  let json = null;
  try { json = await res.json(); } catch (e) { }
  if (!json) json = { ok: false, error: { code: 'HTTP_' + res.status, message: res.status === 413 ? '파일이 너무 큽니다.' : '서버 오류가 발생했습니다. (' + res.status + ')' } };
  json.status = res.status;
  if (res.status === 401 && !opts.noRedirect) { toast('로그인이 만료되었습니다. 다시 로그인하세요.', 'err', 4000); setTimeout(() => { location.href = '/login?next=' + encodeURIComponent(location.pathname); }, 1200); }
  if (res.status === 403 && json.error && json.error.code === 'PASSWORD_CHANGE_REQUIRED') location.href = '/password';
  return json;
}
const errMsg = r => (r && r.error && r.error.message) || '요청을 처리하지 못했습니다.';
async function apiOk(method, url, body) {
  let r;
  try { r = await api(method, url, body); } catch (e) { toast('서버에 연결할 수 없습니다. 네트워크를 확인하세요.', 'err', 4500); return null; }
  if (!r.ok) { toast(errMsg(r), 'err', 4500); return null; }
  return r;
}
function apiUpload(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open('POST', url); x.setRequestHeader('X-CSRFToken', CSRF); x.setRequestHeader('Accept', 'application/json');
    x.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    x.onload = () => {
      let j = null; try { j = JSON.parse(x.responseText); } catch (e) { }
      if (!j) j = { ok: false, error: { code: 'HTTP_' + x.status, message: x.status === 413 ? '파일이 너무 큽니다. (요청 1건 최대 15MB)' : '업로드에 실패했습니다. (' + x.status + ')' } };
      j.status = x.status; resolve(j);
    };
    x.onerror = () => reject(new NetworkError('network'));
    x.send(formData);
  });
}
async function conflictDialog() {
  const v = await modal({ title: '동시 수정 감지', html: '다른 곳(다른 탭·기기 또는 다른 사용자)에서 이 점검이 수정되었습니다.<br>최신 내용을 불러오려면 새로고침하세요.<br><span class="hint">(이 화면에서 아직 저장되지 않은 변경은 반영되지 않습니다.)</span>', buttons: [{ label: '닫기', value: null }, { label: '새로고침', cls: 'primary', value: 'reload' }] });
  if (v === 'reload') location.reload();
}

/* =========================================================
   자동 임시저장 (서버 저장 + 오프라인 대기열)
   - 입력이 바뀌면 800ms 디바운스 후 PATCH, 같은 대상(URL)의 변경은 하나로 합쳐 순서대로 전송
   - 네트워크 실패 시 localStorage 대기열에 보관 → "오프라인 — 미전송 N건" 표시, 연결 복구 시 재전송
   - 낙관적 잠금: 현재 version을 함께 보내고 409면 새로고침 안내
   ========================================================= */
const Saver = {
  ctx: null, pending: new Map(), timer: null, busy: false, lastSaved: null, conflict: false, OUTBOX: 'srsi_outbox',
  init(ctx) {
    this.ctx = ctx;
    window.addEventListener('online', () => this.retryOutbox());
    setInterval(() => { if (this.outbox().length) this.retryOutbox(); }, 15000);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') this.flush(); });
    window.addEventListener('beforeunload', e => { if (this.pending.size || this.busy) { this.flush(); e.preventDefault(); e.returnValue = ''; } });
    this.render();
    if (this.outbox().length) setTimeout(() => this.retryOutbox(), 500);
  },
  readAll() { try { const a = JSON.parse(localStorage.getItem(this.OUTBOX) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } },
  outbox() { return this.readAll().filter(o => o && this.ctx && o.pid === this.ctx.pid); },
  setOutbox(list) {
    const others = this.readAll().filter(o => !o || !this.ctx || o.pid !== this.ctx.pid);
    try { localStorage.setItem(this.OUTBOX, JSON.stringify(others.concat(list))); } catch (e) { }
  },
  queue(method, url, body, immediate) {
    const k = method + ' ' + url, prev = this.pending.get(k);
    this.pending.set(k, { method, url, body: Object.assign(prev ? prev.body : {}, body) });
    this.render('pending');
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), immediate ? 0 : 800);
  },
  async flush() {
    clearTimeout(this.timer); this.timer = null;
    if (this.busy) { this.timer = setTimeout(() => this.flush(), 200); return; }
    if (!this.pending.size) return;
    const ops = Array.from(this.pending.values()); this.pending.clear();
    await this.send(ops, false);
  },
  async idle() { await this.flush(); while (this.busy || this.pending.size) { await sleep(100); if (this.pending.size && !this.busy) await this.flush(); } },
  async send(ops, fromOutbox) {
    this.busy = true; this.render('saving');
    const keep = list => list.map(o => ({ pid: this.ctx.pid, method: o.method, url: o.url, body: o.body }));
    try {
      for (let i = 0; i < ops.length; i++) {
        const op = ops[i];
        let r;
        try { r = await api(op.method, op.url, Object.assign({}, op.body, { version: this.ctx.getVersion() })); }
        catch (e) {
          const rest = keep(ops.slice(i));
          this.setOutbox(fromOutbox ? rest : this.outbox().concat(rest));
          this.render('offline'); return false;
        }
        if (r.ok) {
          if (r.data && r.data.version != null) this.ctx.setVersion(r.data.version);
          this.lastSaved = r.server_time || new Date().toISOString();
          if (this.ctx.onSaved) this.ctx.onSaved(op, r);
          if (fromOutbox) this.setOutbox(keep(ops.slice(i + 1)));
        } else if (r.status === 409 && r.error && r.error.code === 'CONFLICT') {
          this.conflict = true; this.render();
          if (fromOutbox) this.setOutbox([]);
          conflictDialog(); return false;
        } else {
          if (fromOutbox) this.setOutbox(keep(ops.slice(i + 1)));
          toast(errMsg(r), 'err', 4500);
          if (this.ctx.onError) this.ctx.onError(op, r);
        }
      }
      return true;
    } finally { this.busy = false; this.render(); }
  },
  // 사진 업로드·항목 추가처럼 version을 바꾸는 단발성 요청은 자동저장과 겹치지 않게 순서대로 실행
  async exclusive(fn) {
    await this.idle();
    this.busy = true;
    try { return await fn(); } finally { this.busy = false; }
  },
  async retryOutbox() {
    if (this.busy || !this.ctx) return;
    const list = this.outbox(); if (!list.length) return;
    const ok = await this.send(list, true);
    if (ok && !this.outbox().length) toast('오프라인 중 변경한 내용을 서버에 저장했습니다.', 'ok');
  },
  render(st) {
    const el = $('#saveState'); if (!el || !this.ctx) return;
    el.classList.remove('hidden', 'saving', 'fail', 'saved', 'off');
    const n = this.outbox().length;
    if (this.conflict) { el.classList.add('fail'); el.textContent = '⚠ 다른 곳에서 수정됨 — 새로고침 필요'; return; }
    if (n) { el.classList.add('off'); el.textContent = `오프라인 — 미전송 ${n}건 · 눌러서 재시도`; return; }
    if (st === 'pending' || this.pending.size) { el.textContent = '변경됨 · 저장 대기'; return; }
    if (st === 'saving' || this.busy) { el.classList.add('saving'); el.textContent = '저장 중…'; return; }
    if (this.lastSaved) { el.classList.add('saved'); el.textContent = '마지막 저장 ' + fmtTime(this.lastSaved); return; }
    el.textContent = '저장됨 (서버)';
  }
};

/* =========================================================
   사진: 클라이언트에서 긴 변 1280px JPEG로 줄여 업로드 (통신량 절감, 아티팩트 processImage 재사용)
   서버는 Pillow로 다시 검증·EXIF 제거·재인코딩한다.
   ========================================================= */
function pickFiles(camera, multiple = true) {
  return new Promise(res => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp,image/*'; inp.multiple = multiple && !camera;
    if (camera) inp.setAttribute('capture', 'environment');
    inp.className = 'hidden';
    inp.addEventListener('change', () => { res(Array.from(inp.files || [])); inp.remove(); });
    document.body.appendChild(inp);
    inp.click();
  });
}
async function shrinkImage(file) {
  const okType = /^image\/(jpeg|jpg|png|webp|heic|heif)$/i.test(file.type) || /\.(jpe?g|png|webp|heic|heif)$/i.test(file.name || '');
  if (!okType) throw new Error(`이미지 파일(JPG·PNG·WEBP)만 첨부할 수 있습니다: ${file.name}`);
  if (file.size === 0) throw new Error(`빈 파일입니다: ${file.name}`);
  if (file.size > 40 * 1024 * 1024) throw new Error(`사진 용량이 너무 큽니다: ${file.name}`);
  const url = URL.createObjectURL(file);
  try {
    let img;
    try { img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('decode')); i.src = url; }); }
    catch (e) { throw new Error(`이미지를 읽을 수 없습니다. 지원되지 않는 형식이거나 손상된 파일입니다: ${file.name}`); }
    const w = img.naturalWidth, h = img.naturalHeight;
    if (!w || !h) throw new Error(`이미지 크기를 확인할 수 없습니다: ${file.name}`);
    const s = Math.min(1, 1280 / Math.max(w, h));
    const c = document.createElement('canvas'); c.width = Math.round(w * s); c.height = Math.round(h * s);
    const ctx = c.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height); ctx.drawImage(img, 0, 0, c.width, c.height);
    const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.8));
    if (!blob) throw new Error(`사진 압축에 실패했습니다: ${file.name}`);
    return blob;
  } finally { URL.revokeObjectURL(url); }
}
/* 업로드 큐: 진행률 표시 + 실패 시 재시도 버튼 */
const Uploads = {
  list: [], seq: 0, onChange: null,
  async add(files, itemId, kind, onDone) {
    for (const f of files) {
      const u = { uid: ++this.seq, itemId, kind, name: f.name || '사진', file: f, progress: 0, failed: false, msg: '', onDone };
      this.list.push(u); this.changed(u);
      await this.run(u);
    }
  },
  async run(u) {
    u.failed = false; u.msg = ''; u.progress = 0; this.changed(u);
    let blob;
    try { blob = u.blob || (u.blob = await shrinkImage(u.file)); }
    catch (e) { u.failed = true; u.msg = e.message; u.fatal = true; this.changed(u); return; }
    const fd = new FormData(); fd.append('file', blob, (u.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg'); fd.append('kind', u.kind);
    const exec = async () => {
      try {
        const r = await apiUpload(`/api/items/${u.itemId}/photos`, fd, p => { u.progress = p; this.changed(u); });
        if (!r.ok) { u.failed = true; u.msg = errMsg(r); u.fatal = r.status === 400 || r.status === 403 || r.status === 409 || r.status === 413; this.changed(u); return; }
        this.list = this.list.filter(x => x !== u); this.changed(u);
        if (u.onDone) await u.onDone(r);
      } catch (e) { u.failed = true; u.msg = '네트워크 오류 — 연결 후 다시 시도하세요.'; this.changed(u); }
    };
    if (Saver.ctx) await Saver.exclusive(exec); else await exec();
  },
  retry(uid) { const u = this.list.find(x => x.uid === +uid); if (u) this.run(u); },
  dismiss(uid) { this.list = this.list.filter(x => x.uid !== +uid); this.changed(null); },
  changed(u) { if (this.onChange) this.onChange(u); },
  html(itemId, kind) {
    return this.list.filter(u => u.itemId === itemId && u.kind === kind).map(u => `<div class="upl-row ${u.failed ? 'failed' : ''}" data-uid="${u.uid}">
      <span class="grow">${esc(u.name)} — ${u.failed ? esc(u.msg) : '업로드 중 ' + Math.round(u.progress * 100) + '%'}</span>
      ${u.failed ? `${u.fatal ? '' : `<button class="btn sm" type="button" data-act="upl-retry" data-uid="${u.uid}">다시 시도</button>`}<button class="btn sm" type="button" data-act="upl-dismiss" data-uid="${u.uid}">닫기</button>` : `<span class="bar"><i data-w="${Math.round(u.progress * 100)}"></i></span>`}</div>`).join('');
  }
};

/* ---------- 보고서 A4 미리보기 축소 (아티팩트 fitReport) ---------- */
function fitReport(stage) {
  if (!stage) return;
  const sc = $('.a4-scale', stage); if (!sc) return;
  sc.style.transform = ''; sc.style.width = ''; stage.style.height = '';
  const a4 = $('.a4', sc); const avail = stage.clientWidth - 28; const w = a4.offsetWidth;
  const s = Math.min(1, avail / w);
  if (s < 1) { sc.style.width = w + 'px'; sc.style.transform = `scale(${s})`; stage.style.height = (a4.offsetHeight * s + 42) + 'px'; stage.style.overflow = 'hidden'; }
  else stage.style.overflow = '';
}
// CSP(인라인 style 금지)를 지키기 위해 data-w(%) 속성으로 너비 지정
function applyWidths(root) { $$('[data-w]', root || document).forEach(el => { el.style.width = el.dataset.w + '%'; }); }

/* ---------- 액션바 ---------- */
function setActionBar(html) {
  const ab = $('#actionbar'), main = $('#main');
  if (!ab) return;
  if (!html) { ab.classList.add('hidden'); main.classList.remove('has-action'); return; }
  ab.innerHTML = html; ab.classList.remove('hidden'); main.classList.add('has-action');
}

/* ---------- 신규 점검 / 점검 작성 메뉴 ---------- */
async function startNewInspection() {
  const r = await apiOk('POST', '/api/inspections', {});
  if (r) location.href = `/inspections/${encodeURIComponent(r.data.id)}/info`;
}
async function openInspectNav() {
  let r;
  try { r = await api('GET', '/api/inspections/drafts'); } catch (e) { toast('서버에 연결할 수 없습니다.', 'err'); return; }
  const ds = (r.ok && r.data.items) || [];
  if (!ds.length) return startNewInspection();
  const v = await modal({
    title: '점검 작성', html: `작성 중인 점검이 ${ds.length}건 있습니다.<ul class="list mt8">${ds.map(d => `<li><button class="row-btn" type="button" data-pick="${esc(d.id)}"><div class="grow"><div class="main-t">${esc(d.info.place || '(점검 장소 미입력)')} ${d.status === 'rejected' ? '<span class="chip ng">반려</span>' : ''}</div><div class="meta">${esc(d.info.insp_type || '유형 미선택')} · ${fmtDT(d.updated_at)} 저장 · 진행률 ${d.composed ? fmtPct(d.counts.progress) : '체크리스트 미구성'}</div></div>›</button></li>`).join('')}</ul>`,
    buttons: [{ label: '취소', value: null }, { label: '＋ 신규 점검 시작', cls: 'primary', value: 'new' }],
    onOpen: (m, close) => $$('[data-pick]', m).forEach(b => b.addEventListener('click', () => close('d:' + b.dataset.pick)))
  });
  if (v === 'new') startNewInspection();
  else if (v && v.startsWith('d:')) location.href = '/inspections/' + encodeURIComponent(v.slice(2));
}

/* ---------- 위험 경고 배너 (위험도 '상' 부적합 중 조치 미완료) ---------- */
function updateBanner(n, link) {
  const b = $('#dangerBanner'); if (!b) return;
  if (!n) { b.classList.add('hidden'); return; }
  b.classList.remove('hidden');
  b.innerHTML = `<b>⚠ 위험도 '상' 부적합 ${n}건</b><span class="grow">즉시 해당 작업을 중지하고 현장 안전을 확보한 뒤, 내부 안전관리 절차에 따라 관리자에게 보고하세요.</span>${link ? `<a class="btn" href="${esc(link)}">확인</a>` : '<button class="btn" type="button" data-act="show-high">부적합 항목 보기</button>'}`;
}

/* ---------- 공통 이벤트 ---------- */
document.addEventListener('click', e => {
  const img = e.target.closest('img.zoom'); if (img) { lightbox(img.dataset.full || img.src); return; }
  const nav = e.target.closest('[data-act="inspect-nav"]'); if (nav) { e.preventDefault(); openInspectNav(); return; }
  const nb = e.target.closest('[data-act="new-insp"]'); if (nb) { e.preventDefault(); startNewInspection(); return; }
  const rs = e.target.closest('[data-act="retry-save"]'); if (rs) { Saver.retryOutbox(); Saver.flush(); return; }
  const ur = e.target.closest('[data-act="upl-retry"]'); if (ur) { Uploads.retry(ur.dataset.uid); return; }
  const ud = e.target.closest('[data-act="upl-dismiss"]'); if (ud) { Uploads.dismiss(ud.dataset.uid); return; }
});
// data-confirm 속성이 있는 폼은 커스텀 모달로 확인 후 제출
document.addEventListener('submit', async e => {
  const f = e.target;
  if (!f.dataset || f.dataset.confirm === undefined || f.dataset.confirmed) return;
  e.preventDefault();
  const ok = await confirmBox('확인', esc(f.dataset.confirm).replace(/\n/g, '<br>'), '계속');
  if (!ok) return;
  if (Saver.ctx) await Saver.idle();
  f.dataset.confirmed = '1'; f.submit();
});
window.addEventListener('resize', () => fitReport($('#rptStage')));
applyWidths();
if (new URLSearchParams(location.search).get('inspect') === '1' && location.pathname === '/') {
  history.replaceState(null, '', '/'); setTimeout(openInspectNav, 50);
}
