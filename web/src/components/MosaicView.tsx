import { useEffect, useRef, useState } from 'preact/hooks';
import { pack, type Mosaic, type Packed, type Tile } from '../layout';
import { navigate } from '../router';
import { fmtShort } from '../util';
import { attachPanZoom, claimPlayback, fitCanvas, image, savedViews, zoomBy, type View } from './zoom';
import { ZoomCtl } from './ZoomCtl';

const MAXZ = 40;
const GAP = 1; // px between tiles
const big0 = (w: number, h: number) => Math.min(w, h);

function wrap(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, w: number, lh: number, lines: number) {
  const words = text.split(/\s+/);
  let line = '', n = 0;
  for (const word of words) {
    const t = line ? line + ' ' + word : word;
    if (ctx.measureText(t).width > w && line) {
      if (++n >= lines) { ctx.fillText(line + '…', x, y); return; }
      ctx.fillText(line, x, y); y += lh; line = word;
    } else line = t;
  }
  if (line) ctx.fillText(line, x, y);
}

/**
 * A packed, gapless mosaic of one half on a canvas: tiles fill the whole box at every zoom level
 * (zooming out stops at the full view, panning stays inside it). Covers are cropped to fill. The
 * tile under the pointer or keyboard focus plays muted; labels, dates and descriptions appear as
 * tiles grow. A hidden list of links mirrors the tiles for keyboard and screen-reader users.
 */
