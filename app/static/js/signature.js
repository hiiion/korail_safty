'use strict';
/* 서명 캔버스 (마우스·터치·펜 공통, Pointer Events) */
const SignaturePad = {
  pads: new Map(),
  init(canvas) {
    const ctx = canvas.getContext('2d');
    const st = { canvas, ctx, drawing: false, dirty: false, last: null };
    const resize = () => {
      const r = canvas.getBoundingClientRect(); const dpr = window.devicePixelRatio || 1;
      const keep = st.dirty ? canvas.toDataURL() : null;
      canvas.width = Math.max(1, Math.round(r.width * dpr)); canvas.height = Math.max(1, Math.round(r.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.lineWidth = 2.6; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#111';
      if (keep) { const img = new Image(); img.onload = () => ctx.drawImage(img, 0, 0, r.width, r.height); img.src = keep; }
    };
    const pos = e => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    canvas.addEventListener('pointerdown', e => { e.preventDefault(); canvas.setPointerCapture(e.pointerId); st.drawing = true; st.last = pos(e); ctx.beginPath(); ctx.arc(st.last.x, st.last.y, 1.2, 0, 7); ctx.fill(); st.dirty = true; });
    canvas.addEventListener('pointermove', e => { if (!st.drawing) return; const p = pos(e); ctx.beginPath(); ctx.moveTo(st.last.x, st.last.y); ctx.lineTo(p.x, p.y); ctx.stroke(); st.last = p; });
    const end = () => { st.drawing = false; };
    canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end); canvas.addEventListener('pointerleave', end);
    window.addEventListener('resize', resize);
    resize();
    this.pads.set(canvas.dataset.role, st);
    return st;
  },
  clear(role) { const st = this.pads.get(role); if (!st) return; st.ctx.clearRect(0, 0, st.canvas.width, st.canvas.height); st.dirty = false; },
  isEmpty(role) { const st = this.pads.get(role); return !st || !st.dirty; },
  dataUrl(role) { const st = this.pads.get(role); return st && st.dirty ? st.canvas.toDataURL('image/png') : ''; }
};
