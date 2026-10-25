// A tiny pan/zoom controller for a canvas, like a map: drag, wheel, pinch.
// On touch screens one finger scrolls the page vertically (so the page never traps you), a
// horizontal one-finger drag pans, and two fingers pan and zoom. On a mouse, the wheel zooms
// once the canvas is active (clicked), or always with Ctrl/⌘ (which is also a trackpad pinch).

export interface View { k: number; x: number; y: number }   // screen = world * k + (x, y)

export interface PanZoomOptions {
  min: number; max: number;
  onChange: () => void;
  onTap: (sx: number, sy: number) => void;
  onHover?: (sx: number, sy: number) => void;
  onLeave?: () => void;
}

export function attachPanZoom(el: HTMLElement, view: View, o: PanZoomOptions): () => void {
  const pts = new Map<number, { x: number; y: number }>();
  let start: { x: number; y: number; t: number } | null = null;
  let moved = false;
  let pinch: { d: number; mx: number; my: number } | null = null;
  let active = false;
  const local = (e: { clientX: number; clientY: number }) => { const r = el.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };

  const zoomAt = (sx: number, sy: number, f: number) => {
    const k = Math.max(o.min, Math.min(o.max, view.k * f));
    const r = k / view.k;
    view.x = sx - (sx - view.x) * r;
    view.y = sy - (sy - view.y) * r;
    view.k = k;
    o.onChange();
  };

  const down = (e: PointerEvent) => {
    el.setPointerCapture?.(e.pointerId);
    const p = local(e);
    pts.set(e.pointerId, p);
    if (pts.size === 1) { start = { ...p, t: Date.now() }; moved = false; }
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
      moved = true;
    }
  };
  const move = (e: PointerEvent) => {
    const p = local(e);
    if (!pts.has(e.pointerId)) { if (e.pointerType === 'mouse') o.onHover?.(p.x, p.y); return; }
    const prev = pts.get(e.pointerId)!;
    pts.set(e.pointerId, p);
    if (pts.size === 2 && pinch) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      view.x += mx - pinch.mx; view.y += my - pinch.my;
      zoomAt(mx, my, d / (pinch.d || d));
      pinch = { d, mx, my };
      return;
    }
    if (start && Math.hypot(p.x - start.x, p.y - start.y) > 6) moved = true;
    if (moved) { view.x += p.x - prev.x; view.y += p.y - prev.y; o.onChange(); }
  };
  const up = (e: PointerEvent) => {
    const p = local(e);
    if (pts.size === 1 && start && !moved && Date.now() - start.t < 600) { active = true; o.onTap(p.x, p.y); }
    pts.delete(e.pointerId);
    if (pts.size < 2) pinch = null;
    if (!pts.size) start = null;
  };
  const cancel = (e: PointerEvent) => { pts.delete(e.pointerId); pinch = null; if (!pts.size) start = null; };
  const wheel = (e: WheelEvent) => {
    if (!active && !e.ctrlKey && !e.metaKey) return; // let the page scroll
    e.preventDefault();
    const p = local(e);
    zoomAt(p.x, p.y, Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018)));
  };
  const leave = () => { active = false; o.onLeave?.(); };
  // Safari's own pinch events: keep the page from zooming while pinching the canvas.
  const gesture = (e: Event) => e.preventDefault();

  el.addEventListener('pointerdown', down);
  el.addEventListener('pointermove', move);
  el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', cancel);
  el.addEventListener('pointerleave', leave);
  el.addEventListener('wheel', wheel, { passive: false });
  el.addEventListener('gesturestart', gesture);
  el.addEventListener('gesturechange', gesture);
  return () => {
    el.removeEventListener('pointerdown', down);
    el.removeEventListener('pointermove', move);
    el.removeEventListener('pointerup', up);
    el.removeEventListener('pointercancel', cancel);
    el.removeEventListener('pointerleave', leave);
    el.removeEventListener('wheel', wheel);
    el.removeEventListener('gesturestart', gesture);
    el.removeEventListener('gesturechange', gesture);
  };
}

export function zoomBy(view: View, w: number, h: number, f: number, min: number, max: number) {
  const k = Math.max(min, Math.min(max, view.k * f));
  const r = k / view.k;
  view.x = w / 2 - (w / 2 - view.x) * r;
  view.y = h / 2 - (h / 2 - view.y) * r;
  view.k = k;
}

/** Sizes a canvas to its box at the device pixel ratio; returns the CSS size. */
export function fitCanvas(c: HTMLCanvasElement): { w: number; h: number; dpr: number } {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = c.clientWidth, h = c.clientHeight;
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
  return { w, h, dpr };
}

// Thumbnails, loaded only when a tile is big enough on screen, a few at a time.
const cache = new Map<string, { img: HTMLImageElement; ok: boolean }>();
let inflight = 0;
const queue: [string, () => void][] = [];
function pump() {
  while (inflight < 6 && queue.length) {
    const [url, done] = queue.shift()!;
    const img = new Image();
    img.decoding = 'async';
    const entry = { img, ok: false };
    cache.set(url, entry);
    inflight++;
    img.onload = () => { entry.ok = true; inflight--; done(); pump(); };
    img.onerror = () => { inflight--; pump(); };
    img.src = url;
  }
}
export function image(url: string, onLoad: () => void): HTMLImageElement | null {
  const e = cache.get(url);
  if (e) return e.ok ? e.img : null;
  if (!queue.some(([u]) => u === url)) { queue.push([url, onLoad]); pump(); }
  return null;
}

// At most one video plays on the whole page.
let playing: HTMLVideoElement | null = null;
export function claimPlayback(v: HTMLVideoElement) { if (playing && playing !== v) playing.pause(); playing = v; }

/** Views survive leaving Home and coming back (the wheel's Close returns to the same spot). */
export const savedViews = new Map<string, View>();
let modesTop = 0;
export const saveModesTop = (y: number) => { modesTop = y; };
export const modesTopSaved = () => modesTop;
