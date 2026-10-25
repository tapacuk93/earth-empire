import { useEffect, useState } from 'preact/hooks';
import { ANDROID_PACKAGE, APP_SCHEME, APP_STORE_URL, IOS_APP_ID, PLAY_STORE_URL, SITE_NAME } from '../config';
import type { Route } from '../router';
import { Icon } from './icons';

const KEY = 'ee-app-banner';
type Platform = 'ios' | 'android' | null;

export function platform(): Platform {
  const ua = navigator.userAgent;
  if (/Android/i.test(ua)) return 'android';
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'ios';
  return null; // desktop: never a banner
}
const isIosSafari = () => /Safari/.test(navigator.userAgent) && !/CriOS|FxiOS|EdgiOS|OPiOS|GSA\//.test(navigator.userAgent);

function dismissed(): boolean { try { return localStorage.getItem(KEY) === 'web'; } catch { return false; } }
function remember() { try { localStorage.setItem(KEY, 'web'); } catch { /* storage blocked: hide for this visit only */ } }

/** The app URL for the page on screen: an Android intent with a store fallback, or the iOS scheme. */
export function appUrl(p: Exclude<Platform, null>, loc: Location = location): string {
  const path = loc.pathname + loc.search;
  if (p === 'android') {
    const host = loc.hostname === 'localhost' ? 'empire.earth' : loc.host;
    return `intent://${host}${path}#Intent;scheme=https;package=${ANDROID_PACKAGE};S.browser_fallback_url=${encodeURIComponent(PLAY_STORE_URL)};end`;
  }
  return `${APP_SCHEME}:/${path === '/' ? '/' : path}`;
}

/** Keeps Safari's Smart App Banner pointing at this page (only when the App Store id is set). */
function useItunesMeta(route: Route) {
  useEffect(() => {
    if (!IOS_APP_ID) return;
    let m = document.head.querySelector<HTMLMetaElement>('meta[name="apple-itunes-app"]');
    if (!m) { m = document.createElement('meta'); m.name = 'apple-itunes-app'; document.head.appendChild(m); }
    m.content = `app-id=${IOS_APP_ID}, app-argument=${location.href}`;
  }, [route.path, route.query.toString()]);
}

/**
 * On phones and tablets, offers the same screen in the app. Desktop never sees it, and one
 * "Stay on the web" hides it for good. On iOS Safari with an App Store id, Safari's own banner
 * does this job, so this one stays away.
 */
export function AppBanner({ route }: { route: Route }) {
  useItunesMeta(route);
  const [p] = useState(platform);
  const [hidden, setHidden] = useState(dismissed);
  const ownBannerOnly = p === 'ios' && IOS_APP_ID && isIosSafari();
  if (!p || hidden || ownBannerOnly || route.path.startsWith('/highlight/')) return null;

  const open = (e: Event) => {
    if (p !== 'ios') return; // the intent URL falls back to the store by itself
    e.preventDefault();
    const started = Date.now();
    const fallback = window.setTimeout(() => {
      if (!document.hidden && Date.now() - started < 3000 && APP_STORE_URL) location.href = APP_STORE_URL;
    }, 1500);
    const cancel = () => { if (document.hidden) clearTimeout(fallback); };
    document.addEventListener('visibilitychange', cancel, { once: true });
    location.href = appUrl('ios');
  };

  return (
    <aside class={`app-banner ${route.path.startsWith('/item/') ? 'on-feed' : ''}`} aria-label="Open in the app">
      <span class="logo" aria-hidden="true" />
      <span class="app-banner-text"><b>{SITE_NAME}</b><span>Open this page in the app</span></span>
      <a class="btn small" href={appUrl(p)} onClick={open}>Open</a>
      <button class="icon-btn" aria-label="Stay on the web" title="Stay on the web" onClick={() => { remember(); setHidden(true); }}>
        <Icon name="close" size={18} />
      </button>
    </aside>
  );
}