export function MosaicView({ mosaic, title, id, hrefFor }: { mosaic: Mosaic; title: string; id: string; hrefFor: (t: Tile) => string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const vid = useRef<HTMLVideoElement>(null);
  const view = useRef<View>({ k: 1, x: 0, y: 0 });
  const cells = useRef<Packed[]>([]);
  const size = useRef({ w: 0, h: 0 });
  const hover = useRef<Packed | null>(null);
  const raf = useRef(0);
  const [zoom, setZoom] = useState(1);

  // The world is the box itself at zoom 1: W×H in CSS pixels.
  const layoutFor = (w: number, h: number) => {
    if (w === size.current.w && h === size.current.h && cells.current.length) return;
    size.current = { w, h };
    cells.current = pack(mosaic, w, h);
  };
  const clamp = () => {
    const v = view.current, { w, h } = size.current;
    v.k = Math.max(1, Math.min(MAXZ, v.k));
    v.x = Math.min(0, Math.max(w - w * v.k, v.x));
    v.y = Math.min(0, Math.max(h - h * v.k, v.y));
  };

  const draw = () => {
    raf.current = 0;
    const c = canvas.current;
    if (!c) return;
    const { w, h, dpr } = fitCanvas(c);
    if (!w || !h) return;
    layoutFor(w, h);
    clamp();
    const ctx = c.getContext('2d')!;
    const v = view.current;
    const css = getComputedStyle(c);
    const fg = css.getPropertyValue('--text').trim() || '#111', tileBg = css.getPropertyValue('--surface-2').trim() || '#ddd', lineC = css.getPropertyValue('--bg').trim() || '#fff';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = lineC;
    ctx.fillRect(0, 0, w, h);
    for (const p of cells.current) {
      const x = p.x * v.k + v.x, y = p.y * v.k + v.y, cw = p.w * v.k, ch = p.h * v.k;
      if (x > w || y > h || x + cw < 0 || y + ch < 0) continue;
      const g = cw > 8 && ch > 8 ? GAP : 0;
      const ix = x + g / 2, iy = y + g / 2, iw = cw - g, ih = ch - g;
      ctx.fillStyle = tileBg;
      ctx.fillRect(ix, iy, iw, ih);
      const t = p.tile;
      if (Math.min(iw, ih) >= 10 && t.cover) {
        const img = image(t.cover, schedule);
        if (img) {
          // object-fit: cover
          const ir = img.naturalWidth / img.naturalHeight || 1, cr = iw / ih;
          let sw = img.naturalWidth, sh = img.naturalHeight;
          if (ir > cr) sw = sh * cr; else sh = sw / cr;
          ctx.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, ix, iy, iw, ih);
        }
      }
      const nh = t.item?.detection?.hits?.length || 0;
      if (nh && big0(iw, ih) >= 60) {
        const r = Math.min(11, Math.max(7, iw / 16));
        ctx.fillStyle = '#e9a35a'; ctx.beginPath(); ctx.arc(ix + iw - r - 5, iy + r + 5, r, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = '#111'; ctx.font = `700 ${r * 1.1}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.fillText(String(nh), ix + iw - r - 5, iy + r + 5 + r * 0.4); ctx.textAlign = 'start';
      }
      if (t.hit && iw > 12) { ctx.strokeStyle = '#e9a35a'; ctx.lineWidth = 3; ctx.strokeRect(ix + 1.5, iy + 1.5, iw - 3, ih - 3); }
      const big = Math.min(iw, ih);
      if (big >= 90 && !t.attachedTo) {
        const fs = Math.min(15, Math.max(10, big / 14));
        if (t.group) {
        ctx.font = `700 ${fs - 1}px system-ui, sans-serif`;
        const label = t.group;
        const lw = Math.min(iw - 12, ctx.measureText(label).width + 12);
        ctx.fillStyle = 'rgba(0,0,0,.5)'; ctx.fillRect(ix + 6, iy + 6, lw, fs + 6);
        ctx.fillStyle = '#fff'; ctx.save(); ctx.beginPath(); ctx.rect(ix + 6, iy + 6, lw, fs + 6); ctx.clip(); ctx.fillText(label, ix + 12, iy + fs + 6); ctx.restore();
        }
        if (big >= 140) {
          const grad = ctx.createLinearGradient(0, iy + ih * 0.55, 0, iy + ih);
          grad.addColorStop(0, 'rgba(0,0,0,0)'); grad.addColorStop(1, 'rgba(0,0,0,.75)');
          ctx.fillStyle = grad; ctx.fillRect(ix, iy + ih * 0.55, iw, ih * 0.45);
          ctx.fillStyle = '#fff'; ctx.font = `600 ${fs}px system-ui, sans-serif`;
          const lines = big >= 220 ? 2 : 0;
          if (t.date) ctx.fillText(fmtShort(t.date), ix + 8, iy + ih - 8 - lines * fs * 1.3);
          if (lines && t.text) { ctx.font = `400 ${fs}px system-ui, sans-serif`; wrap(ctx, t.text, ix + 8, iy + ih - 8 - (lines - 1) * fs * 1.3, iw - 16, fs * 1.3, lines); }
        }
      }
      if (hover.current === p) { ctx.strokeStyle = fg; ctx.lineWidth = 3; ctx.strokeRect(ix + 1.5, iy + 1.5, iw - 3, ih - 3); }
    }
    placeVideo();
  };
  const schedule = () => { if (!raf.current) raf.current = requestAnimationFrame(draw); };

  const cellAt = (sx: number, sy: number) => {
    const v = view.current, wx = (sx - v.x) / v.k, wy = (sy - v.y) / v.k;
    return cells.current.find((p) => wx >= p.x && wx <= p.x + p.w && wy >= p.y && wy <= p.y + p.h) || null;
  };

  // The one playing tile: a real <video> laid over its cell.
  const placeVideo = () => {
    const el = vid.current, p = hover.current, v = view.current;
    if (!el) return;
    const t = p?.tile;
    const cw = p ? p.w * v.k : 0, ch = p ? p.h * v.k : 0;
    if (!p || !t?.video || Math.min(cw, ch) < 56) { if (!el.paused) el.pause(); el.style.display = 'none'; return; }
    Object.assign(el.style, { display: 'block', left: `${p.x * v.k + v.x}px`, top: `${p.y * v.k + v.y}px`, width: `${cw}px`, height: `${ch}px` });
    if (el.dataset.src !== t.video) { el.dataset.src = t.video; el.src = t.video; el.poster = t.cover || ''; }
    claimPlayback(el);
    el.play().catch(() => undefined);
  };
  const setHover = (p: Packed | null) => { if (hover.current !== p) { hover.current = p; schedule(); } };
  const changed = () => { clamp(); savedViews.set(id, { ...view.current }); setZoom(view.current.k); schedule(); };

  const fit = () => { Object.assign(view.current, { k: 1, x: 0, y: 0 }); changed(); };

  useEffect(() => {
    const c = canvas.current!;
    cells.current = [];
    const keep = savedViews.get(id);
    Object.assign(view.current, keep || { k: 1, x: 0, y: 0 });
    setZoom(view.current.k);
    schedule();
    const off = attachPanZoom(c, view.current, {
      min: 1, max: MAXZ,
      onChange: changed,
      onTap: (sx, sy) => { const p = cellAt(sx, sy); if (p) navigate(hrefFor(p.tile)); },
      onHover: (sx, sy) => { const p = cellAt(sx, sy); setHover(p); c.style.cursor = p ? 'pointer' : 'grab'; },
      onLeave: () => setHover(null),
    });
    const ro = new ResizeObserver(() => schedule());
    ro.observe(c);
    return () => { off(); ro.disconnect(); if (raf.current) cancelAnimationFrame(raf.current); };
  }, [mosaic]);

  const focusTile = (t: Tile) => {
    const p = cells.current.find((x) => x.tile === t);
    if (!p) return;
    const { w, h } = size.current, v = view.current;
    const k = Math.max(v.k, Math.min(MAXZ, (Math.min(w, h) * 0.6) / Math.max(p.w, p.h)));
    Object.assign(v, { k, x: w / 2 - (p.x + p.w / 2) * k, y: h / 2 - (p.y + p.h / 2) * k });
    changed();
    setHover(p);
  };
  const zoomBtn = (f: number) => { zoomBy(view.current, size.current.w, size.current.h, f, 1, MAXZ); changed(); };

  return (
    <section class="mosaic" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} class="sr-only">{title}: {mosaic.tiles.length} videos</h2>
      <ZoomCtl title={title} zoom={zoom} onIn={() => zoomBtn(1.6)} onOut={() => zoomBtn(1 / 1.6)} onFit={fit} />
      <div class="mosaic-box">
        <canvas ref={canvas} class="mosaic-canvas" aria-hidden="true" />
        <video ref={vid} class="mosaic-video" muted loop playsinline preload="none" aria-hidden="true" tabIndex={-1}
          onClick={() => hover.current && navigate(hrefFor(hover.current.tile))} />
      </div>
      <ul class="mosaic-list" aria-label={`${title}: videos`}>
        {mosaic.tiles.map((t) => (
          <li key={t.id}><a href={hrefFor(t)} onFocus={() => focusTile(t)} onBlur={() => setHover(null)}>
            {[t.group, t.date && fmtShort(t.date)].filter(Boolean).join(', ')}: {t.text}
          </a></li>
        ))}
      </ul>
    </section>
  );
}
