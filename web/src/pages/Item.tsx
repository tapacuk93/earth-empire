import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { ApiError, getAllItems, getExplain, getItem, knownItem } from '../api';
import { AnalysisView } from '../components/Analysis';
import { Icon } from '../components/icons';
import { useCategories, useData, useHighlights } from '../components/Profile';
import { ctxItems, ctxLabel, itemHref } from '../context';
import { getFacets, getLayout, getRelated, tagItems } from '../homeData';
import { setFacets } from '../context';
import { attachMap, withAttachments } from '../layout';
import { canGoBack, navigate, type Route } from '../router';
import type { Item, Media } from '../types';
import { altFor, cover, fmtCount, fmtDate, fmtDateTime, igProfile, itemTitle, posterOf, prefersReducedMotion, setMeta } from '../util';
import { NotFound } from './NotFound';

export function Caption({ text, itemId }: { text: string; itemId?: string }) {
  const parts = text.split(/([#@][\p{L}\p{N}_.]*[\p{L}\p{N}_])/u);
  return (
    <p class="caption">
      {parts.map((p, i) => {
        if (i % 2 === 0) return p;
        if (p.startsWith('#')) return itemId ? <a key={i} href={itemHref(itemId, `tag:${p.slice(1).toLowerCase()}`)}>{p}</a> : p;
        return <a key={i} href={igProfile(p)} rel="external noopener">{p}</a>;
      })}
    </p>
  );
}

export function Details({ item }: { item: Item }) {
  // Groupings are the AI facets (CONTRACT.md "Facets"), by membership.
  const fc = useData(getFacets);
  useEffect(() => { if (fc.data) setFacets(fc.data); }, [fc.data]);
  const mine = (fc.data || []).flatMap((f) => f.categories.filter((c) => c.item_ids.includes(item.id)).map((c) => [f, c] as const));
  const c = item.counts || {};
  const counts = [c.likes !== undefined && `${fmtCount(c.likes)} likes`, c.comments !== undefined && `${fmtCount(c.comments)} comments`,
    c.plays !== undefined && `${fmtCount(c.plays)} plays`, c.views !== undefined && `${fmtCount(c.views)} views`].filter(Boolean);
  const loc = item.location;
  return (
    <dl class="details">
      {loc && (
        <div><dt><Icon name="pin" size={16} /> Place</dt><dd>
          {typeof loc.lat === 'number' && typeof loc.lng === 'number'
            ? <a href={`https://www.openstreetmap.org/?mlat=${loc.lat}&mlon=${loc.lng}#map=15/${loc.lat}/${loc.lng}`} rel="external noopener">{loc.name}</a>
            : loc.name}
        </dd></div>
      )}
      {item.music && (item.music.title || item.music.artist) && (
        <div><dt><Icon name="music" size={16} /> Music</dt><dd>{[item.music.title, item.music.artist].filter(Boolean).join(' — ')}</dd></div>
      )}
      {!!item.tagged_users?.length && (
        <div><dt>Tagged</dt><dd class="inline-list">{item.tagged_users.map((t) => <a key={t.username} href={igProfile(t.username)} rel="external noopener">@{t.username}</a>)}</dd></div>
      )}
      {!!item.highlights?.length && (
        <div><dt>Highlights</dt><dd class="inline-list">{item.highlights.map((h) => <a key={h.id} href={`/highlight/${encodeURIComponent(h.id)}?item=${encodeURIComponent(item.id)}`}>{h.title}</a>)}</dd></div>
      )}
      {mine.length > 0 && (
        <div><dt>Categories</dt><dd><ul class="tags" role="list">{mine.map(([f, c]) => <li key={`${f.id}:${c.id}`}><a class="tag" href={itemHref(item.id, `facet:${f.id}:${c.id}`)} title={f.name}>{c.name}</a></li>)}</ul></dd></div>
      )}
      {!!item.hashtags?.length && (
        <div><dt>Hashtags</dt><dd class="inline-list">{item.hashtags.map((h) => <a key={h} href={itemHref(item.id, `tag:${h.toLowerCase()}`)}>#{h}</a>)}</dd></div>
      )}
      {!!item.stickers?.length && (
        <div><dt>Stickers</dt><dd><ul class="plain" role="list">{item.stickers.map((s, i) => {
          const opts = Array.isArray(s.extra?.options) ? ` (${(s.extra!.options as string[]).join(' / ')})` : '';
          return <li key={i}><span class="muted">{s.type}:</span> {s.text}{opts}</li>;
        })}</ul></dd></div>
      )}
      {!!counts.length && <div><dt>Counts</dt><dd>{counts.join(' · ')}</dd></div>}
      {item.source_url && <div><dt>Source</dt><dd><a href={item.source_url} rel="external noopener">View on Instagram <Icon name="external" size={14} /></a></dd></div>}
    </dl>
  );
}


const NEEDS_HL = /^(section|hl|rel):/;

// What happens at the end of a video: loop it, go on to the next item, or stop. Remembered per visitor.
type Playback = 'repeat' | 'next' | 'stop';
const PB_KEY = 'ee-playback';
const PB_NEXT: Record<Playback, Playback> = { next: 'repeat', repeat: 'stop', stop: 'next' };
const PB_LABEL: Record<Playback, string> = { next: 'Autoplay next', repeat: 'Repeat', stop: 'Stop at the end' };
const PB_ICON = { next: 'next', repeat: 'repeat1', stop: 'stop' } as const;
const IMAGE_MS = 5000;

// Sound is on by default and the choice is remembered. If the browser refuses unmuted playback,
// the video plays muted and the wheel asks for a tap; that tap turns sound on.
const MUTE_KEY = 'ee-muted';
function readMuted(): boolean { try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; } }
function saveMuted(m: boolean) { try { localStorage.setItem(MUTE_KEY, m ? '1' : '0'); } catch { /* storage blocked */ } }
let onForcedMute: (() => void) | null = null;
export function playWithSound(v: HTMLVideoElement, muted: boolean) {
  v.muted = muted;
  v.play().catch((e) => {
    if (muted || (e as Error).name !== 'NotAllowedError') return;
    v.muted = true;
    v.play().catch(() => undefined);
    onForcedMute?.();
  });
}
function readPlayback(): Playback { try { const v = localStorage.getItem(PB_KEY); return v === 'repeat' || v === 'stop' ? v : 'next'; } catch { return 'next'; } }

/** An item opened from the infographics: the vertical feed of its context. */
export function ItemPage({ id, route }: { id: string; route: Route }) {
  const ctx = route.query.get('ctx') || 'all';
  const all = useData(getAllItems);
  const hl = useHighlights();
  const cats = useCategories();
  const [solo, setSolo] = useState<Item | null>();
  const [err, setErr] = useState<Error>();
  const lay = useData(getLayout);
  // The API's order where it has one: related videos for rel:, a tag's items for tag:.
  const [served, setServed] = useState<Item[] | null | undefined>(undefined);
  useEffect(() => {
    setServed(undefined);
    const byId = new Map((all.data || []).map((x) => [x.id, x]));
    if (ctx.startsWith('rel:')) {
      // The opened video first, even when it is newer than the item list in memory.
      Promise.all([getRelated(id), byId.get(id) ? Promise.resolve(byId.get(id)) : getItem(id).catch(() => undefined)]).then(([r, anchor]) =>
        setServed(r ? [anchor, ...r.map((x) => x.item || byId.get(x.id))].filter((x): x is Item => !!x && x.media !== undefined) : null));
    } else if (ctx.startsWith('tag:')) tagItems(ctx.slice(4)).then(setServed);
    else setServed(null);
  }, [ctx, !!all.data]);
  const ready = all.data && (!NEEDS_HL.test(ctx) || hl.data) && served !== undefined && !lay.loading;
  const base = ready ? (served && served.length ? served : ctxItems(ctx, all.data!, hl.data || [])) : undefined;
  const list = base && withAttachments(base, attachMap(all.data!, lay.data ? [...lay.data.top, ...lay.data.bottom] : undefined), id);
  const inList = !!list?.some((x) => x.id === id);
  // A served list (related, a tag's items) can hold items newer than the list in memory.

  useEffect(() => {
    if (!ready || inList) return;
    const k = knownItem(id);
    if (k) { setSolo(k); return; }
    getItem(id).then(setSolo, (e) => { setErr(e); setSolo(null); });
  }, [ready, inList, id]);

  if (err instanceof ApiError && err.status === 404) return <NotFound what="item" />;
  if (err && !solo) return <div class="error" role="alert"><p>Could not load this item. {err.message}</p><p><a class="btn" href="/">Back to Earth Empire</a></p></div>;
  const items = inList ? list! : solo ? [solo] : undefined;
  if (!items) return <div class="ifeed loading" aria-busy="true"><p class="sr-only" role="status">Loading…</p><span class="spinner" /></div>;
  return <ItemFeed key={ctx} items={items} start={id} ctx={inList ? ctx : 'all'} label={inList ? ctxLabel(ctx, cats.data, hl.data) : 'Item'} />;
}

function close() { if (canGoBack()) history.back(); else navigate('/'); }

function ItemFeed({ items, start, ctx, label }: { items: Item[]; start: string; ctx: string; label: string }) {
  const list = useRef<HTMLDivElement>(null);
  const [cur, setCur] = useState(() => Math.max(0, items.findIndex((x) => x.id === start)));
  const [muted, setMutedState] = useState(readMuted);
  const [forced, setForced] = useState(false); // the browser blocked sound until a tap
  const setMuted = (m: boolean) => { setMutedState(m); setForced(false); saveMuted(m); };
  useEffect(() => { onForcedMute = () => setForced(true); return () => { onForcedMute = null; }; }, []);
  const shownMuted = muted || forced;
  const [info, setInfo] = useState(false);
  const [ask, setAsk] = useState(false);
  const [pb, setPb] = useState<Playback>(readPlayback);
  const cyclePb = () => { const n = PB_NEXT[pb]; setPb(n); try { localStorage.setItem(PB_KEY, n); } catch { /* storage blocked */ } };
  const item = items[cur];
  // Stills advance by themselves in autoplay mode.
  useEffect(() => {
    if (pb !== 'next' || info || !item) return;
    const m = item.media.length ? item.media : item.repost_of?.media || [];
    if (m.some((x) => x.type === 'video')) return;
    const t = window.setTimeout(() => go(cur + 1), IMAGE_MS);
    return () => clearTimeout(t);
  }, [cur, pb, info]);

  useLayoutEffect(() => {
    const el = list.current!;
    el.scrollTop = cur * el.clientHeight;
    el.focus({ preventScroll: true });
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  useEffect(() => {
    if (!item) return;
    const url = itemHref(item.id, ctx);
    if (location.pathname + location.search !== url) history.replaceState(history.state, '', url);
    setMeta(itemTitle(item), item.description || item.summary || item.caption || undefined, cover(item));
    setInfo(false);
  }, [item?.id]);

  // Only the slide on screen plays; others pause.
  useEffect(() => {
    list.current?.querySelectorAll<HTMLVideoElement>('video').forEach((v) => {
      const mine = v.closest('.islide')?.getAttribute('data-i') === String(cur);
      if (mine && v.closest('.imedia-slide')?.getAttribute('data-on') === '1') playWithSound(v, muted);
      else { v.muted = true; if (!v.paused) v.pause(); }
    });
  }, [cur, muted]);

  const go = (i: number) => {
    const el = list.current!;
    const c = Math.max(0, Math.min(items.length - 1, i));
    el.scrollTo({ top: c * el.clientHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  };
  const onScroll = () => {
    const el = list.current!;
    if (!el.clientHeight) return;
    const i = Math.round(el.scrollTop / el.clientHeight);
    if (i !== cur && i >= 0 && i < items.length) setCur(i);
  };

  return (
    <div class="ifeed" role="dialog" aria-modal="true" aria-label={`${label}: item ${cur + 1} of ${items.length}`}
      style={{ '--ar': String((() => { const md = item && (item.media[0] || item.repost_of?.media?.[0]); return md?.width && md?.height ? md.width / md.height : 9 / 16; })()) }}
      onKeyDown={(e) => {
        const t = e.target as HTMLElement;
        if (t.tagName === 'INPUT' || (t.tagName === 'BUTTON' && (e.key === ' ' || e.key === 'Enter'))) return;
        if (info && t.closest('.isheet') && /Arrow|Page/.test(e.key)) return; // scrolling the open sheet
        if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === 'j') { e.preventDefault(); go(cur + 1); }
        else if (e.key === 'ArrowUp' || e.key === 'PageUp' || e.key === 'k') { e.preventDefault(); go(cur - 1); }
        else if (e.key === 'Escape') { e.preventDefault(); if (ask) setAsk(false); else if (info) setInfo(false); else close(); }
        else if (e.key === '?') setAsk(!ask);
        else if (e.key === 'm') setMuted(!muted);
        else if (e.key === 'i') setInfo(!info);
      }}>
      <div class="ifeed-top fui">
        <button class="icon-btn" onClick={close} aria-label="Close"><Icon name="close" /></button>
        <p class="ifeed-ctx"><b>{label}</b> <span>{cur + 1} / {items.length}</span></p>
        <button class="icon-btn pb-btn" onClick={cyclePb} aria-label={`Playback: ${PB_LABEL[pb]}. Change it.`} title={PB_LABEL[pb]}><Icon name={PB_ICON[pb]} /></button>
        <button class="icon-btn" onClick={() => setMuted(!shownMuted)} aria-label={shownMuted ? 'Unmute' : 'Mute'} aria-pressed={!shownMuted}><Icon name={shownMuted ? 'mute' : 'sound'} /></button>
        <ShareButton title={item ? itemTitle(item) : ''} />
        <button class="icon-btn iask-btn" onClick={() => setAsk(!ask)} aria-label="What is happening?" aria-expanded={ask} title="What is happening?"><b aria-hidden="true">?</b></button>
      </div>
      {ask && item && <Explain key={item.id} item={item} onClose={() => setAsk(false)} />}
      <h1 class="sr-only">{item ? itemTitle(item) : label}</h1>
      <p class="sr-only" role="status" aria-live="polite">{item ? `${cur + 1} of ${items.length}: ${itemTitle(item)}` : ''}</p>
      <div class="ifeed-list" ref={list} onScroll={onScroll} tabIndex={0} aria-label="Swipe or use the arrow keys for the next and previous item">
        {items.map((it, i) => (
          <section key={it.id} class="islide" data-i={i} aria-hidden={i !== cur ? 'true' : undefined}>
            {Math.abs(i - cur) <= 1
              ? <Slide item={it} active={i === cur} muted={muted} forced={forced} onTapVideo={() => setMuted(forced ? false : !muted)} info={info && i === cur} setInfo={setInfo}
                  loop={pb === 'repeat'} onEnded={() => { if (pb === 'next' && i === cur) go(cur + 1); }} />
              : <span class="islide-ph" />}
          </section>
        ))}
      </div>
      <div class="ifeed-nav fui">
        <button class="icon-btn" onClick={() => go(cur - 1)} disabled={cur === 0} aria-label="Previous item"><Icon name="left" class="up" /></button>
        <button class="icon-btn" onClick={() => go(cur + 1)} disabled={cur === items.length - 1} aria-label="Next item"><Icon name="right" class="down" /></button>
      </div>
    </div>
  );
}

function ShareButton({ title }: { title: string }) {
  const [msg, setMsg] = useState('');
  const share = async () => {
    try {
      if (navigator.share) { await navigator.share({ title, url: location.href }); return; }
      await navigator.clipboard.writeText(location.href);
      setMsg('Link copied');
    } catch (e) { if ((e as Error).name !== 'AbortError') setMsg('Copy the address to share'); }
    setTimeout(() => setMsg(''), 2500);
  };
  return <><button class="icon-btn" onClick={share} aria-label="Share"><Icon name="share" /></button><span class="share-msg" role="status">{msg}</span></>;
}

function Slide({ item, active, muted, forced, onTapVideo, info, setInfo, loop, onEnded }: { item: Item; active: boolean; muted: boolean; forced: boolean; onTapVideo: () => void; info: boolean; setInfo: (v: boolean) => void; loop: boolean; onEnded: () => void }) {
  const r = item.repost_of;
  const media: Media[] = item.media.length ? item.media : r?.media || [];
  const row = useRef<HTMLDivElement>(null);
  const [m, setM] = useState(0);
  const seek = (mi: number, at: number) => {
    const el = row.current;
    if (el) el.scrollTo({ left: mi * el.clientWidth });
    setM(mi);
    const v = el?.querySelectorAll<HTMLElement>('.imedia-slide')[mi]?.querySelector('video');
    if (v) { v.currentTime = at; v.play().catch(() => undefined); }
    setInfo(false);
  };
  useEffect(() => {
    row.current?.querySelectorAll<HTMLVideoElement>('video').forEach((v, i) => {
      const on = active && v.closest('.imedia-slide')?.getAttribute('data-n') === String(m);
      if (on) playWithSound(v, muted); else if (!v.paused) v.pause();
      void i;
    });
  }, [m, active]);
  const place = item.location?.name || item.analysis?.where?.place;
  const hits = item.detection?.hits || [];
  const first = hits[0];
  const started = useRef(false);
  const [t, setT] = useState({ cur: 0, dur: 0 });
  // A video starts a moment before its first matched hit.
  const onMeta = (e: Event, i: number) => {
    const v = e.currentTarget as HTMLVideoElement;
    if (!started.current && first && (first.media ?? 0) === i && typeof first.at === 'number') { started.current = true; v.currentTime = Math.max(0, first.at - 1.5); }
  };
  useEffect(() => { if (first && (first.media ?? 0) !== m && active && !started.current) { const el = row.current; if (el) el.scrollLeft = (first.media ?? 0) * el.clientWidth; } }, [active]);
  const curHits = hits.filter((h) => (h.media ?? 0) === m);
  // Playback shows the whole picture (contain) unless its shape is within 10% of the screen's, when it may fill (cover).
  const [dims, setDims] = useState<Record<number, number>>({});
  const arOf = (i: number) => dims[i] || (media[i]?.width && media[i]?.height ? media[i].width! / media[i].height! : 9 / 16);
  const fit = (i: number) => { const sar = innerWidth / Math.max(1, innerHeight); return Math.abs(arOf(i) - sar) / sar < 0.1 ? 'fit-cover' : 'fit-contain'; };
  const learn = (i: number, w: number, h: number) => { if (w && h && Math.abs((dims[i] || 0) - w / h) > 0.01) setDims((d) => ({ ...d, [i]: w / h })); };
  return (
    <>
      <div class="imedia" ref={row} onScroll={(e) => { const el = e.currentTarget as HTMLElement; const i = Math.round(el.scrollLeft / (el.clientWidth || 1)); if (i !== m) setM(i); }}
        aria-roledescription={media.length > 1 ? 'carousel' : undefined} aria-label={media.length > 1 ? `${media.length} photos and videos; swipe sideways` : undefined}>
        {media.map((md, i) => (
          <div key={i} class="imedia-slide" data-n={i} data-on={i === m ? '1' : '0'}>
            <div class="ibg" aria-hidden="true" style={{ backgroundImage: `url("${posterOf(md) || md.url}")` }} />
            {md.type === 'video'
              ? <video src={md.url} poster={posterOf(md)} muted={muted || forced || !active} loop={loop} class={fit(i)} onLoadedMetadata={(e) => { const v = e.currentTarget as HTMLVideoElement; learn(i, v.videoWidth, v.videoHeight); onMeta(e, i); }}
                  onTimeUpdate={(e) => { if (i === m) { const v = e.currentTarget as HTMLVideoElement; setT({ cur: v.currentTime, dur: v.duration || 0 }); } }} onEnded={() => { if (i === media.length - 1) onEnded(); else { row.current?.scrollTo({ left: (i + 1) * (row.current.clientWidth || 0) }); setM(i + 1); } }} playsinline autoplay={false} preload={active ? 'auto' : 'metadata'}
                  aria-label={altFor(item, i, md)} onClick={onTapVideo} />
              : <img class={fit(i)} src={md.url} alt={altFor(item, i, md)} decoding="async" draggable={false} onLoad={(e) => { const g = e.currentTarget as HTMLImageElement; learn(i, g.naturalWidth, g.naturalHeight); }} />}
          </div>
        ))}
      </div>
      <div class="icol" style={{ '--ar': String(arOf(m)) }}>
      {media.length > 1 && <div class="idots" aria-hidden="true">{media.map((_, i) => <span key={i} class={i === m ? 'on' : ''} />)}</div>}
      {forced && active && media[m]?.type === 'video' && <button class="unmute" onClick={onTapVideo}><Icon name="sound" size={16} /> Tap for sound</button>}
      {active && first && (
        <div class="hit-chip fui" role="note" aria-label="Why this is here">
          <span class={`conf ${confLabel(first.confidence) === 'low confidence' ? 'low' : ''}`}>{confLabel(first.confidence)}</span>
          {first.excerpt && <span class="hit-ex">“{first.excerpt}”</span>}
          {first.translation && first.translation !== first.excerpt && <span class="hit-tr">{first.translation}</span>}
          {hits.length > 1 && <span class="hit-n">{hits.length} moments</span>}
        </div>
      )}
      {active && media[m]?.type === 'video' && t.dur > 0 && (
        <div class="hit-bar" aria-hidden="true">
          <span class="hit-bar-fill" style={{ width: `${(t.cur / t.dur) * 100}%` }} />
          {curHits.map((h, k) => typeof h.at === 'number' && <span key={k} class="hit-mark" style={{ left: `${(h.at / t.dur) * 100}%` }} />)}
        </div>
      )}
      <div class={`ioverlay ${info ? 'open' : ''}`}>
        <p class="imeta"><time dateTime={item.taken_at}>{fmtDate(item.taken_at)}</time>{place && ` · ${place}`}
          {r && <> · Original by <a href={r.source_url || igProfile(r.author)} rel="external noopener">@{r.author}</a></>}</p>
        <h2 class="ititle">{item.summary || itemTitle(item)}</h2>
        {!info && (item.description || item.caption) && <p class="idesc">{item.description || item.caption}</p>}
        {!info && item.analysis && <CompactAnalysis item={item} />}
        <button class="btn small imore" onClick={() => setInfo(!info)} aria-expanded={info}>{info ? 'Less' : 'More'}</button>
        {info && (
          <div class="isheet" tabIndex={0} aria-label="Description and analysis">
            {item.description && <p class="description">{item.description}</p>}
            {item.caption && <figure class="caption-box"><figcaption class="muted small">Caption</figcaption><Caption text={item.caption} itemId={item.id} /></figure>}
            {r && (
              <p class="small">Original by <a href={igProfile(r.author)} rel="external noopener">@{r.author}</a>{r.author_name && ` (${r.author_name})`}
                {r.taken_at && `, ${fmtDate(r.taken_at)}`}{r.source_url && <> · <a href={r.source_url} rel="external noopener">View on Instagram</a></>}</p>
            )}
            <Details item={item} />
            {item.analysis && <AnalysisView item={{ ...item, media }} a={item.analysis} seek={seek} />}
            <p class="muted small">{fmtDateTime(item.taken_at)}{item.counts?.likes !== undefined && ` · ${fmtCount(item.counts.likes)} likes`}</p>
          </div>
        )}
      </div>
      </div>
    </>
  );
}

const confLabel = (c?: number) => (typeof c !== 'number' ? 'possible' : c >= 0.7 ? 'likely' : c >= 0.4 ? 'possible' : 'low confidence');

/** A few facts at a glance: who, where, when, mood. */
function CompactAnalysis({ item }: { item: Item }) {
  const a = item.analysis!;
  const who = (a.people || []).filter((p) => p.who).map((p) => p.who!);
  const facts = [
    who.length && `With ${who.slice(0, 3).join(', ')}`,
    a.where?.place && `At ${a.where.place}${a.where.country ? ', ' + a.where.country : ''}`,
    a.when?.time_of_day && `${a.when.time_of_day}${a.when.season ? ', ' + a.when.season : ''}`,
    a.mood && `Mood: ${a.mood}`,
  ].filter(Boolean) as string[];
  if (!facts.length) return null;
  return <ul class="ifacts">{facts.map((f) => <li key={f}>{f}</li>)}</ul>;
}

/** The owner's own description: a post (not a story, not a repost) with a caption. */
const ownCaption = (it: Item) => (['post', 'carousel', 'reel'].includes(it.kind) && !it.repost_of && it.caption?.trim()) || '';

/**
 * The "?" panel: what is happening, in the browser's language. A post is explained by its own
 * description (translated by the API); anything else from its analysis. Until the API answers, or
 * when it cannot, the text the item already has.
 */
function Explain({ item, onClose }: { item: Item; onClose: () => void }) {
  const lang = navigator.language || 'en';
  const [text, setText] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  useEffect(() => { getExplain(item.id, lang).then((r) => { setText(r?.text || null); setDone(true); }); }, [item.id, lang]);
  const fallback = ownCaption(item) || item.description || item.summary || itemTitle(item);
  return (
    <div class="iask" role="region" aria-label="What is happening" aria-busy={!done} lang={text ? lang : undefined}>
      <button class="icon-btn iask-close" onClick={onClose} aria-label="Close the explanation"><Icon name="close" /></button>
      <p>{text || fallback}</p>
      {!done && <span class="spinner small" aria-hidden="true" />}
    </div>
  );
}
