import { useEffect, useRef, useState } from 'preact/hooks';
import { getItems } from '../api';
import type { Item, ItemQuery } from '../types';
import { settleScroll } from '../router';
import { altFor, cover, fmtDate, fmtShort, KIND_LABEL } from '../util';
import { Icon } from './icons';
import { itemHref } from '../context';

interface State { items: Item[]; next: string | null; done: boolean; error?: string }
// Lists already loaded, so going back to one shows it at once, as far as it was scrolled.
const memo = new Map<string, State>();
const PAGE = 24;

export function Feed({ query, emptyText = 'Nothing here yet.', layout = 'grid', ctx = 'all' }: { query: ItemQuery; emptyText?: string; layout?: 'grid' | 'timeline'; ctx?: string }) {
  const key = JSON.stringify(query);
  const [st, setSt] = useState<State>(() => memo.get(key) || { items: [], next: null, done: false });
  const [loading, setLoading] = useState(false);
  const keyRef = useRef(key);
  const sentinel = useRef<HTMLDivElement>(null);
  const inFlight = useRef<string | null>(null); // the list key being loaded, so a page is never fetched twice

  const load = async (reset: boolean) => {
    const k = key;
    const prev = reset ? { items: [], next: null, done: false } : (memo.get(k) || st);
    if (!reset && (prev.done || inFlight.current === k)) return;
    inFlight.current = k;
    setLoading(true);
    try {
      const page = await getItems({ ...query, limit: PAGE, before: reset ? undefined : prev.next || undefined });
      if (keyRef.current !== k) return;
      const next: State = { items: [...prev.items, ...page.items], next: page.next, done: !page.next };
      memo.set(k, next);
      setSt(next);
    } catch (e) {
      if (keyRef.current === k) setSt({ ...prev, error: (e as Error).message || 'Could not load' });
    } finally {
      if (inFlight.current === k) inFlight.current = null;
      if (keyRef.current === k) setLoading(false);
    }
  };

  useEffect(() => {
    keyRef.current = key;
    const m = memo.get(key);
    if (m) { setSt(m); setLoading(false); settleScroll(); }
    else { setSt({ items: [], next: null, done: false }); load(true); }
  }, [key]);

  useEffect(() => { if (st.items.length) settleScroll(); }, [st.items.length > 0]);

  useEffect(() => {
    const el = sentinel.current;
    if (!el || st.done || st.error || !('IntersectionObserver' in window)) return;
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) load(false); }, { rootMargin: '800px 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, [st, loading]);

  const status = loading && !st.items.length ? 'Loading…'
    : st.done && !st.items.length ? emptyText
    : `${st.items.length}${st.done ? '' : '+'} item${st.items.length === 1 ? '' : 's'}`;

  return (
    <section class="feed" aria-label="Items" aria-busy={loading}>
      <p class="sr-only" role="status" aria-live="polite">{status}</p>
      {st.items.length > 0 && (layout === 'timeline' ? <Timeline items={st.items} ctx={ctx} /> : (
        <ul class="grid" role="list">
          {st.items.map((it, i) => <Tile key={it.id} item={it} eager={i < 6} />)}
        </ul>
      ))}
      {loading && !st.items.length && <SkeletonGrid />}
      {st.done && !st.items.length && !loading && <p class="empty">{emptyText}</p>}
      {st.error && (
        <div class="error" role="alert">
          <p>Could not load items. {st.error}</p>
          <button class="btn" onClick={() => { setSt({ ...st, error: undefined }); load(!st.items.length); }}>Try again</button>
        </div>
      )}
      {!st.done && !st.error && st.items.length > 0 && (
        <div ref={sentinel} class="more">
          <button class="btn" onClick={() => load(false)} disabled={loading}>{loading ? 'Loading…' : 'Load more'}</button>
        </div>
      )}
    </section>
  );
}

function SkeletonGrid() {
  return <ul class="grid skeleton" aria-hidden="true">{Array.from({ length: 12 }, (_, i) => <li key={i} class="tile"><span /></li>)}</ul>;
}

export function Tile({ item, eager }: { item: Item; eager?: boolean }) {
  const src = cover(item);
  const isVideo = item.media[0]?.type === 'video' || (!item.media.length && item.repost_of?.media?.[0]?.type === 'video');
  const badge = item.repost_of ? 'repost' : item.kind === 'carousel' ? 'carousel' : item.kind === 'reel' ? 'reel' : item.kind === 'story' ? 'story' : isVideo ? 'reel' : null;
  const label = `${KIND_LABEL[item.kind] || 'Item'}${item.repost_of ? `, sharing @${item.repost_of.author}` : ''}, ${fmtShort(item.taken_at)}`;
  return (
    <li class="tile">
      <a href={`/item/${encodeURIComponent(item.id)}`} aria-label={`${label}: ${item.summary || item.caption || ''}`.slice(0, 300)}>
        {src ? <img src={src} alt={altFor(item, 0, item.media[0])} loading={eager ? 'eager' : 'lazy'} decoding="async" width={360} height={360} />
          : <span class="tile-text">{item.caption || item.summary}</span>}
        {badge && <span class="badge"><Icon name={badge as 'repost'} size={18} /></span>}
        <span class="tile-hover" aria-hidden="true">
          <span class="tile-kind">{KIND_LABEL[item.kind]} · {fmtShort(item.taken_at)}</span>
          {item.summary && <span class="tile-sum">{item.summary}</span>}
        </span>
      </a>
    </li>
  );
}

const monthFmt = new Intl.DateTimeFormat('en', { month: 'long', year: 'numeric', timeZone: 'UTC' });

/** Everything in date order, newest first, grouped by month. */
function Timeline({ items, ctx }: { items: Item[]; ctx: string }) {
  const groups: { key: string; label: string; items: Item[] }[] = [];
  for (const it of items) {
    const d = new Date(it.taken_at);
    const key = isNaN(+d) ? 'unknown' : `${d.getUTCFullYear()}-${d.getUTCMonth()}`;
    let g = groups[groups.length - 1];
    if (!g || g.key !== key) groups.push(g = { key, label: isNaN(+d) ? 'Undated' : monthFmt.format(d), items: [] });
    g.items.push(it);
  }
  return (
    <div class="tl">
      {groups.map((g) => (
        <section key={g.key} class="tl-month" aria-labelledby={`m-${g.key}`}>
          <h2 id={`m-${g.key}`} class="tl-h">{g.label}</h2>
          <ol class="tl-list">
            {g.items.map((it) => {
              const src = cover(it);
              return (
                <li key={it.id}>
                  <a class="tl-row" href={itemHref(it.id, ctx)}>
                    {src ? <img src={src} alt="" width={72} height={72} loading="lazy" decoding="async" /> : <span class="tl-ph" />}
                    <span class="tl-text">
                      <span class="tl-meta"><time dateTime={it.taken_at}>{fmtDate(it.taken_at)}</time> · {KIND_LABEL[it.kind]}{it.repost_of ? ` · sharing @${it.repost_of.author}` : ''}</span>
                      <span class="tl-sum">{it.summary || it.caption || it.description || ''}</span>
                    </span>
                  </a>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
