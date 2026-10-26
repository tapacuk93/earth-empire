import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { Icon } from '../components/icons';
import { HitMeta } from '../components/MonitorCard';
import { fetchMore, getHits, labelOf, setPublished, titleOf, type Hit } from '../monitor';
import { navigate, type Route } from '../router';

const isAudio = (url?: string | null) => /\.(mp3|m4a|aac|wav|ogg|opus)(\?|$)/i.test(url || '');
import { aiLevel, LEVEL_NAME } from '../sections';
import { prefersReducedMotion, setMeta } from '../util';
import { withParam } from './Home';

const KINDS: [string | undefined, string][] = [[undefined, 'All'], ['name', 'Names'], ['language', 'Language']];

/** "+" approves a hit for Home at the AI's level, which the owner may change first. */
function Approve({ h, onSet }: { h: Hit; onSet: (level: number | null) => void }) {
  const ai = aiLevel(h);
  const [lv, setLv] = useState(ai.level ?? 2);
  const on = !!h.published_at;
  const cur = (h as Hit & { level?: number | null }).level;
  return (
    <div class="addtwice">
      <p class="suggest">{ai.level ? <>AI level <b>{ai.level}</b></> : 'Not judged yet'}{ai.reason && <span> — {ai.reason}</span>}</p>
      {on ? (
        <>
          <span class="state-chip s-dedicated">On Home{cur ? ` · level ${cur}` : ''}</span>
          <button class="btn small ghost" onClick={() => onSet(null)}>Remove</button>
        </>
      ) : (
        <>
          <label class="sr-only" for={`lv-${h.id}`}>Level for this video</label>
          <select id={`lv-${h.id}`} class="sec-pick" value={lv} onChange={(e) => setLv(Number((e.target as HTMLSelectElement).value))}>
            {LEVEL_NAME.map((n, i) => <option key={i} value={i + 1}>{n}{i + 1 === ai.level ? ' (AI)' : ''}</option>)}
          </select>
          <button class="btn plus" onClick={() => onSet(lv)} aria-label={`Approve for Home at level ${lv}`}><b aria-hidden="true">+</b> Approve</button>
        </>
      )}
    </div>
  );
}

