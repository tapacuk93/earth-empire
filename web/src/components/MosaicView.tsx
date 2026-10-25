import { useEffect, useRef, useState } from 'preact/hooks';
import type { Mosaic, Tile } from '../layout';
import { navigate } from '../router';
import { fmtShort } from '../util';
import { savedViews, attachPanZoom, claimPlayback, fitCanvas, image, zoomBy, type View } from './zoom';
import { Icon } from './icons';

const MIN = 0.15, MAX = 60;

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
 * An infinitely zoomable mosaic of video tiles on a canvas. Tiles show their cover; the one under
 * the pointer (or keyboard focus) plays muted; labels, dates and descriptions appear as you zoom.
 * A visually hidden list of links mirrors the tiles for keyboard and screen-reader users.
 */
export function MosaicView({ mosaic, title, id, hrefFor }: { mosaic: Mosaic; title: string; id: string; hrefFor: (t: Tile) => string }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const vid = useRef<HTMLVideoElement>(null);
  const view = useRef<View>({ k: 1, x: 0, y: 0 });
  const hover = useRef<Tile | null>(null);
  const raf = useRef(0);
  const [zoom, setZoom] = useState(1);
  const base = useRef(1);

  const draw = () => {
    raf.current = 0;
    const c = canvas.current;
    if (!c) return;
    const { w, h, dpr } = fitCanvas(c);
    const ctx = c.getContext('2d')!;
    const v = view.current;
    const css = getComputedStyle(c);
    const fg = css.getPropertyValue('--text').trim() || '#111', muted = css.getPropertyValue('--muted').trim() || '#666', tileBg = css.getPropertyValue('--surface-2').trim() || '#ddd';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    for (const t of mosaic.tiles) {
      const s = 2 * t.r * v.k, sx = t.x * v.k + v.x - s / 2, sy = t.y * v.k + v.y - s / 2;
      if (sx > w || sy > h || sx + s < 0 || sy + s < 0) continue;
      const g = Math.max(0.5, Math.min(3, s * 0.03));
      const x = sx + g, y = sy + g, z = s - 2 * g;
      ctx.fillStyle = tileBg;
      ctx.fillRect(x, y, z, z);
      if (z >= 12 && t.cover) {
        const img = image(t.cover, schedule);
        if (img) {
          const ir = img.naturalWidth / img.naturalHeight || 1;
          const [sw, sh] = ir > 1 ? [img.naturalHeight, img.naturalHeight] : [img.naturalWidth, img.naturalWidth];
          ctx.drawImage(img, (img.naturalWidth - sw) / 2, (img.naturalHeight - sh) / 2, sw, sh, x, y, z, z);
        }
      }
      if (t.hit && z >= 10) { ctx.strokeStyle = '#e9a35a'; ctx.lineWidth = Math.max(1, z * 0.03); ctx.strokeRect(x, y, z, z); }
      if (z >= 110) {
        const grad = ctx.createLinearGradient(0, y + z * 0.55, 0, y + z);
        grad.addColorStop(0, 'rgba(0,0,0,0)'); grad.addColorStop(1, 'rgba(0,0,0,.75)');
        ctx.fillStyle = grad; ctx.fillRect(x, y + z * 0.55, z, z * 0.45);
        ctx.fillStyle = '#fff';
        const fs = Math.min(15, Math.max(10, z / 18));
        ctx.font = `600 ${fs}px system-ui, sans-serif`;
        if (t.date) ctx.fillText(fmtShort(t.date), x + 8, y + z - 8 - (z >= 190 ? fs * 2.6 : 0));
        if (z >= 190 && t.text) { ctx.font = `400 ${fs}px system-ui, sans-serif`; wrap(ctx, t.text, x + 8, y + z - 8 - fs * 1.3, z - 16, fs * 1.3, 2); }
      }
      if (hover.current === t) { ctx.strokeStyle = fg; ctx.lineWidth = 3; ctx.strokeRect(x + 1.5, y + 1.5, z - 3, z - 3); }
    }
    // Group labels: always, sized to stay legible.
    ctx.textAlign = 'center';
    for (const gr of mosaic.groups) {
      const gx = gr.x * v.k + v.x, gy = (gr.y - gr.r) * v.k + v.y - 6;
      if (gr.r * v.k < 18) continue;
      const fs = Math.max(11, Math.min(22, gr.r * v.k * 0.12));
      ctx.font = `700 ${fs}px system-ui, sans-serif`;
      const tw = ctx.measureText(gr.name).width;
      ctx.fillStyle = 'rgba(0,0,0,.55)';
      ctx.fillRect(gx - tw / 2 - 6, gy - fs, tw + 12, fs + 6);
      ctx.fillStyle = '#fff';
      ctx.fillText(gr.name, gx, gy);
    }
    ctx.textAlign = 'start';
    void muted;
    placeVideo();
  };
  const schedule = () => { if (!raf.current) raf.current = requestAnimationFrame(draw); };

  const tileAt = (sx: number, sy: number) => {
    const v = view.current, wx = (sx - v.x) / v.k, wy = (sy - v.y) / v.k;
    for (let i = mosaic.tiles.length - 1; i >= 0; i--) { const t = mosaic.tiles[i]; if (Math.abs(wx - t.x) <= t.r && Math.abs(wy - t.y) <= t.r) return t; }
    return null;
  };

  // The one playing tile: a real <video> laid over its square.
  const placeVideo = () => {
    const el = vid.current, t = hover.current, v = view.current;
    if (!el) return;
    const s = t ? 2 * t.r * v.k : 0;
    if (!t || !t.video || s < 56) { if (!el.paused) el.pause(); el.style.display = 'none'; return; }
    el.style.display = 'block';
    el.style.left = `${t.x * v.k + v.x - s / 2}px`; el.style.top = `${t.y * v.k + v.y - s / 2}px`;
    el.style.width = el.style.height = `${s}px`;
    if (el.dataset.src !== t.video) { el.dataset.src = t.video; el.src = t.video; el.poster = t.cover || ''; }
    claimPlayback(el);
    el.play().catch(() => undefined);
  };
  const setHover = (t: Tile | null) => { if (hover.current !== t) { hover.current = t; schedule(); } };

  const fit = () => {
    const c = canvas.current!;
    const w = c.clientWidth, h = c.clientHeight;
    const k = Math.min(w / (mosaic.width + 2), h / (mosaic.height + 2));
    base.current = k;
    Object.assign(view.current, { k, x: w / 2, y: h / 2 });
    setZoom(1);
    schedule();
  };

  useEffect(() => {
    const c = canvas.current!;
    fit();
    const keep = savedViews.get(id);
    if (keep) { Object.assign(view.current, keep); setZoom(keep.k / base.current); schedule(); }
    const off = attachPanZoom(c, view.current, {
      min: MIN, max: MAX * Math.max(1, base.current),
      onChange: () => { savedViews.set(id, { ...view.current }); setZoom(view.current.k / base.current); schedule(); },
      onTap: (sx, sy) => { const t = tileAt(sx, sy); if (t) navigate(hrefFor(t)); },
      onHover: (sx, sy) => { const t = tileAt(sx, sy); setHover(t); c.style.cursor = t ? 'pointer' : 'grab'; },
      onLeave: () => setHover(null),
    });
    const ro = new ResizeObserver(() => schedule());
    ro.observe(c);
    return () => { off(); ro.disconnect(); if (raf.current) cancelAnimationFrame(raf.current); };
  }, [mosaic]);

  const focusTile = (t: Tile) => {
    const c = canvas.current!, v = view.current;
    const target = Math.max(v.k, (Math.min(c.clientWidth, c.clientHeight) * 0.45) / (2 * t.r));
    view.current.k = target;
    view.current.x = c.clientWidth / 2 - t.x * target;
    view.current.y = c.clientHeight / 2 - t.y * target;
    setZoom(target / base.current);
    setHover(t);
  };
  const zoomBtn = (f: number) => { const c = canvas.current!; zoomBy(view.current, c.clientWidth, c.clientHeight, f, MIN, MAX * Math.max(1, base.current)); setZoom(view.current.k / base.current); schedule(); };

  return (
    <section class="mosaic" aria-labelledby={`${id}-h`}>
      <header class="mosaic-head">
        <h2 id={`${id}-h`}>{title}</h2>
        <span class="muted small">{mosaic.tiles.length} videos</span>
        <span class="spacer" />
        <span class="muted small zoom-level" role="status">{zoom.toFixed(1)}×</span>
        <button class="icon-btn" onClick={() => zoomBtn(1.6)} aria-label={`Zoom in: ${title}`}>+</button>
        <button class="icon-btn" onClick={() => zoomBtn(1 / 1.6)} aria-label={`Zoom out: ${title}`}>−</button>
        <button class="icon-btn" onClick={fit} aria-label={`Show all: ${title}`}><Icon name="auto" size={18} /></button>
      </header>
      <div class="mosaic-box" ref={box}>
        <canvas ref={canvas} class="mosaic-canvas" aria-hidden="true" />
        <video ref={vid} class="mosaic-video" muted loop playsinline preload="none" aria-hidden="true" tabIndex={-1}
          onClick={() => hover.current && navigate(hrefFor(hover.current))} />
        <p class="mosaic-hint" aria-hidden="true">Pinch or scroll with Ctrl to zoom · drag to move · tap a video</p>
      </div>
      <ul class="mosaic-list" aria-label={`${title}: videos`}>
        {mosaic.tiles.map((t) => (
          <li key={t.id}><a href={hrefFor(t)} onFocus={() => focusTile(t)} onBlur={() => setHover(null)}>
            {t.group}{t.date ? `, ${fmtShort(t.date)}` : ''}: {t.text}
          </a></li>
        ))}
      </ul>
    </section>
  );
}
