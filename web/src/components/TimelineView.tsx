import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { Item } from '../types';
import { navigate } from '../router';
import { cover, fmtShort } from '../util';
import { savedViews, attachPanZoom, claimPlayback, fitCanvas, image, zoomBy, type View } from './zoom';
import { ZoomCtl } from './ZoomCtl';

interface T { it: Item; x: number; y: number; video?: string; src?: string }
const DAY = 864e5;
const yearFmt = new Intl.DateTimeFormat('en', { year: 'numeric', timeZone: 'UTC' });
const monFmt = new Intl.DateTimeFormat('en', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const dayFmt = new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', timeZone: 'UTC' });

/**
 * Every video along time, newest at the top: one row per day, zoomable. Zoomed out it reads in
 * years, then months, then days, and the tiles grow as you zoom in.
 */
export function TimelineView({ items, hrefFor }: { items: Item[]; hrefFor: (it: Item) => string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const vid = useRef<HTMLVideoElement>(null);
  const view = useRef<View>({ k: 1, x: 0, y: 0 });
  const base = useRef(1);
  const raf = useRef(0);
  const hover = useRef<T | null>(null);
  const [zoom, setZoom] = useState(1);
  const newest = items.length ? Date.parse(items[0].taken_at) : Date.now();
  const tiles = useMemo(() => {
    const perDay = new Map<number, number>();
    return items.map((it) => {
      const d = Math.floor((newest - Date.parse(it.taken_at)) / DAY);
      const n = perDay.get(d) || 0;
      perDay.set(d, n + 1);
      const m = it.media[0] || it.repost_of?.media?.[0];
      return { it, x: n, y: d, video: m?.type === 'video' ? m.url : undefined, src: cover(it) } as T;
    });
  }, [items]);
  const span = Math.max(1, ...tiles.map((t) => t.y + 1));
  const wide = Math.max(1, ...tiles.map((t) => t.x + 1));

  const draw = () => {
    raf.current = 0;
    const c = canvas.current;
    if (!c) return;
    const { w, h, dpr } = fitCanvas(c);
    const ctx = c.getContext('2d')!;
    const css = getComputedStyle(c);
    const fg = css.getPropertyValue('--text').trim() || '#111', mut = css.getPropertyValue('--muted').trim() || '#777', line = css.getPropertyValue('--line').trim() || '#ccc', bg = css.getPropertyValue('--surface-2').trim() || '#ddd';
    const v = view.current, k = v.k;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    // The axis: years, months or days depending on how many pixels a day takes.
    const gutter = 64;
    ctx.fillStyle = mut; ctx.strokeStyle = line; ctx.font = '600 11px system-ui, sans-serif';
    const unit = k < 0.9 ? 'year' : k < 14 ? 'month' : 'day';
    const d0 = Math.max(0, Math.floor((0 - v.y) / k) - 1), d1 = Math.min(span + 400, Math.ceil((h - v.y) / k) + 1);
    let lastLabel = '';
    for (let d = d0; d <= d1; d++) {
      const t = new Date(newest - d * DAY);
      const label = unit === 'year' ? yearFmt.format(t) : unit === 'month' ? monFmt.format(t) : dayFmt.format(t);
      if (label === lastLabel) continue;
      lastLabel = label;
      const y = d * k + v.y;
      ctx.beginPath(); ctx.moveTo(gutter - 6, y); ctx.lineTo(w, y); ctx.stroke();
      ctx.fillText(label, 6, y + 12);
    }
    const s = Math.max(2, k * 0.92);
    for (const t of tiles) {
      const sx = gutter + t.x * k + v.x, sy = t.y * k + v.y;
      if (sx > w || sy > h || sx + s < gutter - s || sy + s < 0) continue;
      ctx.fillStyle = bg; ctx.fillRect(sx, sy, s, s);
      if (s >= 12 && t.src) {
        const img = image(t.src, schedule);
        if (img) {
          const m = Math.min(img.naturalWidth, img.naturalHeight);
          ctx.drawImage(img, (img.naturalWidth - m) / 2, (img.naturalHeight - m) / 2, m, m, sx, sy, s, s);
        }
      }
      if (s >= 120) {
        ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(sx, sy + s - 22, s, 22);
        ctx.fillStyle = '#fff'; ctx.font = '600 12px system-ui, sans-serif';
        ctx.fillText(fmtShort(t.it.taken_at), sx + 6, sy + s - 7);
      }
      if (hover.current === t) { ctx.strokeStyle = fg; ctx.lineWidth = 3; ctx.strokeRect(sx + 1.5, sy + 1.5, s - 3, s - 3); ctx.strokeStyle = line; ctx.lineWidth = 1; }
    }
    placeVideo(s);
  };
  const schedule = () => { if (!raf.current) raf.current = requestAnimationFrame(draw); };
  const tileAt = (px: number, py: number) => {
    const v = view.current, s = Math.max(2, v.k * 0.92);
    for (const t of tiles) { const sx = 64 + t.x * v.k + v.x, sy = t.y * v.k + v.y; if (px >= sx && px <= sx + s && py >= sy && py <= sy + s) return t; }
    return null;
  };
  const placeVideo = (s: number) => {
    const el = vid.current, t = hover.current, v = view.current;
    if (!el) return;
    if (!t || !t.video || s < 56) { if (!el.paused) el.pause(); el.style.display = 'none'; return; }
    Object.assign(el.style, { display: 'block', left: `${64 + t.x * v.k + v.x}px`, top: `${t.y * v.k + v.y}px`, width: `${s}px`, height: `${s}px` });
    if (el.dataset.src !== t.video) { el.dataset.src = t.video; el.src = t.video; el.poster = t.src || ''; }
    claimPlayback(el);
    el.play().catch(() => undefined);
  };
  const fit = () => {
    const c = canvas.current!;
    const k = Math.max(0.05, Math.min((c.clientHeight - 20) / span, (c.clientWidth - 80) / wide));
    base.current = k;
    Object.assign(view.current, { k, x: 0, y: 10 });
    setZoom(1); schedule();
  };
  useEffect(() => {
    const c = canvas.current!;
    fit();
    const keep = savedViews.get('time');
    if (keep) { Object.assign(view.current, keep); setZoom(keep.k / base.current); schedule(); }
    const off = attachPanZoom(c, view.current, {
      min: base.current * 0.5, max: 400,
      onChange: () => { savedViews.set('time', { ...view.current }); setZoom(view.current.k / base.current); schedule(); },
      onTap: (x, y) => { const t = tileAt(x, y); if (t) navigate(hrefFor(t.it)); },
      onHover: (x, y) => { const t = tileAt(x, y); if (hover.current !== t) { hover.current = t; schedule(); } c.style.cursor = t ? 'pointer' : 'grab'; },
      onLeave: () => { hover.current = null; schedule(); },
    });
    const ro = new ResizeObserver(() => schedule());
    ro.observe(c);
    return () => { off(); ro.disconnect(); };
  }, [tiles]);
  const zoomBtn = (f: number) => { const c = canvas.current!; zoomBy(view.current, c.clientWidth, c.clientHeight, f, base.current * 0.5, 400); setZoom(view.current.k / base.current); schedule(); };
  const focusTile = (t: T) => {
    const c = canvas.current!;
    const k = Math.max(view.current.k, 160);
    view.current.k = k; view.current.x = c.clientWidth / 2 - 64 - t.x * k - k / 2; view.current.y = c.clientHeight / 2 - t.y * k - k / 2;
    hover.current = t; setZoom(k / base.current); schedule();
  };

  return (
    <section class="mosaic timeline-mode" aria-labelledby="tl-mode-h">
      <h2 id="tl-mode-h" class="mosaic-label fui">Timeline <span>newest at the top</span></h2>
      <ZoomCtl title="timeline" zoom={zoom} onIn={() => zoomBtn(1.8)} onOut={() => zoomBtn(1 / 1.8)} onFit={fit} />
      <div class="mosaic-box">
        <canvas ref={canvas} class="mosaic-canvas" aria-hidden="true" />
        <video ref={vid} class="mosaic-video" muted loop playsinline preload="none" aria-hidden="true" tabIndex={-1}
          onClick={() => hover.current && navigate(hrefFor(hover.current.it))} />
      </div>
      <ul class="mosaic-list" aria-label="Every video, newest first">
        {tiles.map((t) => <li key={t.it.id}><a href={hrefFor(t.it)} onFocus={() => focusTile(t)}>{fmtShort(t.it.taken_at)}: {t.it.summary || t.it.caption || ''}</a></li>)}
      </ul>
    </section>
  );
}
