import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { Item } from '../types';
import { navigate } from '../router';
import { cover, fmtShort } from '../util';
import { attachPanZoom, claimPlayback, fitCanvas, image, savedViews, zoomBy, type View } from './zoom';
import { ZoomCtl } from './ZoomCtl';

interface T { it: Item; x: number; y: number; video?: string; src?: string }
const GUTTER = 44;     // the compact date axis
const GAP = 2;         // px between tiles
const monFmt = new Intl.DateTimeFormat('en', { month: 'short', year: '2-digit', timeZone: 'UTC' });
const dayFmt = new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const yearFmt = new Intl.DateTimeFormat('en', { year: 'numeric', timeZone: 'UTC' });

/**
 * Every video along time, newest at the top: one row per day that has videos (no empty rows),
 * tiles large enough to recognise at the first view (about a third of a phone's width). Busy days
 * run off to the right and pan sideways. Zooming out shrinks the tiles and the axis turns from days
 * to months to years.
 */
export function TimelineView({ items, hrefFor }: { items: Item[]; hrefFor: (it: Item) => string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const vid = useRef<HTMLVideoElement>(null);
  const view = useRef<View>({ k: 1, x: 0, y: 0 });
  const base = useRef(1);
  const raf = useRef(0);
  const hover = useRef<T | null>(null);
  const [zoom, setZoom] = useState(1);
  const { tiles, rows, wide } = useMemo(() => {
    const days: string[] = [];
    const per = new Map<string, number>();
    const tiles = items.map((it) => {
      const day = it.taken_at.slice(0, 10);
      if (!per.has(day)) { per.set(day, 0); days.push(day); }
      const n = per.get(day)!;
      per.set(day, n + 1);
      const m = it.media[0] || it.repost_of?.media?.[0];
      return { it, x: n, y: days.length - 1, video: m?.type === 'video' ? m.url : undefined, src: cover(it) } as T;
    });
    return { tiles, rows: days, wide: Math.max(1, ...per.values()) };
  }, [items]);

  const clamp = () => {
    const c = canvas.current;
    if (!c) return;
    const v = view.current, w = c.clientWidth - GUTTER, h = c.clientHeight;
    v.x = Math.min(0, Math.max(Math.min(0, w - wide * v.k), v.x));
    v.y = Math.min(8, Math.max(Math.min(8, h - rows.length * v.k - 8), v.y));
  };

  const draw = () => {
    raf.current = 0;
    const c = canvas.current;
    if (!c) return;
    const { w, h, dpr } = fitCanvas(c);
    if (!w || !h) return;
    clamp();
    const ctx = c.getContext('2d')!;
    const css = getComputedStyle(c);
    const fg = css.getPropertyValue('--text').trim() || '#111', mut = css.getPropertyValue('--muted').trim() || '#777', line = css.getPropertyValue('--line').trim() || '#ccc', bg = css.getPropertyValue('--surface-2').trim() || '#ddd';
    const v = view.current, k = v.k;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const s = k - GAP;
    for (const t of tiles) {
      const sx = GUTTER + t.x * k + v.x, sy = t.y * k + v.y;
      if (sx > w || sy > h || sx + s < GUTTER || sy + s < 0) continue;
      ctx.fillStyle = bg; ctx.fillRect(sx, sy, s, s);
      if (s >= 10 && t.src) {
        const img = image(t.src, schedule);
        if (img) { const m = Math.min(img.naturalWidth, img.naturalHeight); ctx.drawImage(img, (img.naturalWidth - m) / 2, (img.naturalHeight - m) / 2, m, m, sx, sy, s, s); }
      }
      if (s >= 110) {
        ctx.fillStyle = 'rgba(0,0,0,.55)'; ctx.fillRect(sx, sy + s - 22, s, 22);
        ctx.fillStyle = '#fff'; ctx.font = '600 12px system-ui, sans-serif';
        ctx.fillText(fmtShort(t.it.taken_at), sx + 6, sy + s - 7);
      }
      if (hover.current === t) { ctx.strokeStyle = fg; ctx.lineWidth = 3; ctx.strokeRect(sx + 1.5, sy + 1.5, s - 3, s - 3); }
    }
    // The axis covers the tiles that slide under it.
    ctx.fillStyle = css.getPropertyValue('--bg').trim() || '#fff';
    ctx.fillRect(0, 0, GUTTER - 2, h);
    ctx.strokeStyle = line; ctx.lineWidth = 1; ctx.fillStyle = mut; ctx.font = '600 10px system-ui, sans-serif';
    const unit = k >= 50 ? 'day' : k >= 8 ? 'month' : 'year';
    let last = '';
    rows.forEach((day, i) => {
      const y = i * k + v.y;
      const d = new Date(day + 'T00:00:00Z');
      const label = unit === 'day' ? dayFmt.format(d) : unit === 'month' ? monFmt.format(d) : yearFmt.format(d);
      if (label === last || y < -k || y > h) { last = label; return; }
      last = label;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(GUTTER - 6, y); ctx.stroke();
      ctx.fillText(label, 4, y + 12);
    });
    void fg;
    placeVideo(s);
  };
  const schedule = () => { if (!raf.current) raf.current = requestAnimationFrame(draw); };
  const tileAt = (px: number, py: number) => {
    const v = view.current, s = v.k - GAP;
    if (px < GUTTER) return null;
    for (const t of tiles) { const sx = GUTTER + t.x * v.k + v.x, sy = t.y * v.k + v.y; if (px >= sx && px <= sx + s && py >= sy && py <= sy + s) return t; }
    return null;
  };
  const placeVideo = (s: number) => {
    const el = vid.current, t = hover.current, v = view.current;
    if (!el) return;
    if (!t || !t.video || s < 56) { if (!el.paused) el.pause(); el.style.display = 'none'; return; }
    Object.assign(el.style, { display: 'block', left: `${GUTTER + t.x * v.k + v.x}px`, top: `${t.y * v.k + v.y}px`, width: `${s}px`, height: `${s}px` });
    if (el.dataset.src !== t.video) { el.dataset.src = t.video; el.classList.remove('on'); el.src = t.video; el.poster = t.src || ''; }
    claimPlayback(el);
    el.play().catch(() => undefined);
  };
  /** First view: tiles about a third of a phone's width, a fifth of a wide screen's, never fewer than one per row. */
  const fit = () => {
    const c = canvas.current!;
    const w = c.clientWidth - GUTTER;
    const k = Math.max(110, Math.min(w, w / (c.clientWidth < 700 ? 2.6 : c.clientWidth < 1400 ? 4 : 5.5)));
    base.current = k;
    Object.assign(view.current, { k, x: 0, y: 8 });
    setZoom(1); schedule();
  };
  const minK = () => { const c = canvas.current!; return Math.max(2, Math.min(base.current, (c.clientHeight - 16) / rows.length, (c.clientWidth - GUTTER) / wide) * 0.9); };
  useEffect(() => {
    const c = canvas.current!;
    fit();
    const keep = savedViews.get('time');
    if (keep) { Object.assign(view.current, keep); setZoom(keep.k / base.current); schedule(); }
    const off = attachPanZoom(c, view.current, {
      min: minK(), max: 600,
      onChange: () => { clamp(); savedViews.set('time', { ...view.current }); setZoom(view.current.k / base.current); schedule(); },
      onTap: (x, y) => { const t = tileAt(x, y); if (t) navigate(hrefFor(t.it)); },
      onHover: (x, y) => { const t = tileAt(x, y); if (hover.current !== t) { hover.current = t; schedule(); } c.style.cursor = t ? 'pointer' : 'grab'; },
      onLeave: () => { hover.current = null; schedule(); },
    });
    const ro = new ResizeObserver(() => schedule());
    ro.observe(c);
    return () => { off(); ro.disconnect(); if (raf.current) cancelAnimationFrame(raf.current); raf.current = 0; };
  }, [tiles]);
  const zoomBtn = (f: number) => { const c = canvas.current!; zoomBy(view.current, c.clientWidth, c.clientHeight, f, minK(), 600); clamp(); savedViews.set('time', { ...view.current }); setZoom(view.current.k / base.current); schedule(); };
  const focusTile = (t: T) => {
    const c = canvas.current!;
    const k = Math.max(view.current.k, base.current);
    Object.assign(view.current, { k, x: Math.min(0, (c.clientWidth - GUTTER) / 2 - t.x * k - k / 2), y: c.clientHeight / 2 - t.y * k - k / 2 });
    hover.current = t; clamp(); setZoom(k / base.current); schedule();
  };

  return (
    <section class="mosaic timeline-mode" aria-labelledby="tl-mode-h">
      <h2 id="tl-mode-h" class="mosaic-label fui">Timeline <span>newest at the top</span></h2>
      <ZoomCtl title="timeline" zoom={zoom} onIn={() => zoomBtn(1.6)} onOut={() => zoomBtn(1 / 1.6)} onFit={fit} />
      <div class="mosaic-box">
        <canvas ref={canvas} class="mosaic-canvas" aria-hidden="true" data-tile={String(Math.round(view.current.k - GAP))} />
        <video ref={vid} class="mosaic-video" muted loop playsinline preload="none" aria-hidden="true" tabIndex={-1}
          onPlaying={(e) => (e.currentTarget as HTMLVideoElement).classList.add('on')} />
      </div>
      <ul class="mosaic-list" aria-label="Every video, newest first">
        {tiles.map((t) => <li key={t.it.id}><a href={hrefFor(t.it)} onFocus={() => focusTile(t)}>{fmtShort(t.it.taken_at)}: {t.it.summary || t.it.caption || ''}</a></li>)}
      </ul>
    </section>
  );
}
