import { useEffect, useRef, useState } from 'preact/hooks';
import { Feed } from '../components/Feed';
import { CategoryChips, HighlightsRow, KindTabs, ProfileHeader, useCategories, useHighlights, useProfile } from '../components/Profile';
import { Icon } from '../components/icons';
import { TagCloud } from '../components/TagCloud';
import { hitSlide } from '../components/MonitorCard';
import { VideoFeed, type FeedVideo } from '../components/VideoFeed';
import { getItems } from '../api';
import { getPublished, titleOf, whatOf, type Hit } from '../monitor';
import { useData } from '../components/Profile';
import { fmtShort, posterOf, KIND_LABEL } from '../util';
import type { Item } from '../types';
import { navigate, type Route } from '../router';
import { SITE_NAME } from '../config';
import { KIND_PLURAL, setMeta } from '../util';

async function archiveVideos(): Promise<Item[]> {
  const page = await getItems({ limit: 100 });
  return page.items.filter((it) => (it.media[0] || it.repost_of?.media?.[0])?.type === 'video');
}

export function withParam(r: Route, name: string, value: string | undefined): string {
  const q = new URLSearchParams(r.query);
  if (value) q.set(name, value); else q.delete(name);
  const s = q.toString();
  return r.path + (s ? '?' + s : '');
}

export function SearchBox({ route }: { route: Route }) {
  const q = route.query.get('q') || '';
  const [v, setV] = useState(q);
  const timer = useRef<number>();
  useEffect(() => { if (document.activeElement?.id !== 'q') setV(q); }, [q]);
  const commit = (val: string) => navigate(withParam(route, 'q', val.trim() || undefined), { replace: true, keepScroll: true });
  return (
    <form class="search" role="search" onSubmit={(e) => { e.preventDefault(); clearTimeout(timer.current); commit(v); }}>
      <label class="sr-only" for="q">Search the archive</label>
      <Icon name="search" size={18} />
      <input id="q" type="search" placeholder="Search captions, places, people, what happens…" value={v} enterKeyHint="search"
        autocomplete="off" spellcheck={false}
        onInput={(e) => { const val = (e.target as HTMLInputElement).value; setV(val); clearTimeout(timer.current); timer.current = window.setTimeout(() => commit(val), 350); }} />
    </form>
  );
}

type View = 'tags' | 'timeline';
const VIEW_KEY = 'ee-view';
function storedView(): View { try { return localStorage.getItem(VIEW_KEY) === 'timeline' ? 'timeline' : 'tags'; } catch { return 'tags'; } }

