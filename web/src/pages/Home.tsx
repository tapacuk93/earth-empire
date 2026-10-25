import { useEffect, useRef, useState } from 'preact/hooks';
import { Feed } from '../components/Feed';
import { CategoryChips, HighlightsRow, KindTabs, ProfileHeader, useCategories, useHighlights, useProfile } from '../components/Profile';
import { Icon } from '../components/icons';
import { TagCloud } from '../components/TagCloud';
import { hitSlide } from '../components/MonitorCard';
import { VideoFeed, type FeedVideo } from '../components/VideoFeed';
import { getHighlightItems, getItems } from '../api';
import { Tile } from '../components/Feed';
import { highlightSection, hitSection, SECTION_TITLE } from '../sections';
import type { Highlight } from '../types';
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
  const pubDedicated = (published.data || []).filter((h) => hitSection(h) === 'dedicated');
  const pubCommon = (published.data || []).filter((h) => hitSection(h) !== 'dedicated');
  const hlDedicated = highlights.data?.filter((h) => highlightSection(h) === 'dedicated') || [];
  const hlCommon = highlights.data?.filter((h) => highlightSection(h) !== 'dedicated');
  const twoParts = hlDedicated.length > 0 || pubDedicated.length > 0;
  const watch = route.query.get('watch') || undefined;
  const [archive, setArchive] = useState<Item[]>();
  useEffect(() => { if (watch && !archive) archiveVideos().then(setArchive, () => setArchive([])); }, [watch]);
  const openWatch = (id?: string) => navigate(withParam(route, 'watch', id), { replace: !!watch || !id, keepScroll: true });
  const feed: FeedVideo[] = [
    ...pubDedicated.map(hitSlide), ...pubCommon.map(hitSlide),
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
      {twoParts && (
        <section class="home-part" aria-labelledby="part-dedicated">
          <h2 id="part-dedicated" class="part-h">{SECTION_TITLE.dedicated}</h2>
          {pubDedicated.length > 0 && <PublishedRow id="pub-dedicated" videos={pubDedicated} onWatch={openWatch} />}
          {hlDedicated.length > 0 && <><HighlightsRow highlights={hlDedicated} /><SectionItems highlights={hlDedicated} /></>}
        </section>
      )}
      <section class="home-part" aria-labelledby={twoParts ? 'part-common' : undefined}>
      {twoParts && <h2 id="part-common" class="part-h">{SECTION_TITLE.common}</h2>}
      {pubCommon.length > 0 && <PublishedRow id="pub-common" videos={pubCommon} onWatch={openWatch} />}
      <HighlightsRow highlights={hlCommon} />
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
      </section>
      {watch && archive && feed.length > 0 && (
        <VideoFeed title="Watch" videos={feed} start={watch === 'first' ? feed[0].id : watch} onClose={() => openWatch(undefined)}
          onIndex={(id) => history.replaceState(history.state, '', withParam(route, 'watch', id))} />
      )}
    </>
  );
}

/** Every item of the given highlights, newest first. */
function SectionItems({ highlights }: { highlights: Highlight[] }) {
  const key = highlights.map((h) => h.id).join(',');
  const items = useData(async () => {
    const lists = await Promise.all(highlights.map((h) => getHighlightItems(h).catch(() => [] as Item[])));
    const seen = new Map<string, Item>();
    lists.flat().forEach((it) => seen.set(it.id, it));
    return [...seen.values()].sort((a, b) => b.taken_at.localeCompare(a.taken_at));
  }, [key]);
  if (!items.data?.length) return null;
  return <ul class="grid part-grid" role="list" aria-label="Items in these highlights">{items.data.map((it, i) => <Tile key={it.id} item={it} eager={i < 3} />)}</ul>;
}

function PublishedRow({ id, videos, onWatch }: { id: string; videos: Hit[]; onWatch: (id: string) => void }) {
  return (
    <section aria-labelledby={id}>
      <div class="section-head"><h3 id={id}>Detected and published</h3></div>
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
