// Videos on screen start loading quietly, so opening one starts at once: a tile that stays in view
// for a moment gets a hidden <video preload="auto"> of its file (the browser's media cache serves
// the player later). A few at a time, the most recent kept; nothing on Save-Data or a slow link.

const KEEP = 6;
const AT_ONCE = 3;
const kept = new Map<string, HTMLVideoElement>();
let box: HTMLDivElement | null = null;

function slow(): boolean {
  const c = (navigator as { connection?: { saveData?: boolean; effectiveType?: string } }).connection;
  return !!c && (c.saveData === true || /(^|-)2g$|^3g$/.test(c.effectiveType || ''));
}

function loading(): number {
  let n = 0;
  kept.forEach((v) => { if (v.readyState < 3) n++; });
  return n;
}

export function preloadVideo(url: string): void {
  if (!url || slow() || typeof document === 'undefined') return;
  const have = kept.get(url);
  if (have) { kept.delete(url); kept.set(url, have); return; }   // most recent last
  if (loading() >= AT_ONCE) return;
  if (!box) {
    box = document.createElement('div');
    box.setAttribute('aria-hidden', 'true');
    box.style.cssText = 'position:fixed;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none;left:-10px;top:-10px';
    document.body.appendChild(box);
  }
  const v = document.createElement('video');
  v.muted = true; v.preload = 'auto'; v.playsInline = true; v.src = url;
  box.appendChild(v);
  kept.set(url, v);
  while (kept.size > KEEP) {
    const [old, el] = kept.entries().next().value as [string, HTMLVideoElement];
    el.removeAttribute('src'); el.load(); el.remove();
    kept.delete(old);
  }
}

/** Watch the tiles under `root` (elements with data-video): one that stays in view 500 ms preloads. */
export function watchTiles(root: HTMLElement): () => void {
  if (typeof IntersectionObserver === 'undefined') return () => undefined;
  const timers = new Map<Element, number>();
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const url = (e.target as HTMLElement).dataset.video;
      if (!url) continue;
      if (e.isIntersecting) timers.set(e.target, window.setTimeout(() => preloadVideo(url), 500));
      else { clearTimeout(timers.get(e.target)); timers.delete(e.target); }
    }
  }, { threshold: 0.6 });
  const scan = () => root.querySelectorAll('[data-video]').forEach((el) => io.observe(el));
  scan();
  const mo = new MutationObserver(scan);
  mo.observe(root, { childList: true, subtree: true });
  return () => { io.disconnect(); mo.disconnect(); timers.forEach((t) => clearTimeout(t)); };
}
