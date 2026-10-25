import { useEffect, useState } from 'preact/hooks';

export interface Route { path: string; query: URLSearchParams; key: number }

let current: Route = read();
let key = 0;
const listeners = new Set<(r: Route) => void>();
let pendingScroll: number | null = null;

function read(): Route { return { path: location.pathname, query: new URLSearchParams(location.search), key: key }; }
function emit() { current = read(); listeners.forEach((l) => l(current)); }

if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

export function navigate(to: string, opts: { replace?: boolean; keepScroll?: boolean } = {}) {
  const url = new URL(to, location.href);
  if (url.href === location.href && !opts.replace) return;
  if (opts.replace) {
    history.replaceState({ ...(history.state || {}) }, '', url);
  } else {
    history.replaceState({ ...(history.state || {}), scrollY: window.scrollY }, '', location.href);
    history.pushState({ scrollY: 0 }, '', url);
    key++;
    if (!opts.keepScroll) pendingScroll = 0;
  }
  emit();
}

addEventListener('popstate', (e) => {
  key++;
  pendingScroll = (e.state && typeof e.state.scrollY === 'number') ? e.state.scrollY : 0;
  emit();
});

/** Pages call this once their content is on screen, to restore the scroll a back/forward left. */
export function settleScroll() {
  if (pendingScroll === null) return;
  const y = pendingScroll;
  pendingScroll = null;
  requestAnimationFrame(() => window.scrollTo(0, y));
}

/** Whether there is an in-app page to go back to. */
export const canGoBack = () => key > 0;

export function useRoute(): Route {
  const [r, set] = useState(current);
  useEffect(() => { listeners.add(set); set(current); return () => { listeners.delete(set); }; }, []);
  return r;
}

// Same-origin links navigate in place.
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = (e.target as Element).closest?.('a');
  if (!a || a.target || a.hasAttribute('download') || a.getAttribute('rel')?.includes('external')) return;
  const href = a.getAttribute('href');
  if (!href || href.startsWith('#')) return;
  const url = new URL(href, location.href);
  if (url.origin !== location.origin || url.pathname.startsWith('/mock/')) return;
  e.preventDefault();
  navigate(url.pathname + url.search + url.hash);
});
