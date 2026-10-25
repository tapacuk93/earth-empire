import { useEffect, useRef, useState } from 'preact/hooks';
import type { GEdge, GNode } from '../layout';
import { savedViews, attachPanZoom, fitCanvas, zoomBy, type View } from './zoom';
import { ZoomCtl } from './ZoomCtl';

const MIN = 0.2, MAX = 40;
const COLOR: Record<string, string> = { facet: '--accent-2', person: '--g-people', place: '--g-places', country: '--g-places', object: '--g-things', animal: '--g-things', brand: '--g-things', category: '--g-cats' };

/** Tags as nodes sized by count, edges for tags that appear together; zooming in reveals finer tags. */
export function TagGraphView({ nodes, edges, onOpen, labelFor }: { nodes: GNode[]; edges: GEdge[]; onOpen: (n: GNode) => void; labelFor: (n: GNode) => string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<View>({ k: 1, x: 0, y: 0 });
  const base = useRef(1);
  const raf = useRef(0);
  const hover = useRef<GNode | null>(null);
  const [zoom, setZoom] = useState(1);
  const limitNow = () => Math.round(18 * Math.pow(view.current.k / base.current, 1.3));

  const draw = () => {
    raf.current = 0;
    const c = canvas.current;
    if (!c) return;
    const { w, h, dpr } = fitCanvas(c);
    const ctx = c.getContext('2d')!;
    const css = getComputedStyle(c);
    const v = view.current, limit = limitNow();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const sx = (n: GNode) => n.x * v.k + v.x, sy = (n: GNode) => n.y * v.k + v.y;
    ctx.strokeStyle = css.getPropertyValue('--line').trim() || '#ccc';
    for (const e of edges) {
      const a = nodes[e.a], b = nodes[e.b];
      if (a.rank >= limit || b.rank >= limit) continue;
      ctx.lineWidth = Math.min(4, 0.5 + e.w * 0.5);
      ctx.beginPath(); ctx.moveTo(sx(a), sy(a)); ctx.lineTo(sx(b), sy(b)); ctx.stroke();
    }
    const fg = css.getPropertyValue('--text').trim() || '#111';
    const bg = css.getPropertyValue('--bg').trim() || '#fff';
    const shown: GNode[] = [];
    for (const n of nodes) {
      if (n.rank >= limit) continue;
      const x = sx(n), y = sy(n), r = Math.max(3, n.r * v.k);
      if (x + r < 0 || y + r < 0 || x - r > w || y - r > h) continue;
      shown.push(n);
      ctx.fillStyle = css.getPropertyValue(COLOR[n.kind] || '--g-tags').trim() || '#36c';
      ctx.globalAlpha = hover.current === n ? 1 : 0.85;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      if (hover.current === n) { ctx.strokeStyle = fg; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, r + 2, 0, Math.PI * 2); ctx.stroke(); ctx.strokeStyle = css.getPropertyValue('--line').trim(); }
    }
    // Labels never overlap: most used first, each tried below, above, right and left of its node,
    // skipped when every spot collides with a label already placed. Zooming in makes room for more.
    const placed: [number, number, number, number][] = [];
    const circles = shown.map((n) => [sx(n), sy(n), Math.max(3, n.r * v.k)] as const);
    const hitsCircle = (a: [number, number, number, number]) => circles.some(([cx, cy, r]) => {
      const nx = Math.max(a[0], Math.min(cx, a[0] + a[2])), ny = Math.max(a[1], Math.min(cy, a[1] + a[3]));
      return (cx - nx) ** 2 + (cy - ny) ** 2 < (r + 1) ** 2;
    });
    const hits = (a: [number, number, number, number]) => hitsCircle(a) || placed.some((b) => a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3]);
    for (const n of shown.slice().sort((a, b) => a.rank - b.rank)) {
      const x = sx(n), y = sy(n), r = Math.max(3, n.r * v.k);
      const fs = Math.max(10, Math.min(18, r * 0.6 + 8));
      ctx.font = `${n.rank < 10 ? 700 : 500} ${fs}px system-ui, sans-serif`;
      const text = labelFor(n);
      const tw = ctx.measureText(text).width, th = fs * 1.2, pad = 3;
      const spots: [number, number][] = [[x - tw / 2, y + r + 4], [x - tw / 2, y - r - 4 - th], [x + r + 6, y - th / 2], [x - r - 6 - tw, y - th / 2], [x + r * 0.7 + 4, y + r * 0.7], [x - r * 0.7 - 4 - tw, y + r * 0.7], [x + r * 0.7 + 4, y - r * 0.7 - th], [x - r * 0.7 - 4 - tw, y - r * 0.7 - th]];
      for (const [lx, ly] of spots) {
        const box: [number, number, number, number] = [lx - pad, ly - pad / 2, tw + 2 * pad, th + pad];
        // Inside the safe area (clear of the floating label and controls), clear of every circle and label.
        if (box[0] < 6 || box[1] < 6 || box[0] + box[2] > w - 6 || box[1] + box[3] > h - 6 || hits(box)) continue;
        placed.push(box);
        ctx.fillStyle = bg; ctx.globalAlpha = 0.7; ctx.fillRect(...box); ctx.globalAlpha = 1;
        ctx.fillStyle = fg; ctx.fillText(text, lx, ly + fs * 0.95);
        break;
      }
    }
    c.dataset.labels = JSON.stringify(placed.map((b) => b.map((q) => Math.round(q * 10) / 10)));
    c.dataset.circles = JSON.stringify(circles.filter(([cx, cy, r]) => cx + r > 0 && cy + r > 0 && cx - r < w && cy - r < h).map((q) => q.map((z) => Math.round(z * 10) / 10)));
    c.dataset.size = `${w}x${h}`;
  };
  const schedule = () => { if (!raf.current) raf.current = requestAnimationFrame(draw); };
  const nodeAt = (px: number, py: number) => {
    const v = view.current, limit = limitNow();
    let best: GNode | null = null, bd = Infinity;
    for (const n of nodes) {
      if (n.rank >= limit) continue;
      const d = Math.hypot(n.x * v.k + v.x - px, n.y * v.k + v.y - py);
      if (d <= Math.max(10, n.r * v.k + 4) && d < bd) { best = n; bd = d; }
    }
    return best;
  };
  const fit = () => {
    const c = canvas.current!;
    const top = nodes.filter((n) => n.rank < 18);
    const ext = Math.max(4, ...top.map((n) => Math.max(Math.abs(n.x), Math.abs(n.y)) + n.r * 2));
    const k = Math.min(c.clientWidth, c.clientHeight) / (2 * ext) * 0.9;
    base.current = k;
    Object.assign(view.current, { k, x: c.clientWidth / 2, y: c.clientHeight / 2 });
    setZoom(1); schedule();
  };
  useEffect(() => {
    const c = canvas.current!;
    fit();
    const keep = savedViews.get('tags');
    if (keep) { Object.assign(view.current, keep); setZoom(keep.k / base.current); schedule(); }
    const off = attachPanZoom(c, view.current, {
      min: MIN * base.current, max: MAX * base.current,
      onChange: () => { savedViews.set('tags', { ...view.current }); setZoom(view.current.k / base.current); schedule(); },
      onTap: (x, y) => { const n = nodeAt(x, y); if (n) onOpen(n); },
      onHover: (x, y) => { const n = nodeAt(x, y); if (hover.current !== n) { hover.current = n; schedule(); } c.style.cursor = n ? 'pointer' : 'grab'; },
      onLeave: () => { hover.current = null; schedule(); },
    });
    const ro = new ResizeObserver(() => schedule());
    ro.observe(c);
    return () => { off(); ro.disconnect(); if (raf.current) cancelAnimationFrame(raf.current); raf.current = 0; };
  }, [nodes]);
  const zoomBtn = (f: number) => { const c = canvas.current!; zoomBy(view.current, c.clientWidth, c.clientHeight, f, MIN * base.current, MAX * base.current); setZoom(view.current.k / base.current); schedule(); };

  return (
    <section class="mosaic tag-graph" aria-labelledby="tg-h">
      <h2 id="tg-h" class="mosaic-label fui">Tags <span>{Math.min(nodes.length, limitNow())} of {nodes.length} · zoom for finer tags</span></h2>
      <ZoomCtl title="tags" zoom={zoom} onIn={() => zoomBtn(1.6)} onOut={() => zoomBtn(1 / 1.6)} onFit={fit} />
      <div class="mosaic-box"><canvas ref={canvas} class="mosaic-canvas" aria-hidden="true" /></div>
      <ul class="mosaic-list" aria-label="Tags, most used first">
        {nodes.map((n) => <li key={n.tag}><a href={`/?tag=${encodeURIComponent(n.tag)}`} onClick={(e) => { e.preventDefault(); onOpen(n); }}>{labelFor(n)}: {n.count} video{n.count === 1 ? '' : 's'}</a></li>)}
      </ul>
    </section>
  );
}