export function DetectedPage({ route }: { route: Route }) {
  const kind = route.query.get('kind') || undefined;
  const start = route.query.get('h') || undefined;
  const [hits, setHits] = useState<Hit[]>();
  const [next, setNext] = useState<string | null>(null);
  const [err, setErr] = useState<string>();
  const [msg, setMsg] = useState('');
  const [n, setN] = useState(10);
  const [cur, setCur] = useState(0);
  const [muted, setMuted] = useState(true);
  const wheel = useRef<HTMLDivElement>(null);
  // Slides start below the toolbar, so the clip is never under it: --bar is its bottom edge.
  const det = useRef<HTMLDivElement>(null), bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const b = bar.current, d = det.current;
    if (!b || !d) return;
    const set = () => d.style.setProperty('--bar', `${Math.ceil(b.getBoundingClientRect().bottom)}px`);
    const ro = new ResizeObserver(set);
    ro.observe(b);
    set();
    return () => ro.disconnect();
  }, []);
  const loading = useRef(false);
  useEffect(() => { setMeta('Detected', undefined, undefined, true); }, []);
  useEffect(() => {
    setHits(undefined); setErr(undefined); setCur(0);
    getHits({ kind }).then((p) => { setHits(p.hits); setNext(p.next); }, (e) => setErr(e.message));
  }, [kind]);
  useLayoutEffect(() => {
    if (!hits || !wheel.current) return;
    const i = start ? hits.findIndex((h) => h.id === start) : -1;
    if (i > 0) { wheel.current.scrollTop = i * wheel.current.clientHeight; setCur(i); }
  }, [!!hits]);

  const hit = hits?.[cur];
  useEffect(() => {
    if (hit) history.replaceState(history.state, '', withParam({ ...route, query: new URLSearchParams(location.search) }, 'h', hit.id));
    wheel.current?.querySelectorAll<HTMLVideoElement>('video').forEach((v) => {
      const mine = v.closest('.wslide')?.getAttribute('data-i') === String(cur);
      v.muted = muted;
      if (mine) v.play().catch(() => undefined); else if (!v.paused) v.pause();
    });
    if (hits && next && cur >= hits.length - 3 && !loading.current) {
      loading.current = true;
      getHits({ kind, before: next }).then((p) => { setHits((hs) => [...(hs || []), ...p.hits]); setNext(p.next); }, () => undefined).finally(() => { loading.current = false; });
    }
  }, [hit?.id, muted]);

  const go = (i: number) => {
    const el = wheel.current;
    if (!el || !hits) return;
    const c = Math.max(0, Math.min(hits.length - 1, i));
    el.scrollTo({ top: c * el.clientHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  };
  const onScroll = () => {
    const el = wheel.current;
    if (!el?.clientHeight) return;
    const i = Math.round(el.scrollTop / el.clientHeight);
    if (i !== cur) setCur(i);
  };
  const place = async (h: Hit, level: number | null) => {
    try {
      const r = await setPublished(h.id, level !== null, undefined, level ?? undefined);
      setHits((hs) => hs?.map((x) => (x.id === h.id ? { ...x, ...r, published_at: level ? r.published_at || new Date().toISOString() : null, level } as Hit : x)));
      setMsg(level ? `Approved for Home at level ${level}.` : 'Removed from Home.');
    } catch (e) { setMsg(`Could not change it: ${(e as Error).message}`); }
  };
  const fetchN = async (e: Event) => {
    e.preventDefault();
    setMsg(`Asking the monitor for ${n} more videos…`);
    try {
      const r = await fetchMore(n);
      setMsg(`Queued ${r.queued ?? n} videos to scan${r.to_discover ? `; ${r.to_discover} more to discover further back` : ''}.`);
    } catch (err) { setMsg(/429/.test((err as Error).message) ? 'The scan queue is full; try again later.' : `Could not ask for more: ${(err as Error).message}`); }
  };

  return (
    <div class="det" ref={det}>
      <div class="det-bar fui" ref={bar}>
        <h1 class="det-h">Detected</h1>
        <div class="kinds" role="group" aria-label="Kind of hit">
          {KINDS.map(([k, l]) => <button key={l} class="kind" aria-pressed={kind === k} onClick={() => navigate(withParam(route, 'kind', k), { replace: true })}>{l}</button>)}
        </div>
        {hits && <span class="muted small det-count">{hits.length ? `${cur + 1} / ${hits.length}${next ? '+' : ''} · ${labelOf(hits[cur])}` : ''}</span>}
        <form class="row fetch" onSubmit={fetchN}>
          <label for="fetch-n">Scan more</label>
          <input id="fetch-n" type="number" min={1} max={50} value={n} onInput={(e) => setN(Math.max(1, Math.min(50, Number((e.target as HTMLInputElement).value) || 1)))} />
          <button class="btn small" type="submit">Fetch {n} more</button>
        </form>
        <p class="muted small det-msg" role="status">{msg}</p>
      </div>
      {err ? <p class="error" role="alert">Could not load the hits: {err}</p>
        : !hits ? <p class="muted">Loading…</p>
        : !hits.length ? <p class="empty">Nothing detected yet. Fetch more to scan more videos.</p>
        : (
          <div class="wheel-wrap">
            <div class="wheel" ref={wheel} onScroll={onScroll} tabIndex={0} aria-label="Hits, most certain first. Swipe or use the arrow keys."
              onKeyDown={(e) => {
                const t = e.target as HTMLElement;
                if (t.tagName === 'BUTTON' || t.tagName === 'INPUT' || t.tagName === 'A') return;
                if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === 'j') { e.preventDefault(); go(cur + 1); }
                else if (e.key === 'ArrowUp' || e.key === 'PageUp' || e.key === 'k') { e.preventDefault(); go(cur - 1); }
                else if (e.key === 'm') setMuted(!muted);
              }}>
              {hits.map((h, i) => (
                <section key={h.id} class="wslide" data-i={i} aria-label={`${i + 1} of ${hits.length}: ${titleOf(h)}`} aria-hidden={i !== cur ? 'true' : undefined}>
                  {Math.abs(i - cur) <= 1 && (
                    <>
                      {/* A sound-only clip (the monitor's are mp3) shows its frame, whole, while it plays: a video element would go black */}
                      <div class={`wclip ${isAudio(h.clip) ? 'audio' : ''}`}>
                        {isAudio(h.clip) && (h.frame || h.video?.thumbnail) && <img src={h.frame || h.video?.thumbnail || undefined} alt="" decoding="async" />}
                        <video src={h.clip || undefined} poster={h.frame || h.video?.thumbnail || undefined} muted={muted} loop playsinline preload="none"
                          aria-label={`Clip around the moment: ${titleOf(h)}`} onClick={() => setMuted(!muted)} />
                      </div>
                      <div class="wover">
                        <HitMeta h={h} full fold />
                        <Approve h={h} onSet={(lv) => place(h, lv)} />
                      </div>
                    </>
                  )}
                </section>
              ))}
            </div>
            <div class="wheel-side fui">
              <button class="icon-btn" onClick={() => setMuted(!muted)} aria-label={muted ? 'Unmute' : 'Mute'} aria-pressed={!muted}><Icon name={muted ? 'mute' : 'sound'} /></button>
              <button class="icon-btn" onClick={() => go(cur - 1)} disabled={cur === 0} aria-label="Previous hit"><Icon name="left" class="up" /></button>
              <button class="icon-btn" onClick={() => go(cur + 1)} disabled={cur >= hits.length - 1} aria-label="Next hit"><Icon name="right" class="down" /></button>
            </div>
          </div>
        )}
    </div>
  );
}
