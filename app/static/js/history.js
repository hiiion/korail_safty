'use strict';
/* 점검 이력: 검색·필터 + CSV (아티팩트 renderHistory 이전, 서버 검색) */
(function () {
  const KEY = 'srsi_hist_filter';
  let F = {}; let page = 1; let timer = null;
  try { F = JSON.parse(sessionStorage.getItem(KEY) || '{}') || {}; } catch (e) { F = {}; }
  $$('[data-hf]').forEach(el => { if (F[el.dataset.hf]) el.value = F[el.dataset.hf]; });

  const qs = extra => { const p = new URLSearchParams(); Object.entries(Object.assign({}, F, extra || {})).forEach(([k, v]) => { if (v) p.set(k, v); }); return p.toString(); };

  function row(i) {
    const c = i.counts;
    const href = `/inspections/${encodeURIComponent(i.id)}${i.status === 'draft' || i.status === 'rejected' ? '' : '/report'}`;
    const stCls = { confirmed: 'ok', submitted: 'warn', rejected: 'ng' }[i.status] || 'none';
    return `<li><a class="row-btn" href="${href}"><div class="grow"><div class="main-t">${esc(i.info.place || '(점검 장소 미입력)')} <span class="chip">${esc(i.info.insp_type || '-')}</span> <span class="chip ${stCls}">${esc(i.status_label)}</span></div>
      <div class="meta">${esc(i.info.date)} ${esc(i.info.time)} · ${esc(i.info.inspector)}(${esc(i.info.dept)}) · ${esc(i.info.target_label || '-')}${i.info.vehicle_no ? ' ' + esc(i.info.vehicle_type) + ' ' + esc(i.info.vehicle_no) : ''}${i.info.equip_name ? ' ' + esc(i.info.equip_name) : ''}</div>
      <div class="chips mt8">${i.composed ? `<span class="chip ok">적합 ${c.ok}</span>${c.ng ? `<span class="chip ng">부적합 ${c.ng}</span>` : ''}<span class="chip none">해당없음 ${c.na}</span>${c.none ? `<span class="chip none">미점검 ${c.none}</span>` : ''}` : '<span class="chip none">체크리스트 미구성</span>'}${i.undone ? `<span class="chip warn">미완료 조치 ${i.undone}</span>` : ''}${i.report_no ? `<span class="chip">${esc(i.report_no)}</span>` : ''}</div></div><span aria-hidden="true">›</span></a></li>`;
  }

  async function load() {
    try { sessionStorage.setItem(KEY, JSON.stringify(F)); } catch (e) { }
    let r;
    try { r = await api('GET', '/api/inspections?' + qs({ page })); } catch (e) { $('#histList').innerHTML = '<div class="notice danger">서버에 연결할 수 없습니다.</div>'; return; }
    if (!r.ok) { $('#histList').innerHTML = `<div class="notice danger">${esc(errMsg(r))}</div>`; return; }
    const d = r.data;
    $('#hfCount').textContent = d.total + '건';
    $('#histSub').textContent = `조회 가능한 점검 기록 · 검색 결과 ${d.total}건`;
    $('#histList').innerHTML = d.items.length ? `<ul class="list">${d.items.map(row).join('')}</ul>` : `<div class="empty"><span class="ic">🔍</span>${Object.values(F).some(Boolean) ? '검색 결과가 없습니다.' : '점검 기록이 없습니다.'}</div>`;
    $('#pager').innerHTML = d.pages > 1 ? `${d.page > 1 ? '<button class="btn sm" data-act="pg" data-d="-1" type="button">← 이전</button>' : ''}<span>${d.page} / ${d.pages}</span>${d.page < d.pages ? '<button class="btn sm" data-act="pg" data-d="1" type="button">다음 →</button>' : ''}` : '';
  }

  document.addEventListener('input', e => {
    const t = e.target; if (t.dataset.hf === undefined) return;
    F[t.dataset.hf] = t.value; page = 1;
    clearTimeout(timer); timer = setTimeout(load, t.tagName === 'SELECT' || t.type === 'date' ? 0 : 350);
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    if (b.dataset.act === 'hf-reset') { F = {}; page = 1; $$('[data-hf]').forEach(el => { el.value = ''; }); load(); }
    if (b.dataset.act === 'pg') { page += +b.dataset.d; load(); window.scrollTo(0, 0); }
    if (b.dataset.act === 'csv') { location.href = '/export/stats.csv?' + qs({ kind: b.dataset.kind }); toast('CSV 다운로드를 시작했습니다.', 'ok'); }
  });
  load();
})();
