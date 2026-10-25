import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { getAllItems } from '../api';
import { Icon } from '../components/icons';
import { hitSlide } from '../components/MonitorCard';
import { MosaicView } from '../components/MosaicView';
import { useCategories, useData, useHighlights, useProfile } from '../components/Profile';
import { TagGraphView } from '../components/TagGraphView';
import { TimelineView } from '../components/TimelineView';
import { EarthButton } from '../components/Chrome';
import { modesTopSaved, saveModesTop } from '../components/zoom';
import { VideoFeed } from '../components/VideoFeed';
import { SITE_NAME } from '../config';
import { itemHref } from '../context';
import { attachMap, buildMosaic, buildTagGraph, graphFromApi, mosaicFromLayout, placeAttached, type Tile } from '../layout';
import { getFacets, getLayout, getTagGraph, tagItems, type Facet } from '../homeData';
import { FacetsPanel } from '../components/FacetsPanel';
import type { GNode } from '../layout';
import { ctxItems, setFacets } from '../context';
import { getPublished } from '../monitor';
import { navigate, settleScroll, type Route } from '../router';
import { hitSection, SECTION_TITLE, sectionHighlights, sectionItems, type SectionId } from '../sections';
import { months, people, places, tagsOf } from '../stats';
import { fmtShort, prefersReducedMotion, setMeta } from '../util';

const MODES: [string, string][] = [['mode-mosaic', 'Mosaic mode'], ['mode-tags', 'Tag graph mode'], ['mode-time', 'Timeline mode']];

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
  const commit = (val: string) => navigate(withParam(route, 'q', val.trim() || undefined), { replace: true, keepScroll: true });
  return (
    <form class="search" role="search" onSubmit={(e) => { e.preventDefault(); clearTimeout(timer.current); commit(v); }}>
      <label class="sr-only" for="q">Search Earth Empire</label>
      <Icon name="search" size={18} />
      <input id="q" type="search" placeholder="Search" value={v} onInput={(e) => { const val = (e.target as HTMLInputElement).value; setV(val); clearTimeout(timer.current); timer.current = window.setTimeout(() => commit(val), 350); }} />
    </form>
  );
}

function spanOf(a: string, b: string): string {
  const days = Math.max(0, (Date.parse(b) - Date.parse(a)) / 864e5);
  return days >= 730 ? `${Math.round(days / 365)} years` : days >= 60 ? `${Math.round(days / 30.4)} months` : `${Math.max(1, Math.round(days))} days`;
}

