'use strict';
/* 설정: 업무시간 절감 기준 · JSON 불러오기(관리자) */
(function () {
  (async () => {
    try { const r = await api('GET', '/api/settings'); if (r.ok) { $('#s-before').value = r.data.before_min; $('#s-after').value = r.data.after_min; } } catch (e) { }
  })();
  let fileData = null;

  async function preview(obj) {
    const r = await apiOk('POST', '/api/import', { data: obj });
    if (!r) return;
    const d = r.data;
    $('#importBox').innerHTML = `<div class="import-box"><p class="m0"><b>${esc(d.kind)}</b> · 올바른 점검 ${d.valid}건 · 사진 ${d.photos}장${d.bad.length ? ` · <span class="ng-text">형식 오류 ${d.bad.length}건(${d.bad.join(', ')}번째) 제외</span>` : ''}</p>
      ${d.conflicts.length ? `<p class="warn-text"><b>같은 ID의 점검 ${d.conflicts.length}건</b>이 이미 있습니다.</p><ul class="hint">${d.conflicts.slice(0, 10).map(c => `<li>${esc(c.date)} · ${esc(c.place)} ${esc(c.report_no || '')}</li>`).join('')}${d.conflicts.length > 10 ? '<li>…</li>' : ''}</ul>` : '<p class="hint">충돌하는 점검이 없습니다.</p>'}
      <div class="tools"><button class="btn" type="button" data-act="import-run" data-mode="skip">${d.conflicts.length ? '충돌 건 건너뛰고 ' : ''}불러오기</button>${d.conflicts.length ? '<button class="btn danger" type="button" data-act="import-run" data-mode="overwrite">충돌 건 덮어쓰기</button>' : ''}<button class="btn ghost" type="button" data-act="import-cancel">취소</button></div></div>`;
  }

  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    if (b.dataset.act === 'save-time') {
      const before = +$('#s-before').value, after = +$('#s-after').value;
      if (!(before > 0) || !(after >= 0) || after > before) { toast('기존 소요시간은 0보다 커야 하며, 자동화 후 시간은 기존 시간 이하여야 합니다.', 'err', 4000); return; }
      const r = await apiOk('PATCH', '/api/settings', { before_min: before, after_min: after });
      if (r) toast('저장했습니다.', 'ok');
    }
    if (b.dataset.act === 'import') $('#importFile').click();
    if (b.dataset.act === 'import-cancel') { fileData = null; $('#importBox').innerHTML = ''; }
    if (b.dataset.act === 'import-run' && fileData) {
      const mode = b.dataset.mode;
      if (mode === 'overwrite' && !(await confirmBox('덮어쓰기 확인', '같은 ID의 기존 점검(사진 포함)이 삭제되고 파일의 내용으로 교체됩니다. 계속하시겠습니까?', '덮어쓰기', true))) return;
      b.disabled = true; toast('불러오는 중입니다… 사진이 많으면 시간이 걸릴 수 있습니다.');
      const r = await apiOk('POST', '/api/import', { data: fileData, mode });
      b.disabled = false;
      if (r) { $('#importBox').innerHTML = `<div class="notice">불러오기 완료: ${r.data.imported}건 추가${r.data.skipped ? `, ${r.data.skipped}건 건너뜀` : ''}${r.data.bad.length ? `, 형식 오류 ${r.data.bad.length}건 제외` : ''}</div>`; fileData = null; }
    }
  });
  const fi = $('#importFile');
  if (fi) fi.addEventListener('change', async () => {
    const f = fi.files && fi.files[0]; fi.value = '';
    if (!f) return;
    let obj;
    try { obj = JSON.parse(await f.text()); } catch (e) { alertBox('불러오기 실패', 'JSON 파일을 읽을 수 없습니다. 기존 데이터는 변경되지 않았습니다.'); return; }
    fileData = obj; preview(obj);
  });
})();
