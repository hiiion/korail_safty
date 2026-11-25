'use strict';
/* 인쇄 전용 페이지: 로컬 웹앱은 iframe 제약이 없으므로 window.print()가 바로 동작한다 */
document.querySelectorAll('[data-w]').forEach(el => { el.style.width = el.dataset.w + '%'; });
document.getElementById('printBtn').addEventListener('click', () => window.print());
