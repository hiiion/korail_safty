'use strict';
/* 부적합 관리 (아티팩트 renderNgMgmt 이전) — 확정 이후에도 개선조치 수정 가능, 변경은 서버에서 이력 기록 */
(function () {
  const F = { status: '', risk: '', q: '', overdue: '', repeat: '' };
  let D = null; let timer = null;
  const params = new URLSearchParams(location.search);
  ['status', 'risk', 'overdue', 'repeat'].forEach(k => { if (params.get(k)) F[k] = params.get(k); });
  $$('[data-nf]').forEach(el => { const k = el.dataset.nf; if (el.type === 'checkbox') el.checked = F[k] === '1'; else el.value = F[k]; });

  function photos(ids, name, editable) {
    if (!ids.length) return '';
    return `<div class="photos">${ids.map((id, i) => `<div class="ph"><img class="zoom" src="${thumbUrl(id)}" data-full="${photoUrl(id)}" alt="${name} 사진 ${i + 1}" loading="lazy">${editable ? `<button type="button" class="x" data-act="ph-del" data-photo="${id}" aria-label="사진 삭제">✕</button>` : ''}</div>`).join('')}</div>`;
  }
  function card(x) {
    const g = x.ng, si = stIdx(g.status), can = x.can_action;
    return `<div class="ngc ${si === 2 ? 'done' : si === 1 ? 'inprog' : ''}" data-item="${x.item_id}">
      <div class="hd"><span class="risk ${esc(g.risk)}">위험도 ${RISK[g.risk] || '-'}</span><span class="st s${si}">${ST[g.status]}</span>${x.overdue ? '<span class="chip ng">⏰ 기한 초과</span>' : ''}${x.repeat ? '<span class="chip warn">🔁 반복 지적</span>' : ''}<span class="chip">${esc(x.report_no || x.status_label)}</span></div>
      <div class="ttl">${esc(x.name)}</div>
      <dl class="kv"><dt>점검</dt><dd>${esc(x.date)} · ${esc(x.place)} · ${esc(x.cat)}</dd><dt>부적합 내용</dt><dd>${esc(g.content)}</dd><dt>발생 원인</dt><dd>${esc(g.cause)}</dd><dt>개선조치</dt><dd>${esc(g.action)}</dd><dt>담당자</dt><dd>${esc(g.owner)}</dd><dt>조치 예정일</dt><dd>${esc(g.due)}</dd>${g.done_date && g.status === 'done' ? `<dt>조치 완료일</dt><dd>${esc(g.done_date)}</dd>` : ''}</dl>
      ${can ? `<div class="field"><label class="f">조치 상태 변경</label><div class="seg">${ST_ORDER.map(s => `<button type="button" data-act="ng-status" data-v="${s}" class="${g.status === s ? 'on' : ''}">${ST[s]}</button>`).join('')}</div></div>` : ''}
      <div class="compare"><div><h5>개선 전</h5>${photos(x.before, '개선 전', false) || '<p class="hint">사진 없음</p>'}</div>
        <div><h5>개선 후</h5>${photos(x.after, '개선 후', can) || '<p class="hint">사진 없음</p>'}${Uploads.html(x.item_id, 'action')}${can ? `<div class="ext"><button class="btn sm" type="button" data-act="ph-add" data-cam="1">📷 촬영</button><button class="btn sm" type="button" data-act="ph-add">🖼 갤러리</button></div>` : ''}</div></div>
      <div class="ext">${can ? '<button class="btn sm outline" type="button" data-act="ng-edit">✏️ 조치 내용 수정</button>' : ''}<a class="btn sm" href="/inspections/${encodeURIComponent(x.insp_id)}/report?mode=latest">보고서 보기 ›</a></div>
    </div>`;
  }
  async function load() {
    const p = new URLSearchParams(); Object.entries(F).forEach(([k, v]) => { if (v) p.set(k, v); });
    let r;
    try { r = await api('GET', '/api/ng?' + p.toString()); } catch (e) { $('#ngList').innerHTML = '<div class="notice danger">서버에 연결할 수 없습니다.</div>'; return; }
    if (!r.ok) { $('#ngList').innerHTML = `<div class="notice danger">${esc(errMsg(r))}</div>`; return; }
    D = r.data; render();
  }
  function render() {
    const s = D.status;
    $('#ngKpis').innerHTML = `<div class="kpi ng"><div class="lab">미조치</div><div class="val">${s.todo}</div></div><div class="kpi warn"><div class="lab">조치 중</div><div class="val">${s.in_progress}</div><div class="foot">미완료 합계 ${D.undone}</div></div><div class="kpi ok"><div class="lab">조치 완료</div><div class="val">${s.done}</div><div class="foot">완료율 ${fmtPct(D.done_rate)}</div></div><div class="kpi od"><div class="lab">기한 초과</div><div class="val">${D.overdue}</div></div>`;
    $('#nfCount').textContent = D.items.length + '건 표시';
    $('#ngList').innerHTML = D.items.length ? D.items.map(card).join('') : '<div class="empty card"><span class="ic">🔍</span>조건에 해당하는 부적합 사항이 없습니다.</div>';
    applyWidths($('#ngList'));
  }
  const find = el => { const c = el.closest('[data-item]'); return c && D.items.find(x => x.item_id === +c.dataset.item); };
  async function patch(x, body, msg) {
    const r = await apiOk('PATCH', `/api/items/${x.item_id}/action`, body);
    if (r) { if (r.data.auto_done_date) toast('조치 완료일을 오늘 날짜로 입력했습니다.'); toast(msg, 'ok'); await load(); }
  }
  Uploads.onChange = () => { if (D) render(); };

  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const x = find(b);
    const act = b.dataset.act;
    if (act === 'ng-status' && x) {
      const v = b.dataset.v; if (x.ng.status === v) return;
      if (v === 'done' && !x.after.length && !(await confirmBox('조치 완료 처리', '개선 후 사진이 등록되지 않았습니다. 그래도 조치 완료로 변경하시겠습니까?', '완료 처리'))) return;
      patch(x, { status: v }, `조치 상태를 '${ST[v]}'(으)로 변경했습니다.`);
    }
    if (act === 'ng-edit' && x) {
      const g = x.ng;
      const v = await modal({ title: '개선조치 내용 수정', html: `<div class="field"><label class="f" for="e-action">개선조치 내용</label><textarea class="inp" id="e-action" rows="3">${esc(g.action)}</textarea></div><div class="grid2"><div class="field"><label class="f" for="e-owner">조치 담당자</label><input class="inp" id="e-owner" value="${esc(g.owner)}"></div><div class="field"><label class="f" for="e-due">조치 예정일</label><input type="date" class="inp" id="e-due" value="${esc(g.due)}"></div></div><div class="err-msg hidden" id="e-err"></div><p class="hint">변경 내용은 이력으로 기록되며, 최초 보고서는 변경되지 않습니다.</p>`,
        buttons: [{ label: '취소', value: null }, { label: '저장', cls: 'primary', onClick: m => { const a = $('#e-action', m).value.trim(), o = $('#e-owner', m).value.trim(), d = $('#e-due', m).value; if (!a || !o || !d) { const er = $('#e-err', m); er.textContent = '모든 항목을 입력하세요.'; er.classList.remove('hidden'); return false; } return { action: a, owner: o, due: d }; } }] });
      if (v) patch(x, v, '개선조치 내용을 수정했습니다.');
    }
    if (act === 'ph-add' && x) {
      const files = await pickFiles(!!b.dataset.cam); if (!files.length) return;
      if (x.after.length + files.length > 10) { toast('개선 후 사진은 항목당 최대 10장까지 첨부할 수 있습니다.', 'err'); return; }
      await Uploads.add(files, x.item_id, 'action', async () => { toast('사진을 첨부했습니다.', 'ok'); await load(); });
    }
    if (act === 'ph-del') {
      if (!(await confirmBox('사진 삭제', '선택한 사진을 삭제하시겠습니까?', '삭제', true))) return;
      const r = await apiOk('DELETE', '/api/photos/' + b.dataset.photo, {});
      if (r) { toast('사진을 삭제했습니다.'); load(); }
    }
  });
  document.addEventListener('input', e => {
    const t = e.target; if (t.dataset.nf === undefined) return;
    F[t.dataset.nf] = t.type === 'checkbox' ? (t.checked ? '1' : '') : t.value;
    clearTimeout(timer); timer = setTimeout(load, t.dataset.nf === 'q' ? 350 : 0);
  });
  load();
})();
