'use strict';
/* =========================================================
   안전점검 작성: ① 기본정보 → ② 항목 구성 → ③ 점검 수행  (④ 보고서 검토는 report.js)
   렌더링은 참고 아티팩트(step1HTML·step2HTML·itemHTML 등)를 재사용하고,
   저장은 서버 API(자동저장 Saver + 오프라인 대기열)로 처리한다.
   ========================================================= */
(function () {
  const pid = BOOT.pid, C = BOOT.consts;
  const base = '/inspections/' + encodeURIComponent(pid);
  let cur = null, step = BOOT.step;
  const S = { etcOpen: new Set(), open: new Set(), noteOpen: new Set(), filter: 'all', showInvalid: false, showInvalidInfo: false, lastJump: -1, sel: null };
  const root = $('#inspect');

  /* ---------- 도메인 (서버 services/judgment.py와 같은 규칙) ---------- */
  const ngMissing = it => NG_REQ.filter(([k]) => !String((it.ng || {})[k] || '').trim()).map(x => x[0]);
  function isValid(it) {
    if (!it || !it.result) return false;
    if (it.result === 'ok') return true;
    if (it.result === 'na') return !!String(it.na_reason || '').trim();
    return ngMissing(it).length === 0;
  }
  function itemState(it) {
    if (!it.result) return { cls: 'none', label: '미점검' };
    if (!isValid(it)) return { cls: 'warn', label: '입력 미완료' };
    return { cls: it.result === 'na' ? 'none' : it.result, label: RES_LABEL[it.result] };
  }
  const pct = (a, b) => (b > 0 ? Math.round((a / b) * 1000) / 10 : null);
  function counts() {
    const c = { total: 0, valid: 0, ok: 0, ng: 0, na: 0, none: 0, incomplete: 0 };
    allItems().forEach(({ it }) => { c.total++; if (!it.result) c.none++; else c[it.result]++; if (isValid(it)) c.valid++; else if (it.result) c.incomplete++; });
    c.progress = pct(c.valid, c.total); c.rate = pct(c.ok, c.ok + c.ng);
    return c;
  }
  const allItems = () => { const a = []; cur.categories.forEach(c => c.items.forEach(it => a.push({ it, cat: c }))); return a; };
  const findItem = id => allItems().find(x => x.it.id === +id) || null;
  const itemNo = id => { let o = ''; cur.categories.forEach((c, ci) => c.items.forEach((it, ii) => { if (it.id === +id) o = `${ci + 1}-${ii + 1}`; })); return o; };
  const isOverdue = g => g && g.status !== 'done' && g.due && g.due < cur.today;
  function infoMissing(i) {
    const m = []; const need = (k, l) => { if (!String(i[k] || '').trim()) m.push([k, l]); };
    need('inspector', '점검자 성명'); need('dept', '소속 부서'); need('place', '점검 장소'); need('date', '점검 일시'); need('insp_type', '점검 유형');
    need('target', '점검 대상'); if (i.target === '기타') need('target_etc', '점검 대상(직접 입력)');
    need('zone', '작업구역'); if (i.zone === '기타') need('zone_etc', '작업구역(직접 입력)');
    need('work_type', '작업 유형'); if (i.work_type === '기타') need('work_type_etc', '작업 유형(직접 입력)');
    if (i.target === '철도차량') { need('vehicle_type', '차량 종류'); need('vehicle_no', '차량번호'); }
    if (i.target === '정비설비') { need('equip_name', '설비명'); need('equip_no', '설비 관리번호'); }
    return m;
  }
  const labelOf = (k) => (cur.info[k] === '기타' ? (cur.info[k + '_etc'] || '기타') : (cur.info[k] || ''));

  /* ---------- 최근 입력값 (개인 편의: localStorage) ---------- */
  const LS = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } } };
  function rememberRecent() {
    const r = LS.get('srsi_recent', { inspector: [], dept: [], place: [] });
    ['inspector', 'dept', 'place'].forEach(k => { const v = String(cur.info[k] || '').trim(); if (!v) return; r[k] = [v, ...(r[k] || []).filter(x => x !== v)].slice(0, 10); });
    LS.set('srsi_recent', r);
  }
  const recentList = k => (LS.get('srsi_recent', {})[k] || []).slice(0, 20);

  /* ---------- 불러오기 ---------- */
  async function load() {
    let r;
    try { r = await api('GET', '/api/inspections/' + encodeURIComponent(pid)); }
    catch (e) { root.innerHTML = '<div class="notice danger">서버에 연결할 수 없습니다. 연결을 확인한 뒤 새로고침하세요.</div>'; return; }
    if (!r.ok) { root.innerHTML = `<div class="notice danger">${esc(errMsg(r))}</div>`; return; }
    cur = r.data;
    if (!cur.perms.edit) { location.replace(base + '/report'); return; }
    Saver.init({ pid, getVersion: () => cur.version, setVersion: v => { cur.version = v; }, onSaved, onError });
    Saver.lastSaved = cur.updated_at; Saver.render();
    if (cur.categories[0]) S.open.add(cur.categories[0].id);
    if (step === 3 && (!cur.composed || cur.needs_recompose)) step = 2;
    if (step === 2 && infoMissing(cur.info).length) { step = 1; S.showInvalidInfo = true; }
    render();
    if (location.hash === '#incomplete') setTimeout(() => complete(true), 80);
  }
  function onSaved(op, r) {
    const d = r.data || {};
    if (d.needs_recompose != null) cur.needs_recompose = d.needs_recompose;
    if (d.item && d.item.change_logs) { const f = findItem(d.item.id); if (f) { f.it.change_logs = d.item.change_logs; refreshChlog(f.it); } }
    if (d.auto_done_date && d.item) { const f = findItem(d.item.id); if (f) { f.it.ng.done_date = d.item.ng.done_date; } toast('조치 완료일을 오늘 날짜로 입력했습니다.'); }
  }
  function onError(op, r) {
    if (r.status === 409 && r.error && r.error.code === 'LOCKED') alertBox('수정 불가', esc(errMsg(r)) + '<br>화면을 새로고침합니다.').then(() => location.reload());
  }
  const saveInfo = (k, v, now) => Saver.queue('PATCH', '/api/inspections/' + encodeURIComponent(pid), { [k]: v }, now);
  const saveItem = (id, body, now) => Saver.queue('PATCH', `/api/items/${id}`, body, now);
  const saveNg = (id, body, now) => Saver.queue('PATCH', `/api/items/${id}/action`, body, now);

  /* ---------- 공통 화면 ---------- */
  function stepTabs() {
    const lab = ['① 기본정보', '② 항목 구성', '③ 점검 수행', '④ 보고서 검토'];
    const href = [base + '/info', base + '/compose', base + '/check', base + '/report'];
    return `<div class="steps" role="tablist">${lab.map((l, i) => {
      const n = i + 1; const dis = (n >= 3 && (!cur.composed || cur.needs_recompose));
      return `<a href="${href[i]}" data-act="goto-step" data-step="${n}" role="tab" class="${step === n ? 'on' : n < step ? 'done' : ''} ${dis ? 'dis' : ''}" aria-selected="${step === n}">${l}</a>`;
    }).join('')}</div>`;
  }
  function render() {
    let body = step === 1 ? step1HTML() : step === 2 ? step2HTML() : step3HTML();
    const rej = cur.status === 'rejected' ? `<div class="notice danger"><b>반려됨</b> — 사유: ${esc(cur.rejected_reason)}<br>내용을 수정한 뒤 보고서 검토 단계에서 다시 서명하고 제출하세요.</div>` : '';
    root.innerHTML = stepTabs() + rej + body;
    renderActionBar();
    if (step === 3) { $$('.acc').forEach(a => updateAccHead(+a.dataset.cat)); updateSummary(); applyFilter(false); }
    applyWidths(root);
    updateHighBanner();
  }
  function renderActionBar() {
    const b = {
      1: `<button class="btn" data-act="manual-save" type="button">💾 임시저장</button><button class="btn primary" data-act="to-step2" type="button">다음: 체크리스트 구성 ▶</button>`,
      2: `<button class="btn" data-act="goto-step" data-step="1" type="button">◀ 기본정보</button><button class="btn primary" data-act="confirm-compose" type="button">체크리스트 확정 · 점검 시작 ▶</button>`,
      3: `<button class="btn" data-act="manual-save" type="button">💾 임시저장</button><button class="btn outline" data-act="next-missing" type="button">다음 미점검 ▶</button><button class="btn primary" data-act="complete" type="button">✔ 점검 완료</button>`
    }[step];
    setActionBar(b);
  }
  function updateHighBanner() {
    if (!cur || !cur.composed) { updateBanner(0); return; }
    const n = allItems().filter(({ it }) => it.result === 'ng' && it.ng.risk === 'h' && it.ng.status !== 'done').length;
    updateBanner(step === 3 ? n : 0);
  }

  /* --- 1단계: 기본정보 --- */
  function step1HTML() {
    const i = cur.info; const missing = new Set(S.showInvalidInfo ? infoMissing(i).map(m => m[0]) : []);
    const inv = k => (missing.has(k) ? 'invalid' : '');
    const seg = (field, opts) => `<div class="seg ${inv(field)}" id="f-${field}" role="radiogroup">${opts.map(o => `<button type="button" role="radio" aria-checked="${i[field] === o}" class="${i[field] === o ? 'on' : ''}" data-act="seg" data-field="${field}" data-v="${esc(o)}">${esc(o)}</button>`).join('')}</div>`;
    const sel = (field, opts, ph) => `<select class="inp ${inv(field)}" id="f-${field}" data-struct="${field}"><option value="">${ph}</option>${opts.map(o => `<option ${i[field] === o ? 'selected' : ''} value="${esc(o)}">${esc(o)}</option>`).join('')}</select>`;
    const txt = (field, ph, list, max) => `<input class="inp ${inv(field)}" id="f-${field}" data-info="${field}" value="${esc(i[field])}" placeholder="${esc(ph)}" maxlength="${max || 60}" ${list ? `list="dl-${field}"` : ''} autocomplete="off">${list ? `<datalist id="dl-${field}">${recentList(field).map(v => `<option value="${esc(v)}">`).join('')}</datalist>` : ''}`;
    const combo = (field, groups, ph) => {
      const val = i[field] || ''; const all = groups.flatMap(g => g[1]); const inList = all.includes(val); const etc = !inList && (!!val || S.etcOpen.has(field));
      return `<select class="inp ${inv(field)}" id="f-${field}" data-combo="${field}"><option value="">${ph}</option>${groups.map(([g, opts]) => `<optgroup label="${esc(g)}">${opts.map(o => `<option value="${esc(o)}" ${val === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</optgroup>`).join('')}<option value="__etc" ${etc ? 'selected' : ''}>기타 (직접 입력)</option></select>${etc ? `<input class="inp mt8 ${inv(field)}" id="f-${field}-etc" data-info="${field}" value="${esc(val)}" placeholder="직접 입력" maxlength="60" autocomplete="off">` : ''}`;
    };
    const R = '<span class="req">*</span>';
    return `<div class="card"><h2>점검 기본정보</h2>
      <div class="grid3">
        <div class="field"><label class="f" for="f-inspector">점검자 성명${R}</label>${txt('inspector', '예: 홍길동', true)}</div>
        <div class="field"><label class="f" for="f-dept">소속 부서${R}</label>${combo('dept', C.DEPT_GROUPS, '소속 부서 선택')}</div>
        <div class="field"><label class="f" for="f-date">점검 일시${R} <span class="hint">(자동 입력)</span></label><input type="datetime-local" class="inp ${inv('date')}" id="f-date" data-dt="1" value="${esc(i.date && i.time ? i.date + 'T' + i.time : i.date ? i.date + 'T00:00' : '')}"></div>
      </div>
      <div class="field"><label class="f" for="f-place">점검 장소${R}</label>${txt('place', '예: 수도권 차량기지 검수고 2번선', true, 100)}</div>
      <div class="field"><label class="f">점검 유형${R}</label>${seg('insp_type', C.INSP_TYPES)}</div>
    </div>
    <div class="card"><h2>점검 대상 및 작업환경</h2>
      <div class="field"><label class="f">점검 대상${R}</label>${seg('target', C.TARGETS)}${i.target === '기타' ? `<div class="mt8">${txt('target_etc', '점검 대상 직접 입력')}</div>` : ''}</div>
      ${i.target === '철도차량' ? `<div class="grid2"><div class="field"><label class="f" for="f-vehicle_type">차량 종류${R}</label>${combo('vehicle_type', C.VEHICLE_GROUPS, '차량 종류 선택')}</div>
        <div class="field"><label class="f" for="f-vehicle_no">차량번호${R}</label>${txt('vehicle_no', '예: 140013', false, 30)}</div></div>` : ''}
      ${i.target === '정비설비' ? `<div class="grid2"><div class="field"><label class="f" for="f-equip_name">설비명${R}</label>${txt('equip_name', '예: 10톤 천장크레인')}</div><div class="field"><label class="f" for="f-equip_no">설비 관리번호${R}</label>${txt('equip_no', '예: EQ-CR-010', false, 30)}</div></div>` : ''}
      <div class="grid2">
        <div class="field"><label class="f" for="f-zone">작업구역${R}</label>${sel('zone', C.ZONES, '작업구역 선택')}${i.zone === '기타' ? `<div class="mt8">${txt('zone_etc', '작업구역 직접 입력')}</div>` : ''}</div>
        <div class="field"><label class="f" for="f-work_type">작업 유형${R}</label>${sel('work_type', C.WORKTYPES, '작업 유형 선택')}${i.work_type === '기타' ? `<div class="mt8">${txt('work_type_etc', '작업 유형 직접 입력')}</div>` : ''}</div>
      </div>
      <p class="hint m0">점검 대상·작업구역·작업 유형에 따라 다음 단계에서 체크리스트가 자동 추천됩니다.${cur.composed ? ' 체크리스트 구성 후 변경하면 체크리스트를 다시 구성해야 합니다.' : ''}</p>
    </div>`;
  }
  async function onStructChange(field, value) {
    if (cur.info[field] === value) return;
    if (cur.composed) {
      const hasResp = allItems().some(({ it }) => it.result || it.memo || it.photos.length);
      if (hasResp && !(await confirmBox('점검 조건 변경', '점검 대상·작업구역·작업 유형을 변경하면 체크리스트를 다시 구성해야 하며, <b>제외되는 분야의 기존 응답·사진·부적합 정보가 삭제될 수 있습니다.</b><br><br>변경하시겠습니까?', '변경', true))) { render(); return; }
      cur.needs_recompose = true;
    }
    cur.info[field] = value;
    const body = { [field]: value };
    if (field === 'target') {
      if (value !== '철도차량') { cur.info.vehicle_type = cur.info.vehicle_no = ''; }
      if (value !== '정비설비') { cur.info.equip_name = cur.info.equip_no = ''; }
    }
    Saver.queue('PATCH', '/api/inspections/' + encodeURIComponent(pid), body, true);
    render();
  }
  async function toStep2() {
    const miss = infoMissing(cur.info);
    if (miss.length) {
      S.showInvalidInfo = true; render();
      const el = $('#f-' + miss[0][0]); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      toast(`필수 입력 항목 ${miss.length}개가 비어 있습니다: ${miss.map(m => m[1]).join(', ')}`, 'err', 4500); return;
    }
    rememberRecent();
    await Saver.idle();
    location.href = base + '/compose';
  }

  /* --- 2단계: 체크리스트 구성 --- */
  function selection() {
    if (S.sel) return S.sel;
    const rec = new Set(cur.recommended);
    let sel;
    if (!cur.selected_cats) sel = new Set(rec);
    else if (cur.needs_recompose) {
      const custom = new Set(cur.template.filter(c => c.rule === 'custom').map(c => c.id));
      sel = new Set([...rec, ...cur.selected_cats.filter(id => custom.has(id))]);
    } else sel = new Set(cur.selected_cats);
    cur.template.forEach(c => { if (c.rule === 'common') sel.add(c.id); });
    return (S.sel = sel);
  }
  function step2HTML() {
    const rec = new Set(cur.recommended); const sel = selection();
    const total = cur.template.filter(c => sel.has(c.id)).reduce((a, c) => a + c.items.length, 0);
    return `<div class="notice">「${esc(labelOf('target'))} · ${esc(labelOf('zone'))} · ${esc(labelOf('work_type'))}」 조건에 맞춰 점검 분야를 <b>자동 추천</b>했습니다. 공통 필수 분야는 제외할 수 없으며, 필요한 분야를 추가로 선택할 수 있습니다. 세부 항목은 다음 단계에서 추가·수정·삭제할 수 있습니다.</div>
      ${cur.needs_recompose ? '<div class="notice warn">점검 조건이 변경되어 체크리스트를 다시 구성합니다. 제외되는 분야의 응답은 확정 시 삭제됩니다.</div>' : ''}
      <div class="card"><div class="sec-title"><h2>점검 분야 선택</h2><span class="chip">선택 ${sel.size}개 분야 · 약 ${total}개 항목</span></div>
      ${cur.template.map(c => {
        const locked = c.rule === 'common'; const on = sel.has(c.id) || locked; const isRec = rec.has(c.id);
        return `<div class="compose-cat ${on ? 'on' : ''}"><label class="compose-head"><input type="checkbox" data-compose="${c.id}" ${on ? 'checked' : ''} ${locked ? 'disabled' : ''}><span class="nm">${esc(c.name)}</span>
          ${locked ? '<span class="chip dark">공통 필수</span>' : isRec ? '<span class="chip ok">자동 추천</span>' : '<span class="chip none">선택</span>'}<span class="chip">${c.items.length}항목</span></label>
          <details><summary class="hint">항목 미리보기</summary><ol class="compose-items">${c.items.map(t => `<li>${esc(t)}</li>`).join('')}</ol></details></div>`;
      }).join('')}
      <p class="hint">※ 자동 구성은 점검 항목 추천을 위한 보조 기능입니다. 기본 체크리스트는 시연용 예시이며, 실제 운영 시 공식 안전점검 기준을 반영해야 합니다.</p></div>`;
  }
  async function composeToggle(el) {
    const id = +el.dataset.compose; const sel = selection();
    if (!el.checked && cur.recommended.includes(id)) {
      if (!(await confirmBox('자동 추천 분야 제외', '현재 점검 조건에 따라 <b>자동 추천된 분야</b>입니다. 제외하면 해당 분야의 안전 항목을 점검하지 않게 됩니다.<br>정말 제외하시겠습니까?', '제외', true))) { el.checked = true; return; }
    }
    if (el.checked) sel.add(id); else sel.delete(id);
    render();
  }
  async function confirmCompose() {
    const sel = selection();
    if (!sel.size) { toast('점검 분야를 1개 이상 선택하세요.', 'err'); return; }
    const removed = cur.categories.filter(c => c.template_category_id && cur.template.some(t => t.id === c.template_category_id) && !sel.has(c.template_category_id));
    const lost = removed.reduce((a, c) => a + c.items.filter(it => it.result || it.memo || it.photos.length).length, 0);
    if (lost && !(await confirmBox('응답 삭제 확인', `제외되는 분야(${removed.map(x => esc(x.name)).join(', ')})의 응답 <b>${lost}건</b>이 삭제됩니다. 계속하시겠습니까?`, '삭제 후 진행', true))) return;
    const r = await Saver.exclusive(() => api('POST', `/api/inspections/${encodeURIComponent(pid)}/compose`, { version: cur.version, category_ids: [...sel] }).catch(() => null));
    if (!r) { toast('서버에 연결할 수 없습니다.', 'err'); return; }
    if (!r.ok) { if (r.status === 409 && r.error.code === 'CONFLICT') conflictDialog(); else toast(errMsg(r), 'err', 4500); return; }
    location.href = base + '/check';
  }

  /* --- 3단계: 점검 수행 --- */
  function step3HTML() {
    return `<div class="sticky-sum"><div class="sum-box" id="sumBox"></div></div>
      <div class="notice">모든 항목의 초기 상태는 <b>미점검</b>이며, 각 항목을 직접 확인한 뒤 결과를 선택하세요. 일괄 적합 처리는 제공하지 않습니다. <b>진행률은 입력 완료 비율이며 실제 안전 적합 판정과는 별개</b>이고, 최종 안전 판단은 현장 담당자가 수행합니다.</div>
      <div class="filters" id="filters" role="group" aria-label="점검 항목 필터"></div>
      <div class="tools"><button class="btn sm outline" type="button" data-act="expand-all">▾ 모두 펼치기</button><button class="btn sm outline" type="button" data-act="collapse-all">▴ 모두 접기</button><button class="btn sm outline" type="button" data-act="next-missing">다음 미점검 ▶</button></div>
      <div id="filterEmpty" class="empty card hidden"><span class="ic">🔍</span>선택한 조건에 해당하는 점검 항목이 없습니다.</div>
      <div id="accs">${cur.categories.map((cat, ci) => `<section class="acc ${S.open.has(cat.id) ? 'open' : ''}" id="acc-${cat.id}" data-cat="${cat.id}">
        <button class="acc-head" type="button" data-act="acc-toggle" aria-expanded="${S.open.has(cat.id)}"><div class="acc-h grow"></div><span class="arrow" aria-hidden="true">▾</span></button>
        <div class="acc-body">${cat.items.map((it, ii) => itemHTML(it, `${ci + 1}-${ii + 1}`)).join('')}
        <div class="empty cat-empty hidden">이 분야에는 해당 항목이 없습니다.</div>
        <button class="btn sm ghost" type="button" data-act="add-item" data-cat="${cat.id}">＋ 이 분야에 항목 추가</button></div></section>`).join('')}</div>
      ${cur.deleted_log.length ? `<div class="card"><h3>삭제된 부적합 항목 (${cur.deleted_log.length})</h3><ul class="log">${cur.deleted_log.map(l => `<li>${fmtDT(l.at)} · ${esc(l.name)} — 사유: ${esc(l.reason)}</li>`).join('')}</ul></div>` : ''}`;
  }
  function photosHTML(arr, name) {
    if (!arr || !arr.length) return '';
    return `<div class="photos">${arr.map((pid_, i) => `<div class="ph"><img class="zoom" src="${thumbUrl(pid_)}" data-full="${photoUrl(pid_)}" alt="첨부 사진 ${i + 1}" loading="lazy"><button type="button" class="x" data-act="ph-del" data-arr="${name}" data-i="${i}" aria-label="사진 삭제">✕</button><button type="button" class="rp" data-act="ph-rep" data-arr="${name}" data-i="${i}">재등록</button></div>`).join('')}</div>`;
  }
  const uplBox = (id, kind) => `<div class="upl" data-upl="${id}-${kind}">${Uploads.html(id, kind)}</div>`;
  function chlogHTML(it) {
    const l = it.change_logs || [];
    return l.length ? `<ul class="chlog">${l.map(x => `<li>${fmtDT(x.at)} 부적합 → ${esc(RES_LABEL[x.to] || '미점검')} · 사유: ${esc(x.reason)}</li>`).join('')}</ul>` : '';
  }
  function itemHTML(it, no) {
    const st = itemState(it); const missing = S.showInvalid && !isValid(it);
    const hist = cur.history[it.id] || [];
    const inv = cond => (S.showInvalid && cond ? 'invalid' : '');
    let sub = '';
    if (it.result === 'na') sub += `<div class="item-sub field"><label class="f" for="na-${it.id}">해당 없음 사유<span class="req">*</span></label><input class="inp ${inv(!String(it.na_reason || '').trim())}" id="na-${it.id}" data-f="na_reason" value="${esc(it.na_reason)}" placeholder="예: 해당 설비 없음" maxlength="300"></div>`;
    if (it.result === 'ng') {
      const g = it.ng; const ms = new Set(S.showInvalid ? ngMissing(it) : []);
      const ta = (k, l, ph) => `<div class="field"><label class="f" for="ng-${k}-${it.id}">${l}<span class="req">*</span></label><textarea class="inp ${ms.has(k) ? 'invalid' : ''}" id="ng-${k}-${it.id}" data-ng="${k}" rows="2" placeholder="${esc(ph)}">${esc(g[k])}</textarea></div>`;
      sub += `<div class="ng-panel"><h4>⚠️ 부적합 세부 정보</h4>
        ${ta('content', '부적합 내용', '확인된 부적합 상태를 구체적으로 입력')}${ta('cause', '발생 원인', '원인을 입력')}
        <div class="field"><label class="f">위험도 (담당자 판단)<span class="req">*</span></label><div class="seg ${ms.has('risk') ? 'invalid' : ''}">${Object.entries(RISK).map(([k, v]) => `<button type="button" data-act="ngseg" data-k="risk" data-v="${k}" class="risk-${k} ${g.risk === k ? 'on' : ''}">${v}</button>`).join('')}</div>
          ${g.risk === 'h' ? '<p class="err-msg">즉시 해당 작업을 중지하고 현장 안전을 확보한 뒤, 내부 안전관리 절차에 따라 관리자에게 보고하세요.</p>' : ''}</div>
        ${ta('action', '개선조치 내용', '개선조치 계획을 입력')}
        <div class="grid2"><div class="field"><label class="f" for="ng-owner-${it.id}">조치 담당자<span class="req">*</span></label><input class="inp ${ms.has('owner') ? 'invalid' : ''}" id="ng-owner-${it.id}" data-ng="owner" value="${esc(g.owner)}" placeholder="담당자 성명" maxlength="60"></div>
        <div class="field"><label class="f" for="ng-due-${it.id}">조치 예정일<span class="req">*</span></label><input type="date" class="inp ${ms.has('due') ? 'invalid' : ''}" id="ng-due-${it.id}" data-ng="due" value="${esc(g.due)}"></div></div>
        <div class="field"><label class="f">조치 상태</label><div class="seg">${ST_ORDER.map(s => `<button type="button" data-act="ngseg" data-k="status" data-v="${s}" class="${g.status === s ? 'on' : ''}">${ST[s]}</button>`).join('')}</div>${isOverdue(g) ? '<p class="err-msg">⏰ 조치 예정일이 지났습니다 (기한 초과)</p>' : ''}</div>
        <div class="compare"><div><h5>개선 전 사진</h5>${photosHTML(it.before, 'before')}${uplBox(it.id, 'before')}<div class="ext"><button class="btn sm" type="button" data-act="ph-add" data-arr="before" data-cam="1" aria-label="개선 전 사진 촬영">📷</button><button class="btn sm" type="button" data-act="ph-add" data-arr="before" aria-label="개선 전 사진 갤러리">🖼</button></div></div>
        <div><h5>개선 후 사진</h5>${photosHTML(it.after, 'after')}${uplBox(it.id, 'action')}<div class="ext"><button class="btn sm" type="button" data-act="ph-add" data-arr="after" data-cam="1" aria-label="개선 후 사진 촬영">📷</button><button class="btn sm" type="button" data-act="ph-add" data-arr="after" aria-label="개선 후 사진 갤러리">🖼</button></div></div></div>
      </div>`;
    }
    const noteOpen = S.noteOpen.has(it.id) || !!it.memo;
    return `<div class="item ${it.result ? 'r-' + it.result : 'r-none'} ${missing ? 'missing' : ''}" id="it-${it.id}" data-item="${it.id}" data-res="${it.result || 'none'}">
      <div class="item-top"><span class="item-no">${no}</span><div class="item-text">${esc(it.name)}
        <div class="chips mt8"><span class="item-state chip ${st.cls}">${st.label}</span>${hist.length ? `<button type="button" class="history-badge" data-act="item-history">과거 부적합 ${hist.length}회 ›</button>` : ''}${it.is_custom ? '<span class="chip none">추가 항목</span>' : ''}</div></div>
        <button class="item-menu" type="button" data-act="item-menu" aria-label="항목 메뉴">⋮</button></div>
      <div class="res" role="radiogroup" aria-label="점검 결과">
        <button type="button" role="radio" aria-checked="${it.result === 'ok'}" class="ok ${it.result === 'ok' ? 'on' : ''}" data-act="res" data-v="ok">✔ 적합</button>
        <button type="button" role="radio" aria-checked="${it.result === 'ng'}" class="ng ${it.result === 'ng' ? 'on' : ''}" data-act="res" data-v="ng">✖ 부적합</button>
        <button type="button" role="radio" aria-checked="${it.result === 'na'}" class="na ${it.result === 'na' ? 'on' : ''}" data-act="res" data-v="na">− 해당 없음</button></div>
      <div class="chl">${chlogHTML(it)}</div>
      ${sub}
      <div class="ext"><button class="btn sm" type="button" data-act="ph-add" data-arr="photos" data-cam="1">📷 촬영</button><button class="btn sm" type="button" data-act="ph-add" data-arr="photos">🖼 갤러리</button><button class="btn sm" type="button" data-act="note-toggle">📝 특이사항${it.memo ? ' ●' : ''}</button></div>
      ${photosHTML(it.photos, 'photos')}${uplBox(it.id, 'finding')}
      ${noteOpen ? `<div class="item-sub"><label class="f" for="note-${it.id}">특이사항 · 추가 의견</label><textarea class="inp" id="note-${it.id}" data-f="memo" rows="2" placeholder="특이사항이나 추가 의견을 입력">${esc(it.memo)}</textarea></div>` : ''}
    </div>`;
  }
  function rerenderItem(id) {
    const el = $('#it-' + id); const f = findItem(id); if (!el || !f) return;
    const tmp = document.createElement('div'); tmp.innerHTML = itemHTML(f.it, itemNo(id)); const n = tmp.firstElementChild;
    el.replaceWith(n); applyWidths(n); updateAccHead(f.cat.id); updateSummary(); updateHighBanner();
  }
  function refreshChlog(it) { const el = $(`#it-${it.id} .chl`); if (el) el.innerHTML = chlogHTML(it); }
  function refreshItemChrome(id) {
    const el = $('#it-' + id); const f = findItem(id); if (!el || !f) return; const st = itemState(f.it);
    el.className = `item ${f.it.result ? 'r-' + f.it.result : 'r-none'} ${S.showInvalid && !isValid(f.it) ? 'missing' : ''}`;
    const s = $('.item-state', el); s.className = 'item-state chip ' + st.cls; s.textContent = st.label;
    updateAccHead(f.cat.id);
  }
  function updateAccHead(catId) {
    const cat = cur.categories.find(c => c.id === catId); const el = $('#acc-' + catId); if (!cat || !el) return;
    let done = 0, ng = 0; cat.items.forEach(it => { if (isValid(it)) done++; if (it.result === 'ng') ng++; });
    const tot = cat.items.length; const left = tot - done;
    $('.acc-h', el).innerHTML = `<div class="row"><span class="nm">${esc(cat.name)}</span><span class="cnt">(${done}/${tot})</span>${tot && left === 0 ? '<span class="chip ok">✔ 완료</span>' : ''}</div>
      <div class="acc-badges">${ng ? `<span class="chip ng">부적합 ${ng}</span>` : ''}${left > 0 ? `<span class="chip none">남은 ${left}</span>` : ''}</div>
      <div class="mini"><i data-w="${tot ? (done / tot) * 100 : 0}"></i></div>`;
    applyWidths(el);
  }
  function updateSummary() {
    const box = $('#sumBox'); if (!box) return; const c = counts();
    box.innerHTML = `<div class="prog-line"><span>진행률</span><div class="prog" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${c.progress || 0}"><i data-w="${c.progress || 0}"></i></div><span>${c.valid}/${c.total} (${c.progress == null ? 0 : c.progress}%)</span></div>
      <div class="tally"><span class="t-ok">적합 ${c.ok}</span><span class="t-ng">부적합 ${c.ng}</span><span class="t-na">해당 없음 ${c.na}</span><span class="t-none">미점검 ${c.none}</span>${c.incomplete ? `<span class="chip warn">입력 미완료 ${c.incomplete}</span>` : ''}</div>
      <div class="jump" aria-label="분야 바로가기">${cur.categories.map(cat => { let d = 0; cat.items.forEach(it => { if (isValid(it)) d++; }); return `<button type="button" data-act="jump" data-cat="${cat.id}">${d === cat.items.length && d ? '✔ ' : ''}${esc(cat.name)} ${d}/${cat.items.length}</button>`; }).join('')}</div>`;
    applyWidths(box);
    const f = $('#filters'); if (f) {
      const opts = [['all', '전체', c.total], ['none', '미점검', c.none], ['ok', '적합', c.ok], ['ng', '부적합', c.ng], ['na', '해당 없음', c.na]];
      f.innerHTML = opts.map(([k, l, n]) => `<button type="button" data-act="filter" data-v="${k}" class="${S.filter === k ? 'on' : ''}" aria-pressed="${S.filter === k}">${l} ${n}</button>`).join('');
    }
  }
  function applyFilter(openMatches) {
    const f = S.filter; let any = 0;
    $$('.acc').forEach(acc => {
      let vis = 0;
      $$('.item', acc).forEach(el => { const x = findItem(el.dataset.item); const res = (x && x.it.result) || 'none'; const show = f === 'all' || res === f; el.classList.toggle('hidden', !show); if (show) vis++; });
      any += vis;
      acc.classList.toggle('hidden', f !== 'all' && vis === 0);
      $('.cat-empty', acc).classList.toggle('hidden', vis > 0 || f !== 'all');
      if (openMatches && f !== 'all' && vis) { acc.classList.add('open'); S.open.add(+acc.dataset.cat); }
    });
    const fe = $('#filterEmpty'); if (fe) fe.classList.toggle('hidden', any > 0);
  }
  function scrollToItem(id, catId) {
    if (S.filter !== 'all') { S.filter = 'all'; updateSummary(); applyFilter(false); }
    const acc = $('#acc-' + catId); if (acc && !acc.classList.contains('open')) { acc.classList.add('open'); S.open.add(catId); }
    const el = $('#it-' + id); if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
  }
  function nextMissing() {
    const all = allItems(); if (!all.length) return;
    for (let k = 1; k <= all.length; k++) {
      const idx = (S.lastJump + k) % all.length; const x = all[idx];
      if (!isValid(x.it)) { S.lastJump = idx; scrollToItem(x.it.id, x.cat.id); return; }
    }
    alertBox('입력 완료', '모든 점검 항목의 입력이 완료되었습니다.');
  }
  async function setResult(id, v) {
    const f = findItem(id); const it = f.it;
    if (it.result === v) return;
    const body = { result: v };
    if (it.result === 'ng') {
      const reason = await reasonBox('부적합 판정 변경', `「${esc(it.name)}」 항목의 <b>부적합</b> 판정을 <b>${RES_LABEL[v]}</b>(으)로 변경합니다.<br>변경 사유는 보고서와 감사로그에 기록됩니다. 입력한 부적합 세부정보는 보존되지만 보고서에서 제외됩니다.`, '변경', '예: 재확인 결과 이상 없음');
      if (!reason) return;
      body.reason = reason;
    }
    it.result = v;
    saveItem(id, body, !!body.reason);
    rerenderItem(id);
    const focusId = v === 'ng' ? '#ng-content-' + id : v === 'na' ? '#na-' + id : null;
    if (focusId) { const el = $(focusId); if (el && !el.value) setTimeout(() => el.focus({ preventScroll: true }), 50); }
  }
  /* 사진 */
  const ARR_KIND = { photos: 'finding', before: 'before', after: 'action' };
  const KIND_ARR = { finding: 'photos', before: 'before', action: 'after' };
  async function addPhotos(id, arr, camera) {
    const f = findItem(id); if (!f) return;
    const files = await pickFiles(camera); if (!files.length) return;
    if (f.it[arr].length + files.length > 10) { toast('사진은 종류별로 항목당 최대 10장까지 첨부할 수 있습니다.', 'err'); return; }
    await Uploads.add(files, f.it.id, ARR_KIND[arr], async r => { cur.version = r.data.version; Saver.lastSaved = r.server_time; f.it[arr].push(r.data.photo.id); rerenderItem(id); Saver.render(); });
  }
  async function deletePhoto(id, arr, i, silent) {
    const f = findItem(id); const photoId = f.it[arr][i];
    if (!silent && !(await confirmBox('사진 삭제', '선택한 사진을 삭제하시겠습니까?', '삭제', true))) return;
    const r = await Saver.exclusive(() => api('DELETE', '/api/photos/' + photoId, { version: cur.version }).catch(() => null));
    if (!r || !r.ok) { toast(r ? errMsg(r) : '서버에 연결할 수 없습니다.', 'err'); return; }
    cur.version = r.data.version; f.it[arr] = f.it[arr].filter(x => x !== photoId); rerenderItem(id);
    if (!silent) toast('사진을 삭제했습니다.');
  }
  async function replacePhoto(id, arr, i) {
    const f = findItem(id); const old = f.it[arr][i];
    const files = await pickFiles(false, false); if (!files.length) return;
    await Uploads.add([files[0]], f.it.id, ARR_KIND[arr], async r => {
      cur.version = r.data.version; f.it[arr].push(r.data.photo.id);
      await deletePhoto(id, arr, f.it[arr].indexOf(old), true); toast('사진을 재등록했습니다.', 'ok');
    });
  }
  Uploads.onChange = u => {
    if (!u) { $$('.upl').forEach(el => { const [id, kind] = el.dataset.upl.split('-'); el.innerHTML = Uploads.html(+id, kind); applyWidths(el); }); return; }
    const el = $(`[data-upl="${u.itemId}-${u.kind}"]`); if (el) { el.innerHTML = Uploads.html(u.itemId, u.kind); applyWidths(el); }
  };
  /* 항목 추가·수정·삭제 */
  const dupExists = (text, exceptId) => { const k = norm(text); return allItems().some(x => x.it.id !== exceptId && norm(x.it.name) === k); };
  async function addItemModal(catId) {
    const cat = cur.categories.find(c => c.id === catId);
    const tplOk = BOOT.admin && cat.template_category_id;
    const v = await modal({
      title: `항목 추가 · ${cat.name}`, html: `<label class="f" for="mi-text">점검 항목 내용</label><textarea class="inp" id="mi-text" rows="3" maxlength="200" placeholder="예: 작업대 고정 상태가 양호한가"></textarea><div class="err-msg hidden" id="mi-err"></div>
        ${tplOk ? `<label class="check-lbl"><input type="checkbox" id="mi-tpl">기본 템플릿에도 저장 (이후 신규 점검에 적용, 관리자)</label>` : ''}<p class="hint">${tplOk ? '체크하지 않으면 이번 점검에만 적용됩니다.' : '이번 점검에만 적용됩니다. 기본 템플릿 변경은 관리자에게 요청하세요.'}</p>`,
      buttons: [{ label: '취소', value: null }, { label: '추가', cls: 'primary', onClick: m => {
        const t = $('#mi-text', m).value.trim(); const e = $('#mi-err', m);
        if (!t) { e.textContent = '항목 내용을 입력하세요.'; e.classList.remove('hidden'); return false; }
        if (dupExists(t)) { e.textContent = '동일한 점검 항목이 이미 있습니다.'; e.classList.remove('hidden'); return false; }
        return { t, tpl: !!($('#mi-tpl', m) && $('#mi-tpl', m).checked) };
      } }]
    });
    if (!v) return;
    const r = await Saver.exclusive(() => api('POST', `/api/inspections/${encodeURIComponent(pid)}/categories/${catId}/items`, { version: cur.version, name: v.t, to_template: v.tpl }).catch(() => null));
    if (!r || !r.ok) { toast(r ? errMsg(r) : '서버에 연결할 수 없습니다.', 'err', 4500); return; }
    cur.version = r.data.version; cat.items.push(Object.assign({ change_logs: [] }, r.data.item)); S.open.add(catId); render();
    setTimeout(() => scrollToItem(r.data.item.id, catId), 50); toast('항목을 추가했습니다.', 'ok');
  }
  async function itemMenu(id) {
    const f = findItem(id); const hist = cur.history[f.it.id] || [];
    const v = await modal({ title: '점검 항목 관리', html: `<p class="m0"><b>${esc(f.it.name)}</b></p><p class="hint m0">${esc(f.cat.name)}</p>`,
      buttons: [{ label: '닫기', value: null }, ...(hist.length ? [{ label: `과거 이력(${hist.length})`, value: 'hist' }] : []), { label: '✏️ 수정', cls: 'outline', value: 'edit' }, { label: '🗑 삭제', cls: 'danger', value: 'del' }] });
    if (v === 'hist') showItemHistory(id);
    if (v === 'edit') editItemModal(id);
    if (v === 'del') deleteItem(id);
  }
  async function editItemModal(id) {
    const f = findItem(id);
    const v = await modal({ title: '항목 수정', html: `<label class="f" for="mi-text">점검 항목 내용</label><textarea class="inp" id="mi-text" rows="3" maxlength="200">${esc(f.it.name)}</textarea><div class="err-msg hidden" id="mi-err"></div><p class="hint">이번 점검에만 적용되며 과거 점검 기록과 기본 템플릿에는 영향을 주지 않습니다.</p>`,
      buttons: [{ label: '취소', value: null }, { label: '저장', cls: 'primary', onClick: m => {
        const t = $('#mi-text', m).value.trim(); const e = $('#mi-err', m);
        if (!t) { e.textContent = '항목 내용을 입력하세요.'; e.classList.remove('hidden'); return false; }
        if (dupExists(t, f.it.id)) { e.textContent = '동일한 점검 항목이 이미 있습니다.'; e.classList.remove('hidden'); return false; }
        return t;
      } }] });
    if (!v) return;
    f.it.name = v; saveItem(id, { name: v }, true); rerenderItem(id); toast('항목을 수정했습니다.', 'ok');
  }
  async function deleteItem(id) {
    const f = findItem(id); const body = { version: cur.version };
    if (f.it.result === 'ng') {
      const reason = await reasonBox('부적합 항목 삭제', `「${esc(f.it.name)}」은(는) <b>부적합</b> 항목입니다. 삭제하려면 사유가 필요하며, 삭제 이력은 보고서와 감사로그에 남습니다.`, '삭제');
      if (!reason) return; body.reason = reason;
    } else if (!(await confirmBox('항목 삭제', `「${esc(f.it.name)}」 항목을 이번 점검에서 삭제합니다. 입력한 응답·사진도 함께 삭제됩니다.<p class="hint">과거 점검 기록과 기본 템플릿에는 영향이 없습니다.</p>`, '삭제', true))) return;
    const r = await Saver.exclusive(() => { body.version = cur.version; return api('DELETE', `/api/items/${f.it.id}`, body).catch(() => null); });
    if (!r || !r.ok) { toast(r ? errMsg(r) : '서버에 연결할 수 없습니다.', 'err', 4500); return; }
    cur.version = r.data.version; f.cat.items = f.cat.items.filter(x => x.id !== f.it.id);
    if (body.reason) cur.deleted_log.push({ name: f.it.name, reason: body.reason, at: new Date().toISOString() });
    render(); toast('항목을 삭제했습니다.');
  }
  function showItemHistory(id) {
    const f = findItem(id); const list = cur.history[f.it.id] || [];
    const since = new Date(Date.now() - cur.repeat_days * 864e5).toISOString().slice(0, 10);
    const recent = list.filter(p => p.date >= since).length;
    const tbl = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>일자</th><th>관리번호</th><th>부적합 내용</th><th>위험도</th><th>개선조치</th><th>상태</th></tr></thead><tbody>${list.map(p => `<tr><td>${esc(p.date)}</td><td>${esc(p.report_no)}</td><td>${esc(p.content)}</td><td>${p.risk ? `<span class="risk ${p.risk}">${RISK[p.risk]}</span>` : '-'}</td><td>${esc(p.action)}</td><td><span class="st s${stIdx(p.status)}">${ST[p.status]}</span></td></tr>`).join('')}</tbody></table></div>`;
    modal({ title: '과거 부적합 이력', wide: true, html: `<p class="m0"><b>${esc(f.it.name)}</b></p><p class="hint">${esc(cur.info.place)} · 전체 ${list.length}회 · 최근 ${cur.repeat_days}일 ${recent}회${recent >= 1 ? ' — 이번 점검에서도 부적합이면 <b class="ng-text">반복 지적사항</b>으로 분류됩니다.' : ''}</p>${tbl}` });
  }
  /* 점검 완료 검증 → 보고서 검토 */
  async function complete(silent) {
    await Saver.idle();
    const info = infoMissing(cur.info);
    if (info.length) {
      await alertBox('필수 입력 누락', `기본정보 필수 항목 ${info.length}개가 비어 있어 점검을 완료할 수 없습니다.<br><b>${info.map(m => esc(m[1])).join(', ')}</b>`);
      location.href = base + '/info'; return;
    }
    const items = allItems(); const bad = items.filter(x => !isValid(x.it));
    if (!items.length) { alertBox('점검 완료 불가', '체크리스트에 점검 항목이 없습니다.'); return; }
    if (bad.length) {
      const none = bad.filter(x => !x.it.result).length, na = bad.filter(x => x.it.result === 'na').length, ng = bad.filter(x => x.it.result === 'ng').length;
      S.showInvalid = true; S.filter = 'all'; bad.forEach(x => S.open.add(x.cat.id)); render();
      if (!silent) await alertBox('점검 완료 불가', `입력이 완료되지 않은 항목이 <b>${bad.length}건</b> 있습니다.<ul>${none ? `<li>미점검 항목 ${none}건</li>` : ''}${na ? `<li>해당 없음 사유 미입력 ${na}건</li>` : ''}${ng ? `<li>부적합 세부정보 미입력 ${ng}건</li>` : ''}</ul>회색·빨간색으로 표시된 항목을 확인하세요. 첫 번째 누락 항목으로 이동합니다.`);
      S.lastJump = items.indexOf(bad[0]); scrollToItem(bad[0].it.id, bad[0].cat.id);
      return;
    }
    if (!cur.opinion_edited || !cur.opinion) {
      const r = await Saver.exclusive(() => api('POST', `/api/inspections/${encodeURIComponent(pid)}/opinion`, { version: cur.version }).catch(() => null));
      if (r && r.ok) cur.version = r.data.version;
      else if (r && r.status === 409 && r.error.code === 'CONFLICT') { conflictDialog(); return; }
    }
    location.href = base + '/report';
  }

  /* ---------- 이벤트 ---------- */
  const ACT = {
    'manual-save': async () => { await Saver.idle(); toast('임시저장되었습니다.', 'ok'); },
    'goto-step': async (el, e) => {
      e.preventDefault(); const n = +el.dataset.step; if (n === step) return;
      if (n >= 2 && step === 1 && infoMissing(cur.info).length) { toStep2(); return; }
      if (n === 3 && (!cur.composed || cur.needs_recompose)) { toast('체크리스트를 먼저 확정하세요.', 'warn'); return; }
      if (n === 4) { if (step !== 3) { await Saver.idle(); location.href = base + '/check#incomplete'; return; } complete(); return; }
      await Saver.idle(); location.href = [null, base + '/info', base + '/compose', base + '/check'][n];
    },
    seg: el => { const f = el.dataset.field, v = el.dataset.v; if (f === 'target') { onStructChange(f, v); return; } cur.info[f] = v; saveInfo(f, v); $$(`[data-field="${f}"]`).forEach(b => { b.classList.toggle('on', b.dataset.v === v); b.setAttribute('aria-checked', b.dataset.v === v); }); $('#f-' + f).classList.remove('invalid'); },
    'to-step2': () => toStep2(),
    'confirm-compose': () => confirmCompose(),
    'acc-toggle': el => { const acc = el.closest('.acc'); const id = +acc.dataset.cat; const o = acc.classList.toggle('open'); el.setAttribute('aria-expanded', o); if (o) S.open.add(id); else S.open.delete(id); },
    'expand-all': () => $$('.acc').forEach(a => { a.classList.add('open'); S.open.add(+a.dataset.cat); }),
    'collapse-all': () => $$('.acc').forEach(a => { a.classList.remove('open'); S.open.delete(+a.dataset.cat); }),
    jump: el => { const id = +el.dataset.cat; const acc = $('#acc-' + id); if (!acc) return; if (acc.classList.contains('hidden')) { S.filter = 'all'; updateSummary(); applyFilter(false); } acc.classList.add('open'); S.open.add(id); acc.scrollIntoView({ behavior: 'smooth', block: 'start' }); },
    filter: el => { S.filter = el.dataset.v; updateSummary(); applyFilter(true); },
    'show-high': () => { S.filter = 'ng'; updateSummary(); applyFilter(true); const first = $('.item.r-ng'); if (first) first.scrollIntoView({ behavior: 'smooth', block: 'start' }); },
    'next-missing': () => nextMissing(),
    res: el => setResult(+el.closest('[data-item]').dataset.item, el.dataset.v),
    ngseg: el => { const id = +el.closest('[data-item]').dataset.item; const f = findItem(id); const k = el.dataset.k, v = el.dataset.v; if (f.it.ng[k] === v) return; f.it.ng[k] = v; if (k === 'status' && v !== 'done') f.it.ng.done_date = ''; saveNg(id, { [k]: v }); rerenderItem(id); },
    'note-toggle': el => { const id = +el.closest('[data-item]').dataset.item; if (S.noteOpen.has(id)) S.noteOpen.delete(id); else S.noteOpen.add(id); rerenderItem(id); const t = $('#note-' + id); if (t) t.focus({ preventScroll: true }); },
    'ph-add': el => addPhotos(+el.closest('[data-item]').dataset.item, el.dataset.arr, !!el.dataset.cam),
    'ph-del': el => deletePhoto(+el.closest('[data-item]').dataset.item, el.dataset.arr, +el.dataset.i),
    'ph-rep': el => replacePhoto(+el.closest('[data-item]').dataset.item, el.dataset.arr, +el.dataset.i),
    'item-menu': el => itemMenu(+el.closest('[data-item]').dataset.item),
    'item-history': el => showItemHistory(+el.closest('[data-item]').dataset.item),
    'add-item': el => addItemModal(+el.dataset.cat),
    complete: () => complete(),
  };
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-act]'); if (!el || el.disabled || !cur) return;
    const h = ACT[el.dataset.act]; if (h) { if (el.tagName !== 'A' || el.dataset.act !== 'goto-step') e.preventDefault(); Promise.resolve(h(el, e)).catch(err => { console.error(err); toast('오류: ' + err.message, 'err'); }); }
  });
  document.addEventListener('input', e => {
    const t = e.target; if (!cur) return;
    if (t.dataset.info !== undefined) { const k = t.dataset.info; cur.info[k] = t.value; t.classList.remove('invalid'); saveInfo(k, t.value); return; }
    if (t.dataset.dt) { const [d, tm] = (t.value || '').split('T'); if (d) { cur.info.date = d; cur.info.time = (tm || '').slice(0, 5); Saver.queue('PATCH', '/api/inspections/' + encodeURIComponent(pid), { date: d, time: cur.info.time || '00:00' }); t.classList.remove('invalid'); } return; }
    const wrap = t.closest('[data-item]'); if (!wrap) return; const id = +wrap.dataset.item; const f = findItem(id); if (!f) return;
    if (t.dataset.f) { f.it[t.dataset.f] = t.value; saveItem(id, { [t.dataset.f]: t.value }); }
    else if (t.dataset.ng) { f.it.ng[t.dataset.ng] = t.value; saveNg(id, { [t.dataset.ng]: t.value }); }
    else return;
    if (t.value.trim()) t.classList.remove('invalid');
    refreshItemChrome(id); updateSummary();
  });
  document.addEventListener('change', e => {
    const t = e.target; if (!cur) return;
    if (t.dataset.struct) { onStructChange(t.dataset.struct, t.value); return; }
    if (t.dataset.combo) {
      const f = t.dataset.combo;
      if (t.value === '__etc') { S.etcOpen.add(f); cur.info[f] = ''; saveInfo(f, ''); render(); const x = $('#f-' + f + '-etc'); if (x) x.focus(); }
      else { S.etcOpen.delete(f); cur.info[f] = t.value; saveInfo(f, t.value); render(); }
      return;
    }
    if (t.dataset.compose) composeToggle(t);
    if (t.dataset.ng === 'due') { const id = +t.closest('[data-item]').dataset.item; rerenderItem(id); }
  });
  load();
})();