export function Home({ route }: { route: Route }) {
  const [saved, setSaved] = useState<View>(storedView);
  const tag = route.query.get('tag') || undefined;
  const urlView = route.query.get('view');
  const view: View = tag ? 'tags' : urlView === 'timeline' || urlView === 'tags' ? urlView : saved;
  const pickView = (v: View) => {
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* storage blocked */ }
    setSaved(v);
    const q = new URLSearchParams(route.query);
    q.delete('view');
    if (v === 'timeline') q.delete('tag');
    const s = q.toString();
    navigate('/' + (s ? '?' + s : ''), { replace: true, keepScroll: true });
  };
  const profile = useProfile();
  const highlights = useHighlights();
  const categories = useCategories();
  const kind = route.query.get('kind') || undefined;
  const category = route.query.get('category') || undefined;
  const q = route.query.get('q') || undefined;

  useEffect(() => {
    const p = profile.data;
    const bits = [q && `“${q}”`, kind && KIND_PLURAL[kind], category && categories.data?.find((c) => c.slug === category)?.name].filter(Boolean);
    setMeta(bits.length ? bits.join(' · ') : SITE_NAME,
      p ? `The archive of @${p.username}${p.full_name ? ` (${p.full_name})` : ''}: every post, reel, story and highlight, described.` : undefined,
      p?.avatar || undefined);
  }, [profile.data, q, kind, category, categories.data]);

  const cat = categories.data?.find((c) => c.slug === category);
  const published = useData(getPublished);
  const watch = route.query.get('watch') || undefined;
  const [archive, setArchive] = useState<Item[]>();
  useEffect(() => { if (watch && !archive) archiveVideos().then(setArchive, () => setArchive([])); }, [watch]);
  const openWatch = (id?: string) => navigate(withParam(route, 'watch', id), { replace: !!watch || !id, keepScroll: true });
  const feed: FeedVideo[] = [
    ...(published.data || []).map(hitSlide),
    ...(archive || []).map((it) => {
      const m = (it.media[0]?.type === 'video' ? it.media[0] : it.repost_of?.media?.[0])!;
      return { id: it.id, url: m.url, cover: posterOf(m), label: it.summary || it.caption || KIND_LABEL[it.kind],
        overlay: <><p class="mon-src">{KIND_LABEL[it.kind]} · {fmtShort(it.taken_at)}{it.repost_of ? ` · by @${it.repost_of.author}` : ''}</p>
          <p class="mon-title">{it.summary || it.caption}</p><p><a href={`/item/${encodeURIComponent(it.id)}`}>Details</a></p></> };
    }),
  ];
  return (
    <>
      <ProfileHeader profile={profile.data} />
      {profile.error && <p class="error" role="alert">Could not load the profile: {profile.error.message}</p>}
      <HighlightsRow highlights={highlights.data} />
      {!!published.data?.length && <PublishedRow videos={published.data} onWatch={openWatch} />}
      <div class="view-switch" role="group" aria-label="View">
        <button aria-pressed={view === 'tags'} onClick={() => pickView('tags')}>Tag cloud</button>
        <button aria-pressed={view === 'timeline'} onClick={() => pickView('timeline')}>Everything, by date</button>
      </div>
      <button class="btn small ghost watch-btn" onClick={() => openWatch(published.data?.[0]?.id || 'first')}>▶ Watch fullscreen</button>
      <div class="filters">
        <SearchBox route={route} />
        <KindTabs active={kind} onPick={(k) => navigate(withParam(route, 'kind', k), { replace: true, keepScroll: true })} />
        {view === 'timeline' && <CategoryChips categories={categories.data} active={category}
          onPick={(c) => navigate(withParam(route, 'category', c), { replace: true, keepScroll: true })} />}
        {cat && <p class="cat-note">{cat.description} <a href={`/category/${cat.slug}`}>{cat.name} page →</a></p>}
      </div>
      {view === 'tags' && <TagCloud active={tag} onPick={(t) => navigate(withParam(route, 'tag', t), { replace: true, keepScroll: true })} />}
      <Feed query={{ kind, category, q, tag: view === 'tags' ? tag : undefined }} layout={view === 'timeline' ? 'timeline' : 'grid'}
        emptyText={q ? `Nothing matches “${q}”.` : 'Nothing here yet.'} />
      {watch && archive && feed.length > 0 && (
        <VideoFeed title="Watch" videos={feed} start={watch === 'first' ? feed[0].id : watch} onClose={() => openWatch(undefined)}
          onIndex={(id) => history.replaceState(history.state, '', withParam(route, 'watch', id))} />
      )}
    </>
  );
}

function PublishedRow({ videos, onWatch }: { videos: Hit[]; onWatch: (id: string) => void }) {
  return (
    <section aria-labelledby="pub-h">
      <div class="section-head"><h2 id="pub-h">Detected and published</h2></div>
      <ul class="mon-row" role="list">
        {videos.map((h) => {
          const img = h.frame || h.video?.thumbnail;
          return (
            <li key={h.id}>
              <button class="mon-thumb" onClick={() => onWatch(h.id)} aria-label={`Fullscreen: ${titleOf(h)}`}>
                {img ? <img src={img} alt="" loading="lazy" width={180} height={320} /> : <span class="mon-noimg">{whatOf(h)}</span>}
                <span class="mon-play" aria-hidden="true">▶</span>
              </button>
              <p><b>{whatOf(h)}</b> · {h.source?.name || h.account || h.platform}</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
