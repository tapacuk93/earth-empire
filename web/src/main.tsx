import { render } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import './styles.css';
import { AppBanner } from './components/AppBanner';
import { Icon } from './components/icons';
import { SITE_NAME } from './config';
import { CategoryPage } from './pages/Category';
import { HighlightPage } from './pages/Highlight';
import { Home } from './pages/Home';
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

function decode(s: string) { try { return decodeURIComponent(s); } catch { return s; } }

function App() {
  const route = useRoute();
  const seg = route.path.split('/').filter(Boolean).map(decode);
  const first = useRef(true);
  const mainRef = useRef<HTMLElement>(null);

  // On in-app navigation, move focus to the new page so screen readers start there.
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const h1 = mainRef.current?.querySelector('h1') as HTMLElement | null;
    const target = h1 || mainRef.current;
    if (target && seg[0] !== 'highlight') { target.setAttribute('tabindex', '-1'); target.focus({ preventScroll: true }); }
  }, [route.path]);

  if (seg[0] === 'highlight' && seg[1] && seg.length === 2) return <main id="main" ref={mainRef}><HighlightPage id={seg[1]} route={route} /></main>;

  let page;
  if (seg.length === 0) page = <Home route={route} />;
  else if (seg[0] === 'item' && seg[1] && seg.length === 2) page = <ItemPage id={seg[1]} />;
  else if (seg[0] === 'category' && seg[1] && seg.length === 2) page = <CategoryPage slug={seg[1]} route={route} />;
  else page = <NotFound />;

  return (
    <>
      <a class="skip" href="#main" onClick={(e) => { e.preventDefault(); mainRef.current?.focus(); }}>Skip to content</a>
      <header class="site-head">
        <a class="brand" href="/" aria-label={`${SITE_NAME}, home`}><span class="logo" aria-hidden="true" />{SITE_NAME}</a>
        <span class="spacer" />
        <ThemeToggle />
      </header>
      <main id="main" ref={mainRef} tabIndex={-1}>{page}</main>
      <AppBanner route={route} />
      <footer class="site-foot">
        <p>An archive of an Instagram account. Every item is described by Claude; people are named only from what the post says.</p>
      </footer>
    </>
  );
}

const root = document.getElementById('app')!;
root.textContent = '';
render(<App />, root);
