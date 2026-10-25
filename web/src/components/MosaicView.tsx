import { useEffect, useRef, useState } from 'preact/hooks';
import { lastAlpha, pack, type Mosaic, type Packed, type Tile } from '../layout';
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

/** A "more" tile: its videos in a small grid that grows as you zoom in, with a count until each is big enough. */
function moreGrid(n: number, iw: number, ih: number) {
  const cols = Math.max(1, Math.round(Math.sqrt((n * iw) / ih))), rows = Math.ceil(n / cols);
  return { cols, rows, cw: iw / cols, ch: ih / rows };
}
let drawMore: (ctx: CanvasRenderingContext2D, more: Tile[], ix: number, iy: number, iw: number, ih: number) => void = () => undefined;

/**
 * A packed, gapless mosaic of one half on a canvas: tiles fill the whole box at every zoom level
 * (zooming out stops at the full view, panning stays inside it). Covers are cropped to fill. The
 * tile under the pointer or keyboard focus plays muted; labels, dates and descriptions appear as
 * tiles grow. A hidden list of links mirrors the tiles for keyboard and screen-reader users.
 */
export function MosaicView({ mosaic, title, id, hrefFor, share, clamped }: { mosaic: Mosaic; title: string; id: string; hrefFor: (t: Tile) => string; share?: number; clamped?: boolean }) {
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
    // For tests and debugging: each video's area and weight (attached images left out).
    const c = canvas.current;
    if (c) c.dataset.alpha = String(lastAlpha);
    if (c) c.dataset.cells = JSON.stringify(cells.current.map((p) => [p.tile.id, Math.round(p.w * p.h), +(p.tile.r * p.tile.r).toFixed(4), Math.round(p.x), Math.round(p.y), Math.round(p.w), Math.round(p.h), p.tile.video ? 1 : 0, p.tile.more ? 1 : 0]));
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
      if (t.more) { drawMore(ctx, t.more, ix, iy, iw, ih); continue; }
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
      if (t.hit && Math.min(iw, ih) >= 40) {
        ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(ix + 5, iy + ih - 22, 26, 17);
        ctx.fillStyle = '#e9a35a'; ctx.font = '700 10px system-ui, sans-serif'; ctx.fillText('AI', ix + 11, iy + ih - 9);
      }
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
      // Attached images: small insets in the video's corner, never cells of their own.
      if (t.kids?.length && big >= 110) {
        const kz = Math.round(big * 0.26), n = Math.min(t.kids.length, Math.max(1, Math.floor((iw - 16) / (kz + 4))), 3);
        for (let k = 0; k < n; k++) {
          const kx = ix + iw - 8 - (k + 1) * kz - k * 4, ky = iy + ih - 8 - kz - (big >= 140 ? 26 : 0);
          ctx.fillStyle = '#fff'; ctx.fillRect(kx - 2, ky - 2, kz + 4, kz + 4);
          const ki = t.kids[k].cover ? image(t.kids[k].cover!, schedule) : null;
          if (ki) { const m = Math.min(ki.naturalWidth, ki.naturalHeight); ctx.drawImage(ki, (ki.naturalWidth - m) / 2, (ki.naturalHeight - m) / 2, m, m, kx, ky, kz, kz); }
        }
      }
      if (hover.current === p) { ctx.strokeStyle = fg; ctx.lineWidth = 3; ctx.strokeRect(ix + 1.5, iy + 1.5, iw - 3, ih - 3); }
    }
    placeVideo();
  };
  const schedule = () => { if (!raf.current) raf.current = requestAnimationFrame(draw); };
  drawMore = (ctx, more, ix, iy, iw, ih) => {
    const g = moreGrid(more.length, iw, ih);
    more.forEach((t, i) => {
      const x = ix + (i % g.cols) * g.cw, y = iy + Math.floor(i / g.cols) * g.ch;
      const img = t.cover && Math.min(g.cw, g.ch) >= 8 ? image(t.cover, schedule) : null;
      if (img) {
        const ir = img.naturalWidth / img.naturalHeight || 1, cr = g.cw / g.ch;
        let sw = img.naturalWidth, sh = img.naturalHeight;
        if (ir > cr) sw = sh * cr; else sh = sw / cr;
        ctx.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, x + 0.5, y + 0.5, g.cw - 1, g.ch - 1);
      }
    });
    if (Math.min(g.cw, g.ch) < 48) {
      ctx.fillStyle = 'rgba(0,0,0,.55)'; ctx.fillRect(ix, iy, iw, ih);
      ctx.fillStyle = '#fff'; ctx.font = `700 ${Math.max(12, Math.min(22, Math.min(iw, ih) / 4))}px system-ui, sans-serif`; ctx.textAlign = 'center';
      ctx.fillText(`+${more.length}`, ix + iw / 2, iy + ih / 2 + 6); ctx.textAlign = 'start';
    }
  };

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
    if (el.dataset.src !== t.video) { el.dataset.src = t.video; el.classList.remove('on'); el.src = t.video; el.poster = t.cover || ''; }
    claimPlayback(el);
    el.play().catch(() => undefined);
  };
  // A preview starts after a short pause on a tile and stays while the pointer is anywhere over it.
  const hoverTimer = useRef(0);
  const setHover = (p: Packed | null, delay = 0) => {
    if (hover.current === p) { clearTimeout(hoverTimer.current); return; }
    clearTimeout(hoverTimer.current);
    if (delay && p) { hoverTimer.current = window.setTimeout(() => { hover.current = p; schedule(); }, delay); return; }
    hover.current = p; schedule();
  };
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
      onTap: (sx, sy) => {
        const p = cellAt(sx, sy);
        if (!p) return;
        if (!p.tile.more) { navigate(hrefFor(p.tile)); return; }
        // A "more" tile: open the video under the finger once they are big enough, else zoom in on it.
        const v = view.current, g = moreGrid(p.tile.more.length, p.w * v.k, p.h * v.k);
        if (Math.min(g.cw, g.ch) >= 48) {
          const col = Math.floor((sx - (p.x * v.k + v.x)) / g.cw), row = Math.floor((sy - (p.y * v.k + v.y)) / g.ch);
          const t = p.tile.more[row * g.cols + col];
          if (t) navigate(hrefFor(t));
          return;
        }
        const { w: W, h: H } = size.current;
        const k = Math.min(MAXZ, Math.max(v.k * 1.5, (48 * Math.max(g.cols, g.rows) * 1.2) / Math.min(p.w, p.h)));
        Object.assign(v, { k, x: W / 2 - (p.x + p.w / 2) * k, y: H / 2 - (p.y + p.h / 2) * k });
        changed();
      },
      onHover: (sx, sy) => { const p = cellAt(sx, sy); setHover(p, 150); c.style.cursor = p ? 'pointer' : 'grab'; },
      onLeave: () => setHover(null),
    });
    const ro = new ResizeObserver(() => schedule());
    ro.observe(c);
    return () => { off(); ro.disconnect(); if (raf.current) cancelAnimationFrame(raf.current); raf.current = 0; };
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
    <section class="mosaic" aria-labelledby={`${id}-h`} style={share ? { flex: `${share} 1 0` } : undefined} data-share={share?.toFixed(3)} data-clamped={clamped ? '1' : undefined}>
      <h2 id={`${id}-h`} class="sr-only">{title}: {mosaic.tiles.length} videos</h2>
      <ZoomCtl title={title} zoom={zoom} onIn={() => zoomBtn(1.6)} onOut={() => zoomBtn(1 / 1.6)} onFit={fit} />
      <div class="mosaic-box">
        <canvas ref={canvas} class="mosaic-canvas" aria-hidden="true" />
        <video ref={vid} class="mosaic-video" muted loop playsinline preload="none" aria-hidden="true" tabIndex={-1}
          onPlaying={(e) => (e.currentTarget as HTMLVideoElement).classList.add('on')} />
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
