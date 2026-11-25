'use strict';
/* 대시보드 (아티팩트 renderDashboard 이전 — 통계는 서버 /api/dashboard 집계) */
(function () {
  let D = null;
  $('#todayLbl').textContent = todayStr();

  function histRow(i) {
    const c = i.counts;
    return `<li><a class="row-btn" href="/inspections/${encodeURIComponent(i.id)}/report"><div class="grow"><div class="main-t">${esc(i.info.place)} <span class="chip">${esc(i.info.insp_type)}</span></div>
      <div class="meta">${esc(i.info.date)} ${esc(i.info.time)} · ${esc(i.info.inspector)}(${esc(i.info.dept)}) · ${esc(i.info.target_label)}${i.info.vehicle_no ? ' ' + esc(i.info.vehicle_type) + ' ' + esc(i.info.vehicle_no) : ''}${i.info.equip_name ? ' ' + esc(i.info.equip_name) : ''}</div>
      <div class="chips mt8"><span class="chip ok">적합 ${c.ok}</span>${c.ng ? `<span class="chip ng">부적합 ${c.ng}</span>` : ''}<span class="chip none">해당없음 ${c.na}</span>${i.undone ? `<span class="chip warn">미완료 조치 ${i.undone}</span>` : ''}<span class="chip">${esc(i.report_no || i.status_label)}</span></div></div><span aria-hidden="true">›</span></a></li>`;
  }

  async function load() {
    let r, dr;
    try { [r, dr] = await Promise.all([api('GET', '/api/dashboard'), api('GET', '/api/inspections/drafts')]); }
    catch (e) { $('#dash').innerHTML = '<div class="notice danger">서버에 연결할 수 없습니다. 연결을 확인한 뒤 새로고침하세요.</div>'; return; }
    if (!r.ok) { $('#dash').innerHTML = `<div class="notice danger">${esc(errMsg(r))}</div>`; return; }
    const drafts = (dr.ok && dr.data.items) || [];
    D = r.data; render(drafts);
    // 로그인 직후 1회: "이어서 작성" 안내 (아티팩트 enterApp과 동일)
    let shown = false; try { shown = sessionStorage.getItem('srsi_resume_shown') === '1'; sessionStorage.setItem('srsi_resume_shown', '1'); } catch (e) { shown = true; }
    if (!shown && drafts.length) {
      const d = drafts[0];
      const v = await modal({ title: '작성 중인 점검이 있습니다', html: `이전에 작성하던 점검을 이어서 작성하시겠습니까?<div class="card flat"><b>${esc(d.info.place || '(점검 장소 미입력)')}</b><br><span class="hint">${esc(d.info.inspector || '-')} · 최종 저장 ${fmtDT(d.updated_at)} · 진행률 ${d.composed ? fmtPct(d.counts.progress) : '체크리스트 미구성'}</span></div>${drafts.length > 1 ? `<p class="hint">그 외 작성 중 ${drafts.length - 1}건은 대시보드에서 확인할 수 있습니다.</p>` : ''}`,
        buttons: [{ label: '나중에', value: false }, { label: '이어서 작성', cls: 'primary', value: true }] });
      if (v) location.href = '/inspections/' + encodeURIComponent(d.id);
    }
  }

  function render(drafts) {
    const st = D.status, ngTotal = D.ng_total;
    $('#undoneBtn').textContent = `⚠️ 미완료 조치 ${D.undone}건`;
    const deg = n => (ngTotal ? (n / ngTotal) * 360 : 0);
    const d0 = deg(st.done), d1 = d0 + deg(st.in_progress);
    const maxC = Math.max(1, ...D.by_category.map(x => x[1]));
    const t = D.time;
    $('#dash').innerHTML = `
    ${drafts.length ? `<div class="card warnb"><div class="sec-title"><h2>📝 작성 중인 점검 (${drafts.length})</h2></div><ul class="list">${drafts.map(d => `<li><div class="row-btn"><div class="grow"><div class="main-t">${esc(d.info.place || '(점검 장소 미입력)')} · ${esc(d.info.insp_type || '유형 미선택')} ${d.status === 'rejected' ? '<span class="chip ng">반려</span>' : ''}</div><div class="meta">${esc(d.info.inspector || '-')} · 최종 저장 ${fmtDT(d.updated_at)} · 진행률 ${d.composed ? fmtPct(d.counts.progress) : '체크리스트 미구성'}</div></div>
      <a class="btn sm primary" href="/inspections/${encodeURIComponent(d.id)}">이어서 작성</a><button class="btn sm" data-act="del-draft" data-id="${esc(d.id)}" type="button" aria-label="작성 중 점검 삭제">삭제</button></div></li>`).join('')}</ul></div>` : ''}
    <div class="kpis">
      <div class="kpi"><div class="lab">전체 점검</div><div class="val">${D.total}<small>건</small></div><div class="foot">제출·확정 기준</div></div>
      <div class="kpi ok"><div class="lab">적합</div><div class="val">${D.ok}<small>항목</small></div><div class="foot">적합률 ${fmtPct(D.rate)}</div></div>
      <div class="kpi ng"><div class="lab">부적합</div><div class="val">${D.ng}<small>항목</small></div><div class="foot">해당 없음 ${D.na}항목</div></div>
      <div class="kpi warn"><div class="lab">미조치</div><div class="val">${st.todo}<small>건</small></div><div class="foot">조치 중 ${st.in_progress} · 미완료 ${D.undone} · 기한초과 ${D.overdue}</div></div>
    </div>
    <div class="dash-grid">
      <div class="card"><h2>개선조치 완료율</h2>
        <div class="donut-wrap"><div class="donut" id="donut" role="img" aria-label="개선조치 완료율 ${fmtPct(D.done_rate)}"><div class="c"><b>${D.done_rate == null ? '-' : D.done_rate + '%'}</b><span>${D.done_rate == null ? '산정 대상 없음' : '조치 완료'}</span></div></div>
        <ul class="legend"><li><i class="lg-ok"></i>조치 완료<b>${st.done}건</b></li><li><i class="lg-warn"></i>조치 중<b>${st.in_progress}건</b></li><li><i class="lg-ng"></i>미조치<b>${st.todo}건</b></li><li class="od"><i class="lg-od"></i>기한 초과<b>${D.overdue}건</b></li></ul></div>
        <p class="hint mt12 mb0">완료율 = 조치 완료 ÷ 전체 부적합(${ngTotal}건) × 100</p></div>
      <div class="card"><h2>분야별 부적합 건수</h2>${D.by_category.length ? D.by_category.map(([n, v]) => `<div class="hbar"><span>${esc(n)}</span><div class="track"><div class="fill" data-w="${(v / maxC) * 100}"></div></div><b>${v}</b></div>`).join('') : '<div class="empty"><span class="ic">✅</span>부적합 사항이 없습니다.</div>'}</div>
      <div class="card"><div class="sec-title"><h2>🔁 반복 지적사항 TOP 5</h2><span class="hint">최근 ${D.repeat_days}일 · 동일 장소·항목 2회 이상</span></div>
        ${D.repeats.length ? `<ul class="list">${D.repeats.map((g, i) => `<li><button class="row-btn" type="button" data-act="show-repeat" data-i="${i}"><span class="chip dark">${i + 1}</span><div class="grow"><div class="main-t">${esc(g.text)}</div><div class="meta">${esc(g.place)} · ${esc(g.cat)} · 최근 ${esc(g.last)}</div></div><span class="chip ng">${g.count}회</span></button></li>`).join('')}</ul>` : '<div class="empty"><span class="ic">👍</span>반복 지적사항이 없습니다.</div>'}</div>
      <div class="card"><h2>⏱ 업무시간 절감 효과 (예상)</h2>
        <div class="kpis two"><div class="kpi"><div class="lab">절감률</div><div class="val">${fmtPct(t.rate)}</div><div class="foot">1회 ${t.before}분 → ${t.after}분</div></div>
        <div class="kpi ok"><div class="lab">누적 절감</div><div class="val">${t.total_hours}<small>시간</small></div><div class="foot">${D.total}건 × ${t.per}분</div></div></div>
        <p class="hint m0">※ 실측값이 아닌 가상 시나리오 기반 예상 수치입니다. 설정에서 소요시간을 확인할 수 있습니다.</p></div>
    </div>
    <div class="card mt16"><div class="sec-title"><h2>최근 점검 이력</h2><a class="btn sm ghost" href="/history">전체 보기 ›</a></div>
      ${D.recent.length ? `<ul class="list">${D.recent.map(histRow).join('')}</ul>` : '<div class="empty"><span class="ic">🗂</span>제출·확정된 점검이 없습니다.</div>'}</div>`;
    const dn = $('#donut');
    dn.style.background = ngTotal ? `conic-gradient(var(--ok) 0 ${d0}deg, var(--warn) ${d0}deg ${d1}deg, var(--ng) ${d1}deg 360deg)` : 'var(--none-bg)';
    applyWidths($('#dash'));
  }

  function ngHistTable(rows) {
    return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>일자</th><th>관리번호</th><th>부적합 내용</th><th>위험도</th><th>개선조치</th><th>상태</th></tr></thead><tbody>${rows.map(p => `<tr><td>${esc(p.date)}</td><td><a href="/inspections/${encodeURIComponent(p.insp_id)}/report">${esc(p.report_no)}</a></td><td>${esc(p.content)}</td><td>${p.risk ? `<span class="risk ${p.risk}">${RISK[p.risk]}</span>` : '-'}</td><td>${esc(p.action)}</td><td><span class="st s${stIdx(p.status)}">${ST[p.status] || ''}</span></td></tr>`).join('')}</tbody></table></div>`;
  }

  document.addEventListener('click', async e => {
    const rep = e.target.closest('[data-act="show-repeat"]');
    if (rep) {
      const g = D.repeats[+rep.dataset.i];
      modal({ title: '반복 지적사항 상세', wide: true, html: `<p class="m0"><b>${esc(g.text)}</b></p><p class="hint">${esc(g.place)} · ${esc(g.cat)} · 최근 ${D.repeat_days}일 ${g.count}회 · 최근 발생 ${esc(g.last)}</p>${ngHistTable(g.rows)}<p class="hint">근본원인 분석과 재발방지 대책 수립을 권장합니다.</p>` });
      return;
    }
    const del = e.target.closest('[data-act="del-draft"]');
    if (del) {
      if (!(await confirmBox('작성 중 점검 삭제', '작성 중인 점검을 삭제하시겠습니까? 입력 내용과 사진이 모두 삭제되며 되돌릴 수 없습니다.', '삭제', true))) return;
      const r = await apiOk('DELETE', '/api/inspections/' + encodeURIComponent(del.dataset.id), {});
      if (r) { toast('작성 중인 점검을 삭제했습니다.'); load(); }
    }
  });
  window.ngHistTable = ngHistTable;
  load();
})();