export function Home({ route }: { route: Route }) {
  const profile = useProfile();
  const highlights = useHighlights();
  const categories = useCategories();
  const all = useData(getAllItems);
  const published = useData(getPublished);
  const watch = route.query.get('watch') || undefined;

  useEffect(() => {
    const p = profile.data;
    setMeta(SITE_NAME, 'Earth Empire: every video, described and mapped by what it is about.', '/icon/og.png');
  }, [profile.data]);
  useEffect(() => { if (all.data) settleScroll(); }, [!!all.data]);

  const items = all.data || [];
  const hl = highlights.data || [];
  const hits = published.data || [];
  const ready = !!all.data && !!highlights.data;
  const lay = useData(getLayout);
  const tg = useData(getTagGraph);
  // One packed mosaic over the whole screen, every video in it; similarity decides the neighbours
  // and size ^ display_exponent the area. The API's combined list when it has one, else both halves.
  const mosaic = useMemo(() => {
    if (!ready || lay.loading) return null;
    const L = lay.data;
    const all = L ? (L.tiles || [...L.top, ...L.bottom]) : undefined;
    const attach = attachMap(items, all);
    const byId = new Map(items.map((it) => [it.id, it]));
    const hitById = new Map(hits.map((h) => [h.id, h]));
    return placeAttached(all ? mosaicFromLayout(all, byId, hitById, L!.exponent) : buildMosaic(items, hl, hits), attach);
  }, [ready, lay.loading, items, hl, hits]);
  const graph = useMemo(() => (tg.loading || !ready ? null : tg.data ? graphFromApi(tg.data.nodes, tg.data.edges) : buildTagGraph(items, tagsOf(items))), [ready, tg.loading, items]);
  const fc = useData(getFacets);
  useEffect(() => { if (fc.data) setFacets(fc.data); }, [fc.data]);
  const openFacet = (facet: string, category: string) => {
    const ctx = `facet:${facet}:${category}`;
    const list = ctxItems(ctx, items, hl);
    if (list.length) navigate(itemHref(list[0].id, ctx));
  };
  const openTag = async (n: GNode) => {
    if (n.facet && n.category) return openFacet(n.facet, n.category);
    const tag = n.tag;
    const list = (await tagItems(tag)) || ctxItems(`tag:${tag}`, items, hl);
    if (list.length) navigate(itemHref(list[0].id, `tag:${tag}`));
  };
  const tagLabel = (n: { tag: string; kind: string }) => n.kind === 'category' ? categories.data?.find((c) => c.slug === n.tag)?.name || n.tag : n.kind === 'hashtag' ? '#' + n.tag : n.tag;
  const hrefFor = (t: Tile) => (t.hit ? withParam(route, 'watch', t.id) : itemHref(t.id, `rel:all:${t.id}`));
  const first = items[items.length - 1], last = items[0];
  const modes = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState(0);
  // The mode on screen is remembered (by index) and restored on return; scroll events before the
  // restore must not overwrite it.
  const restored = useRef(false);
  const onModesScroll = () => {
    const el = modes.current;
    if (!el?.clientHeight) return;
    const i = Math.round(el.scrollTop / el.clientHeight);
    setMode(i);
    if (restored.current) saveModesTop(i);
  };
  useEffect(() => {
    if (!ready) return;
    const want = modesTopSaved();
    let n = 0;
    const go = () => {
      const el = modes.current;
      if (!el) return;
      el.scrollTop = want * el.clientHeight;
      onModesScroll();
      if (Math.abs(el.scrollTop - want * el.clientHeight) > 2 && ++n < 60) setTimeout(go, 50); else restored.current = true;
    };
    go();
  }, [ready]);
  const openHit = (id?: string) => navigate(withParam(route, 'watch', id), { replace: !!watch || !id, keepScroll: true });

  return (
    <>
      <div class="modes" ref={modes} onScroll={onModesScroll}>
        <section class="mode mode-mosaic" id="mode-mosaic" aria-label="Mosaic mode">
          {mosaic && !mosaic.tiles.length && (
            <div class="empty-full"><p>Nothing is public yet.</p><p class="muted">Videos appear here as they arrive.</p></div>
          )}
          {!mosaic ? <div class="skeleton-cloud" aria-hidden="true" /> : mosaic.tiles.length > 0 && (
            <MosaicView id="m-all" title="Every video" mosaic={mosaic} hrefFor={hrefFor}
              onEdge={(d) => { const el = modes.current; if (el && d > 0) el.scrollTo({ top: el.clientHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' }); }} />
          )}
        </section>
        <section class="mode" id="mode-tags" aria-label="Tag graph mode">
          {graph && graph.nodes.length > 0 && (
            <TagGraphView nodes={graph.nodes} edges={graph.edges} labelFor={tagLabel} onOpen={openTag} />
          )}
          {fc.data && <FacetsPanel facets={fc.data} onOpen={(f: Facet, c) => openFacet(f.id, c.id)} />}
        </section>
        <section class="mode" id="mode-time" aria-label="Timeline mode">
          {all.data && <TimelineView items={items} hrefFor={(it) => itemHref(it.id)} />}
        </section>
      </div>
      <header class="home-pill fui">
        <h1><EarthButton label={SITE_NAME} />{SITE_NAME}</h1>
        {all.error ? <p class="error" role="alert">Could not load Earth Empire: {all.error.message}</p> : all.data && (
          <p class="stats-line">
            <b>{items.length}</b> videos{first && last && <> · <b>{spanOf(first.taken_at, last.taken_at)}</b></>} · <b>{places(items).length}</b> places · <b>{people(items).length}</b> people{profile.data && <> · from <a href={`https://www.instagram.com/${profile.data.username}/`} rel="external noopener">@{profile.data.username}</a></>}
          </p>
        )}
      </header>
      <nav class="mode-dots fui" aria-label="Modes">
        {MODES.map(([mid, label], i) => (
          <button key={mid} aria-label={label} aria-current={mode === i ? 'true' : undefined} title={label}
            onClick={() => { const el = modes.current; if (el) el.scrollTo({ top: i * el.clientHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' }); void mid; }}>
            <span aria-hidden="true" /></button>
        ))}
      </nav>
      {watch && hits.length > 0 && (
        <VideoFeed title="Detected and published" videos={hits.map(hitSlide)} start={watch} onClose={() => openHit(undefined)}
          onIndex={(id) => history.replaceState(history.state, '', withParam(route, 'watch', id))} />
      )}
    </>
  );
}
