import { useEffect, useRef, useState } from 'preact/hooks';
import { ApiError, getItem, knownItem } from '../api';
import { AnalysisView } from '../components/Analysis';
import { Icon } from '../components/icons';
import { MediaViewer, type MediaHandle } from '../components/MediaViewer';
import { useCategories } from '../components/Profile';
import { canGoBack } from '../router';
import type { Item, Repost } from '../types';
import { altFor, cover, fmtCount, fmtDate, fmtDateTime, igProfile, itemTitle, KIND_LABEL, setMeta } from '../util';
import { NotFound } from './NotFound';

export function Caption({ text }: { text: string }) {
  const parts = text.split(/([#@][\p{L}\p{N}_.]*[\p{L}\p{N}_])/u);
  return (
    <p class="caption">
      {parts.map((p, i) => {
        if (i % 2 === 0) return p;
        if (p.startsWith('#')) return <a key={i} href={`/?q=${encodeURIComponent(p)}`}>{p}</a>;
        return <a key={i} href={igProfile(p)} rel="external noopener">{p}</a>;
      })}
    </p>
  );
}

function BackLink() {
  return (
    <a class="back" href="/" onClick={(e) => { if (canGoBack()) { e.preventDefault(); history.back(); } }}>
      <Icon name="back" size={18} /> Archive
    </a>
  );
}

function ShareButton({ title }: { title: string }) {
  const [msg, setMsg] = useState('');
  const share = async () => {
    const url = location.href;
    try {
      if (navigator.share) { await navigator.share({ title, url }); return; }
      await navigator.clipboard.writeText(url);
      setMsg('Link copied');
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setMsg('Copy the address bar to share');
    }
    setTimeout(() => setMsg(''), 2500);
  };
  return (
    <span class="share">
      <button class="btn ghost" onClick={share}><Icon name="share" size={18} /> Share</button>
      <span role="status" class="share-msg">{msg}</span>
    </span>
  );
}

function OriginalCard({ r, handle }: { r: Repost; handle: { current: MediaHandle | null } }) {
  const kind = r.source_url?.includes('/reel/') ? 'Reel' : 'Post';
  return (
    <figure class="pane original">
      <figcaption class="pane-head">
        <span class="pane-label">Original</span>
        <span>{kind} by <a href={igProfile(r.author)} rel="external noopener">@{r.author}</a>{r.author_name && <span class="muted"> · {r.author_name}</span>}</span>
      </figcaption>
      <MediaViewer media={r.media} handle={handle} label={`${kind} by @${r.author}`}
        alt={(i, m) => `${m.type === 'video' ? 'Video' : 'Photo'}${r.media.length > 1 ? ` ${i + 1} of ${r.media.length}` : ''} by @${r.author}${r.caption ? ': ' + r.caption : ''}`.slice(0, 400)} />
      <div class="pane-body">
        {r.caption && <Caption text={r.caption} />}
        <p class="muted small">
          {r.taken_at && <time dateTime={r.taken_at}>{fmtDate(r.taken_at)}</time>}
          {r.source_url && <> · <a href={r.source_url} rel="external noopener">View on Instagram <Icon name="external" size={14} /></a></>}
        </p>
      </div>
    </figure>
  );
}

function Details({ item }: { item: Item }) {
  const cats = useCategories();
  const name = (slug: string) => cats.data?.find((c) => c.slug === slug)?.name || slug;
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
      {!!item.categories?.length && (
        <div><dt>Categories</dt><dd><ul class="tags" role="list">{item.categories.map((s) => <li key={s}><a class="tag" href={`/category/${encodeURIComponent(s)}`}>{name(s)}</a></li>)}</ul></dd></div>
      )}
      {!!item.hashtags?.length && (
        <div><dt>Hashtags</dt><dd class="inline-list">{item.hashtags.map((h) => <a key={h} href={`/?q=${encodeURIComponent('#' + h)}`}>#{h}</a>)}</dd></div>
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

export function ItemPage({ id }: { id: string }) {
  const [item, setItem] = useState<Item | undefined>(() => knownItem(id));
  const [err, setErr] = useState<Error>();
  const main = useRef<MediaHandle>(null);
  const orig = useRef<MediaHandle>(null);

  useEffect(() => {
    let live = true;
    setErr(undefined);
    setItem(knownItem(id));
    getItem(id).then((x) => live && setItem(x), (e) => live && setErr(e));
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    if (item) setMeta(itemTitle(item), item.summary || item.caption || undefined, cover(item));
  }, [item]);

  if (err instanceof ApiError && err.status === 404) return <NotFound what="item" />;
  if (err && !item) return <div class="error" role="alert"><p>Could not load this item. {err.message}</p><p><a class="btn" href={location.pathname}>Try again</a></p></div>;
  if (!item) return <div class="item-loading" aria-busy="true"><p class="sr-only" role="status">Loading…</p><div class="viewer placeholder" /></div>;

  const kind = KIND_LABEL[item.kind] || 'Item';
  const r = item.repost_of;
  const seek = (m: number, at: number) => main.current?.seek(m, at);
  const own = item.media.length > 0 && (
    <MediaViewer media={item.media} handle={main} eager label={`${kind} media`} alt={(i, m) => altFor(item, i, m)} />
  );

  return (
    <article class={`item ${r ? 'is-repost' : ''}`} aria-labelledby="item-h">
      <div class="item-bar"><BackLink /><ShareButton title={itemTitle(item)} /></div>
      <div class="item-layout">
        <div class="item-media">
          {r ? (
            <div class="repost-pair">
              <figure class="pane sharing">
                <figcaption class="pane-head"><span class="pane-label">Shared</span><span>{kind} sharing <a href={igProfile(r.author)} rel="external noopener">@{r.author}</a></span></figcaption>
                {own}
              </figure>
              <OriginalCard r={r} handle={orig} />
            </div>
          ) : own}
        </div>
        <div class="item-info">
          <header class="item-head">
            <p class="eyebrow">
              <span class={`kind-pill k-${item.kind}`}>{kind}</span>
              {r && <span class="kind-pill k-repost">Repost</span>}
              <time dateTime={item.taken_at}>{fmtDateTime(item.taken_at)}</time>
            </p>
            <h1 id="item-h" class="item-title">{item.summary || (item.caption ? itemTitle(item) : `${kind} from ${fmtDate(item.taken_at)}`)}</h1>
          </header>
          {item.description && <p class="description">{item.description}</p>}
          {item.caption && <figure class="caption-box"><figcaption class="muted small">Caption</figcaption><Caption text={item.caption} /></figure>}
          <Details item={item} />
          {item.analysis ? <AnalysisView item={item} a={item.analysis} seek={seek} /> : <p class="muted">Not described yet.</p>}
        </div>
      </div>
    </article>
  );
}
