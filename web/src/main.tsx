import { render } from 'preact';
import { useEffect, useRef } from 'preact/hooks';
import './styles.css';
import './idle';
import { AppBanner } from './components/AppBanner';
import { SecretDot, ThemeToggle } from './components/Chrome';
import { SITE_NAME } from './config';
import { CategoryRedirect } from './pages/CategoryRedirect';
import { HighlightPage } from './pages/Highlight';
import { Home } from './pages/Home';
import { DetectedPage } from './pages/Detected';
import { OwnerOnly, SettingsPage } from './pages/Settings';
import { StatusPage } from './pages/Status';
import { useOwner } from './live';
import { ItemPage } from './pages/Item';
import { NotFound } from './pages/NotFound';
import { useRoute } from './router';

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

  const nav = owner && (
    <nav class="site-nav" aria-label="Sections">
      {([['/', 'Home'], ['/detected', 'Detected'], ['/settings', 'Settings'], ['/status', 'Status']] as const).map(([href, label]) => {
        const here = href === '/' ? !OWNER_ROUTES.includes(seg[0] || '') : seg[0] === href.slice(1) || (href === '/detected' && seg[0] === 'monitor');
        return <a key={href} href={href} aria-current={here ? 'page' : undefined}>{label}</a>;
      })}
    </nav>
  );

  // Home is fullscreen: no header or footer, only small floating controls over the canvases.
  if (seg.length === 0) {
    return (
      <>
        <a class="skip" href="#main" onClick={(e) => { e.preventDefault(); mainRef.current?.focus(); }}>Skip to content</a>
        <main id="main" ref={mainRef} tabIndex={-1} class="home-main"><Home route={route} /></main>
        <div class="float-tools fui">{nav}<ThemeToggle /></div>
        <span class="corner-dot"><SecretDot /></span>
        <AppBanner route={route} />
      </>
    );
  }

  let page;
  if (seg[0] === 'item' && seg[1] && seg.length === 2) page = <ItemPage id={seg[1]} route={route} />;
  else if (seg[0] === 'category' && seg[1] && seg.length === 2) page = <CategoryRedirect slug={seg[1]} />;
  else if ((seg[0] === 'detected' || seg[0] === 'monitor') && seg.length === 1) page = <OwnerOnly><DetectedPage route={route} /></OwnerOnly>;
  else if (seg[0] === 'status' && seg.length === 1) page = <OwnerOnly><StatusPage /></OwnerOnly>;
  else if (seg[0] === 'settings' && seg.length === 1) page = <SettingsPage />;
  else page = <NotFound />;

  // Every screen is fullscreen; the only chrome is small floating controls.
  return (
    <>
      <a class="skip" href="#main" onClick={(e) => { e.preventDefault(); mainRef.current?.focus(); }}>Skip to content</a>
      <main id="main" ref={mainRef} tabIndex={-1} class="page-full">{page}</main>
      <a class="float-home fui" href="/" aria-label={`${SITE_NAME}, home`}><span class="logo" aria-hidden="true" /></a>
      <div class="float-tools fui">{nav}<ThemeToggle /></div>
      <span class="corner-dot"><SecretDot /></span>
      <AppBanner route={route} />
    </>
  );
}

const root = document.getElementById('app')!;
root.textContent = '';
render(<App />, root);
