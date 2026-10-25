import { useEffect, useRef, useState } from 'preact/hooks';
import { getHighlightItems, getHighlights } from '../api';
import { Icon } from '../components/icons';
import { canGoBack, navigate, type Route } from '../router';
import type { Highlight, Item } from '../types';
import { altFor, cover, fmtShort, igProfile, posterOf, setMeta } from '../util';
import { NotFound } from './NotFound';

const IMAGE_MS = 5000;

export function HighlightPage({ id, route }: { id: string; route: Route }) {
  const [all, setAll] = useState<Highlight[]>();
  const [items, setItems] = useState<Item[]>();
  const [err, setErr] = useState<Error>();
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  const [held, setHeld] = useState(false);
  const [muted, setMuted] = useState(true);
  const fill = useRef<HTMLSpanElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const elapsed = useRef(0);
  const root = useRef<HTMLElement>(null);

  const h = all?.find((x) => x.id === id);
  const hi = all ? all.findIndex((x) => x.id === id) : -1;

  useEffect(() => { getHighlights().then(setAll, setErr); }, []);
  useEffect(() => {
    if (!h) return;
    let live = true;
    setItems(undefined);
    getHighlightItems(h).then((list) => {
      if (!live) return;
      setItems(list);
      const want = route.query.get('item');
      const at = want ? list.findIndex((x) => x.id === want) : -1;
      setI(at >= 0 ? at : 0);
      elapsed.current = 0;
    }, setErr);
    return () => { live = false; };
  }, [h?.id]);

  const item = items?.[i];
  const media = item ? (item.media[0] || item.repost_of?.media?.[0]) : undefined;
  const stopped = paused || held;

  useEffect(() => {
    if (h) setMeta(`${h.title} — highlight`, `The “${h.title}” highlight: ${h.item_ids.length} stor${h.item_ids.length === 1 ? 'y' : 'ies'}.`, h.cover || (item && cover(item)));
  }, [h?.id]);

  useEffect(() => { root.current?.focus({ preventScroll: true }); }, [!!h]);

  // Keep the address shareable: it names the story on screen.
  useEffect(() => {
    if (!item) return;
    const url = `/highlight/${encodeURIComponent(id)}?item=${encodeURIComponent(item.id)}`;
    if (location.pathname + location.search !== url) history.replaceState(history.state, '', url);
    // Warm the next one.
    const nx = items?.[i + 1];
    const nm = nx && (nx.media[0] || nx.repost_of?.media?.[0]);
    if (nm && nm.type === 'image') new Image().src = nm.url;
  }, [item?.id]);

  const close = () => (canGoBack() ? history.back() : navigate('/'));
  const goHighlight = (d: number) => {
    const t = all?.[hi + d];
    if (t) navigate(`/highlight/${encodeURIComponent(t.id)}`, { replace: true });
    else if (d > 0) close();
  };
  const go = (d: number) => {
    if (!items) return;
    const n = i + d;
    elapsed.current = 0;
    if (n < 0) { if (hi > 0) goHighlight(-1); else if (video.current) video.current.currentTime = 0; return; }
    if (n >= items.length) { goHighlight(1); return; }
    setI(n);
  };

  // The progress bar and the image timer.
  useEffect(() => {
    if (!media) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = now - last; last = now;
      let p = 0;
      if (media.type === 'video') {
        const v = video.current;
        p = v && v.duration ? v.currentTime / v.duration : 0;
      } else {
        if (!stopped && !document.hidden) elapsed.current += dt;
        p = elapsed.current / IMAGE_MS;
        if (p >= 1) { go(1); return; }
      }
      if (fill.current) fill.current.style.transform = `scaleX(${Math.min(1, p)})`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [media, stopped, i, items]);

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    if (stopped) v.pause(); else v.play().catch(() => setPaused(true));
  }, [stopped, item?.id]);

  // The key handler is attached once and reads the latest actions, so a key pressed right after a
  // tap never acts on the story before it.
  const actions = useRef({ go, goHighlight, close });
  actions.current = { go, goHighlight, close };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement;
      if ((t.tagName === 'A' || t.tagName === 'BUTTON') && (e.key === ' ' || e.key === 'Enter')) return;
      const a = actions.current;
      if (e.key === 'ArrowRight') { e.preventDefault(); e.shiftKey ? a.goHighlight(1) : a.go(1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); e.shiftKey ? a.goHighlight(-1) : a.go(-1); }
      else if (e.key === ' ' || e.key === 'k') { e.preventDefault(); setPaused((p) => !p); }
      else if (e.key === 'm') setMuted((m) => !m);
      else if (e.key === 'Escape') a.close();
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, []);

  // Tap left or right, hold to pause, swipe sideways for the next highlight, down to close.
  const ptr = useRef<{ x: number; y: number; t: number; hold?: number; held?: boolean } | null>(null);
  const onDown = (e: PointerEvent) => {
    if ((e.target as Element).closest('button, a') || e.button !== 0) return;
    const p = { x: e.clientX, y: e.clientY, t: Date.now(), hold: 0, held: false };
    p.hold = window.setTimeout(() => { p.held = true; setHeld(true); }, 220);
    ptr.current = p;
  };
  const onUp = (e: PointerEvent) => {
    const p = ptr.current;
    ptr.current = null;
    if (!p) return;
    clearTimeout(p.hold);
    setHeld(false);
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) { goHighlight(dx < 0 ? 1 : -1); return; }
    if (dy > 80 && dy > Math.abs(dx)) { close(); return; }
    if (p.held || Math.abs(dx) > 10 || Math.abs(dy) > 10) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    go(e.clientX - r.left < r.width * 0.3 ? -1 : 1);
  };

  if (err) return <div class="error" role="alert"><p>Could not load this highlight. {err.message}</p><p><a href="/">Back to Earth Empire</a></p></div>;
  if (all && !h) return <NotFound what="highlight" />;

  const r = item?.repost_of;
  return (
    <section class="story-viewer" ref={root} tabIndex={-1} aria-roledescription="viewer" aria-label={h ? `Highlight: ${h.title}` : 'Highlight'}>
      {media && <div class="story-backdrop" aria-hidden="true" style={{ backgroundImage: `url("${posterOf(media) || media.url}")` }} />}
      <div class="story-stage" onPointerDown={onDown} onPointerUp={onUp} onPointerCancel={() => { ptr.current = null; setHeld(false); }}
        onContextMenu={(e) => e.preventDefault()}>
        <div class="bars" aria-hidden="true">
          {(items || [null]).map((_, k) => (
            <span class="bar" key={k}><span class="bar-fill" ref={k === i ? fill : undefined} style={{ transform: `scaleX(${k < i ? 1 : 0})` }} /></span>
          ))}
        </div>
        <header class="story-top">
          {h?.cover && <img class="story-cover" src={h.cover} alt="" width={32} height={32} />}
          <h1 class="story-title">{h?.title || '…'}</h1>
          {item && <time class="story-date" dateTime={item.taken_at}>{fmtShort(item.taken_at)}</time>}
          <span class="spacer" />
          {media?.type === 'video' && (
            <button class="icon-btn" onClick={() => setMuted(!muted)} aria-label={muted ? 'Unmute' : 'Mute'} aria-pressed={!muted}>
              <Icon name={muted ? 'mute' : 'sound'} />
            </button>
          )}
          <button class="icon-btn" onClick={() => setPaused(!paused)} aria-label={paused ? 'Play' : 'Pause'}><Icon name={paused ? 'play' : 'pause'} /></button>
          <button class="icon-btn" onClick={close} aria-label="Close"><Icon name="close" /></button>
        </header>
        <p class="sr-only" role="status" aria-live="polite">{items && item ? `${i + 1} of ${items.length}, ${fmtShort(item.taken_at)}${paused ? ', paused' : ''}` : 'Loading…'}</p>
        <div class="story-media">
          {item && media && (media.type === 'video'
            ? <video key={item.id} ref={video} src={media.url} poster={posterOf(media)} muted={muted} playsinline autoplay
                preload="auto" onEnded={() => go(1)} aria-label={altFor(item, 0, media)} />
            : <img key={item.id} src={media.url} alt={altFor(item, 0, media)} draggable={false} />)}
          {!items && <span class="spinner" aria-hidden="true" />}
        </div>
        {item && (
          <footer class="story-bottom">
            {r && <p class="credit">Original by <a href={r.source_url || igProfile(r.author)} rel="external noopener">@{r.author}</a></p>}
            {item.summary && <p class="story-sum">{item.summary}</p>}
            <a class="btn small" href={`/item/${encodeURIComponent(item.id)}`}>Details</a>
          </footer>
        )}
        <button class="story-nav prev" onClick={() => go(-1)} aria-label="Previous"><Icon name="left" /></button>
        <button class="story-nav next" onClick={() => go(1)} aria-label="Next"><Icon name="right" /></button>
      </div>
      {all && all.length > 1 && (
        <nav class="story-others" aria-label="Other highlights">
          {all.map((x) => (
            <a key={x.id} href={`/highlight/${encodeURIComponent(x.id)}`} aria-current={x.id === id ? 'page' : undefined}
              onClick={(e) => { e.preventDefault(); navigate(`/highlight/${encodeURIComponent(x.id)}`, { replace: true }); }}>
              {x.cover ? <img src={x.cover} alt="" width={40} height={40} /> : null}<span>{x.title}</span>
            </a>
          ))}
        </nav>
      )}
    </section>
  );
}
