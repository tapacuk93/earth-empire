import { render } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import './styles.css';
import { AppBanner } from './components/AppBanner';
import { Icon } from './components/icons';
import { SITE_NAME } from './config';
import { CategoryPage } from './pages/Category';
import { HighlightPage } from './pages/Highlight';
import { Home } from './pages/Home';
import { DetectedPage } from './pages/Detected';
import { OwnerOnly, OwnerToken, SettingsPage } from './pages/Settings';
import { StatusPage } from './pages/Status';
import { useOwner } from './live';
import { ItemPage } from './pages/Item';
import { NotFound } from './pages/NotFound';
import { useRoute } from './router';

type Theme = 'auto' | 'light' | 'dark';
function readTheme(): Theme { try { return (localStorage.getItem('theme') as Theme) || 'auto'; } catch { return 'auto'; } }

function ThemeToggle() {
  const [t, setT] = useState<Theme>(readTheme);
  useEffect(() => {
    const el = document.documentElement;
    if (t === 'auto') el.removeAttribute('data-theme'); else el.setAttribute('data-theme', t);
    try { localStorage.setItem('theme', t); } catch { /* private mode */ }
  }, [t]);
  const next: Theme = t === 'auto' ? 'dark' : t === 'dark' ? 'light' : 'auto';
  return (
    <button class="icon-btn theme" onClick={() => setT(next)} aria-label={`Theme: ${t}. Switch to ${next}.`} title={`Theme: ${t}`}>
      <Icon name={t === 'auto' ? 'auto' : t === 'dark' ? 'moon' : 'sun'} />
    </button>
  );
}

/**
 * The owner's hidden way in, as in the apps: on the footer's final dot, one tap, a pause, then three
 * quick taps opens the admin key prompt. The key is checked with GET /v1/admin/me and kept locally.
 */
function SecretDot() {
  const taps = useRef<number[]>([]);
  const [open, setOpen] = useState(false);
  const owner = useOwner();
  const tap = () => {
    const now = Date.now();
    const t = [...taps.current, now].filter((x) => now - x < 4000).slice(-4);
    taps.current = t;
    if (t.length === 4 && t[1] - t[0] >= 600 && t[2] - t[1] < 450 && t[3] - t[2] < 450) { taps.current = []; setOpen(true); }
  };
  return (
    <>
      <button type="button" class="secret-dot" onClick={tap} aria-label="." tabIndex={-1}>.</button>
      {open && !owner && <OwnerPrompt onClose={() => setOpen(false)} />}
    </>
  );
}

function OwnerPrompt({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return (
    <div class="prompt-back" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="prompt" role="dialog" aria-modal="true" aria-label="Admin key" onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
        <h2>Admin key</h2>
        <OwnerToken onChange={(ok) => { if (ok) setTimeout(onClose, 600); }} inputRef={ref} />
        <button class="btn small ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}

function decode(s: string) { try { return decodeURIComponent(s); } catch { return s; } }

const OWNER_ROUTES = ['detected', 'monitor', 'status', 'settings'];

function App() {
  const route = useRoute();
  const owner = useOwner();
  const seg = route.path.split('/').filter(Boolean).map(decode);
  const first = useRef(true);
  const mainRef = useRef<HTMLElement>(null);

  // On in-app navigation, move focus to the new page so screen readers start there.
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const h1 = mainRef.current?.querySelector('h1') as HTMLElement | null;
    const target = h1 || mainRef.current;
    if (target && seg[0] !== 'highlight' && seg[0] !== 'item') { target.setAttribute('tabindex', '-1'); target.focus({ preventScroll: true }); }
  }, [route.path]);

  if (seg[0] === 'highlight' && seg[1] && seg.length === 2) return <main id="main" ref={mainRef}><HighlightPage id={seg[1]} route={route} /></main>;

  let page;
  if (seg.length === 0) page = <Home route={route} />;
  else if (seg[0] === 'item' && seg[1] && seg.length === 2) page = <ItemPage id={seg[1]} route={route} />;
  else if (seg[0] === 'category' && seg[1] && seg.length === 2) page = <CategoryPage slug={seg[1]} route={route} />;
  else if ((seg[0] === 'detected' || seg[0] === 'monitor') && seg.length === 1) page = <OwnerOnly><DetectedPage route={route} /></OwnerOnly>;
  else if (seg[0] === 'status' && seg.length === 1) page = <OwnerOnly><StatusPage /></OwnerOnly>;
  else if (seg[0] === 'settings' && seg.length === 1) page = <SettingsPage />;
  else page = <NotFound />;

  return (
    <>
      <a class="skip" href="#main" onClick={(e) => { e.preventDefault(); mainRef.current?.focus(); }}>Skip to content</a>
      <header class="site-head">
        <a class="brand" href="/" aria-label={`${SITE_NAME}, home`}><span class="logo" aria-hidden="true" /><span class="brand-name">{SITE_NAME}</span></a>
        <span class="spacer" />
        {owner && (
          <nav class="site-nav" aria-label="Sections">
            {([['/', 'Home'], ['/detected', 'Detected'], ['/settings', 'Settings'], ['/status', 'Status']] as const).map(([href, label]) => {
              const here = href === '/' ? !OWNER_ROUTES.includes(seg[0] || '') : seg[0] === href.slice(1) || (href === '/detected' && seg[0] === 'monitor');
              return <a key={href} href={href} aria-current={here ? 'page' : undefined}>{label}</a>;
            })}
          </nav>
        )}
        <ThemeToggle />
      </header>
      <main id="main" ref={mainRef} tabIndex={-1}>{page}</main>
      <AppBanner route={route} />
      <footer class="site-foot">
        <p>An archive of an Instagram account. Every item is described by Claude; people are named only from what the post says<SecretDot />.</p>
      </footer>
    </>
  );
}

const root = document.getElementById('app')!;
root.textContent = '';
render(<App />, root);
