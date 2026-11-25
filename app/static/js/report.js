'use strict';
/* ④ 보고서 검토 · 점검 상세: 종합의견 · 서명 · 제출/확인/반려 · 복사 · 삭제 */
(function () {
  const pid = BOOT.pid, perms = BOOT.perms || {};
  const base = '/inspections/' + encodeURIComponent(pid);
  let version = BOOT.version;
  const sigSaved = Object.assign({}, BOOT.sig);
  const stage = $('#rptStage');
  applyWidths(stage);
  fitReport(stage);
  $$('img', stage).forEach(img => img.addEventListener('load', () => fitReport(stage)));

  if (perms.edit) {
    Saver.init({ pid, getVersion: () => version, setVersion: v => { version = v; }, onSaved: () => refreshReport() });
    setActionBar(`<a class="btn" href="${base}/check">◀ 점검 수정</a><button class="btn navy" data-act="submit" type="button">점검자 서명 후 제출</button>`);
  } else if (perms.review) {
    setActionBar(`<button class="btn" data-act="reject" type="button">반려</button><button class="btn navy" data-act="confirm" type="button">확인(확정)</button>`);
  }
  $$('.sig-pad').forEach(c => SignaturePad.init(c));

  let refreshT = null;
  async function refreshReport() {
    clearTimeout(refreshT);
    refreshT = setTimeout(async () => {
      try {
        const res = await fetch(`${base}/report/fragment?mode=${encodeURIComponent(BOOT.mode)}`, { credentials: 'same-origin', cache: 'no-store' });
        if (!res.ok) return;
        $('.a4.rpt', stage).innerHTML = await res.text();
        applyWidths(stage); fitReport(stage);
        $$('img', stage).forEach(img => img.addEventListener('load', () => fitReport(stage)));
      } catch (e) { }
    }, 300);
  }

  async function saveSignature(role) {
    if (SignaturePad.isEmpty(role)) return sigSaved[role];
    const r = await apiOk('POST', `/api/inspections/${encodeURIComponent(pid)}/signatures`, { role, image: SignaturePad.dataUrl(role) });
    if (!r) return false;
    sigSaved[role] = true; SignaturePad.clear(role);
    const st = $('#sigSt-' + role); if (st) st.innerHTML = '<span class="sig-done">✔ 서명됨 (방금)</span>';
    toast('서명을 저장했습니다.', 'ok'); refreshReport();
    return true;
  }

  async function submit(btn) {
    await Saver.idle();
    if (SignaturePad.isEmpty('inspector') && !sigSaved.inspector) {
      await alertBox('점검자 서명 필요', '서명란에 점검자 서명을 한 뒤 제출하세요.'); $('.sig-pad[data-role="inspector"]').scrollIntoView({ behavior: 'smooth', block: 'center' }); return;
    }
    if (!(await confirmBox('점검 제출', '제출하면 <b>점검 결과가 잠기고</b> 제출 시각이 종료 시간으로 기록됩니다.<br>이후에는 개선조치 정보만 수정할 수 있으며, 확인자가 반려하면 다시 수정할 수 있습니다.<br><br>제출하시겠습니까?', '제출'))) return;
    btn.disabled = true;
    try {
      if (!(await saveSignature('inspector'))) return;
      let r;
      try { r = await api('POST', `/api/inspections/${encodeURIComponent(pid)}/submit`, {}); } catch (e) { toast('서버에 연결할 수 없습니다.', 'err'); return; }
      if (r.ok) { toast('점검을 제출했습니다. 확인자의 확인을 기다립니다.', 'ok', 4000); setTimeout(() => location.reload(), 600); return; }
      if (r.error.code === 'INCOMPLETE') {
        await alertBox('제출 불가', `입력이 완료되지 않은 항목이 <b>${r.error.items.length}건</b> 있습니다.<ul>${r.error.items.slice(0, 8).map(x => `<li>${esc(x.name)} — ${esc(x.message)}</li>`).join('')}</ul>첫 번째 미완료 항목으로 이동합니다.`);
        location.href = base + '/check#incomplete'; return;
      }
      if (r.error.code === 'VALIDATION' && r.error.fields) { await alertBox('제출 불가', esc(errMsg(r))); location.href = base + '/info'; return; }
      toast(errMsg(r), 'err', 5000);
    } finally { btn.disabled = false; }
  }
  async function confirmInsp(btn) {
    if (SignaturePad.isEmpty('confirmer') && !sigSaved.confirmer) {
      await alertBox('확인자 서명 필요', '서명란에 확인자 서명을 한 뒤 확인하세요.'); $('.sig-pad[data-role="confirmer"]').scrollIntoView({ behavior: 'smooth', block: 'center' }); return;
    }
    if (!(await confirmBox('확인(확정)', '확인하면 <b>관리번호가 발급</b>되고 현재 점검 결과가 <b>최초 보고서</b>로 보존됩니다.<br>확정 이후에는 개선조치 정보만 수정할 수 있습니다.<br><br>확정하시겠습니까?', '확정'))) return;
    btn.disabled = true;
    try {
      if (!(await saveSignature('confirmer'))) return;
      const r = await apiOk('POST', `/api/inspections/${encodeURIComponent(pid)}/confirm`, {});
      if (r) { toast(`점검이 확정되었습니다. 관리번호 ${r.data.report_no}`, 'ok', 5000); setTimeout(() => { location.href = base + '/report?mode=original'; }, 700); }
    } finally { btn.disabled = false; }
  }
  async function rejectInsp() {
    const reason = await reasonBox('반려', '반려하면 점검자가 내용을 수정한 뒤 다시 제출해야 합니다. 반려 사유는 보고서와 감사로그에 기록됩니다.', '반려', '예: 부적합 원인 기재를 구체적으로 보완하세요.');
    if (!reason) return;
    const r = await apiOk('POST', `/api/inspections/${encodeURIComponent(pid)}/reject`, { reason });
    if (r) { toast('반려했습니다.', 'ok'); setTimeout(() => location.reload(), 600); }
  }

  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const act = b.dataset.act;
    if (act === 'sig-clear') SignaturePad.clear(b.dataset.role);
    if (act === 'sig-save') { if (SignaturePad.isEmpty(b.dataset.role)) { toast('서명란에 서명하세요.', 'warn'); return; } saveSignature(b.dataset.role); }
    if (act === 'submit') submit(b);
    if (act === 'confirm') confirmInsp(b);
    if (act === 'reject') rejectInsp();
    if (act === 'regen-opinion') {
      if (BOOT.opinion_edited && !(await confirmBox('초안 다시 생성', '수정한 종합의견이 자동 생성 초안으로 대체됩니다. 계속하시겠습니까?', '다시 생성'))) return;
      await Saver.idle();
      const r = await apiOk('POST', `/api/inspections/${encodeURIComponent(pid)}/opinion`, { version });
      if (r) { version = r.data.version; BOOT.opinion_edited = false; $('#opinionTa').value = r.data.opinion; const o = $('#rptOpinion'); if (o) o.textContent = r.data.opinion; toast('종합의견 초안을 다시 생성했습니다.', 'ok'); }
    }
    if (act === 'copy-insp') {
      if (!(await confirmBox('복사해서 새 점검', '기본정보와 체크리스트 구성을 복사해 새 점검을 만듭니다. 점검 결과·사진은 복사되지 않습니다.', '새 점검 만들기'))) return;
      const r = await apiOk('POST', '/api/inspections', { copy_from: pid });
      if (r) location.href = `/inspections/${encodeURIComponent(r.data.id)}/info`;
    }
    if (act === 'delete-insp') {
      let body = {};
      if (b.dataset.soft === '1') {
        const reason = await reasonBox('확정된 점검 삭제', '제출·확정된 점검은 <b>소프트 삭제</b>되어 목록에서 사라지며, 기록은 감사 목적으로 보존됩니다.', '삭제');
        if (!reason) return; body.reason = reason;
      } else if (!(await confirmBox('점검 삭제', '작성 중인 점검을 삭제하시겠습니까? 입력 내용과 사진이 모두 삭제되며 되돌릴 수 없습니다.', '삭제', true))) return;
      const r = await apiOk('DELETE', '/api/inspections/' + encodeURIComponent(pid), body);
      if (r) { toast('삭제했습니다.'); setTimeout(() => { location.href = '/history'; }, 500); }
    }
  });
  const ta = $('#opinionTa');
  if (ta && perms.edit && !ta.value.trim()) {  // 종합의견이 비어 있으면 초안 자동 생성
    (async () => { const r = await apiOk('POST', `/api/inspections/${encodeURIComponent(pid)}/opinion`, { version }); if (r) { version = r.data.version; ta.value = r.data.opinion; const o = $('#rptOpinion'); if (o) o.textContent = r.data.opinion; } })();
  }
  if (ta) ta.addEventListener('input', () => { BOOT.opinion_edited = true; Saver.queue('PATCH', '/api/inspections/' + encodeURIComponent(pid), { opinion: ta.value }); const o = $('#rptOpinion'); if (o) o.textContent = ta.value; });

  // 위험도 '상' 미완료 부적합 배너
  if (BOOT.status !== 'confirmed') {
    (async () => { try { const r = await api('GET', '/api/inspections/' + encodeURIComponent(pid)); if (r.ok) { let n = 0; r.data.categories.forEach(c => c.items.forEach(it => { if (it.result === 'ng' && it.ng.risk === 'h' && it.ng.status !== 'done') n++; })); updateBanner(n, perms.edit ? base + '/check' : null); } } catch (e) { } })();
  }
})();
