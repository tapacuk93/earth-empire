import { useEffect, useRef, useState } from 'preact/hooks';
import { Feed } from '../components/Feed';
import { CategoryChips, HighlightsRow, KindTabs, ProfileHeader, useCategories, useHighlights, useProfile } from '../components/Profile';
import { Icon } from '../components/icons';
import { TagCloud } from '../components/TagCloud';
import { navigate, type Route } from '../router';
import { SITE_NAME } from '../config';
import { KIND_PLURAL, setMeta } from '../util';

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
  return (
    <>
      <ProfileHeader profile={profile.data} />
      {profile.error && <p class="error" role="alert">Could not load the profile: {profile.error.message}</p>}
      <HighlightsRow highlights={highlights.data} />
      <div class="view-switch" role="group" aria-label="View">
        <button aria-pressed={view === 'tags'} onClick={() => pickView('tags')}>Tag cloud</button>
        <button aria-pressed={view === 'timeline'} onClick={() => pickView('timeline')}>Everything, by date</button>
      </div>
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
    </>
  );
}
