import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { getAllItems } from '../api';
import { Icon } from '../components/icons';
import { hitSlide } from '../components/MonitorCard';
import { MosaicView } from '../components/MosaicView';
import { useCategories, useData, useHighlights, useProfile } from '../components/Profile';
import { TagGraphView } from '../components/TagGraphView';
import { TimelineView } from '../components/TimelineView';
import { modesTopSaved, saveModesTop } from '../components/zoom';
import { VideoFeed } from '../components/VideoFeed';
import { SITE_NAME } from '../config';
import { itemHref } from '../context';
import { attachMap, buildMosaic, buildTagGraph, graphFromApi, mosaicFromLayout, placeAttached, type Tile } from '../layout';
import { getLayout, getTagGraph, tagItems } from '../homeData';
import { ctxItems } from '../context';
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
      <label class="sr-only" for="q">Search the archive</label>
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
    setMeta(SITE_NAME, p ? `The archive of @${p.username} as a map of videos: what is related sits together.` : undefined, p?.avatar || undefined);
  }, [profile.data]);
  useEffect(() => { if (all.data) settleScroll(); }, [!!all.data]);

  const items = all.data || [];
  const hl = highlights.data || [];
  const hits = published.data || [];
  const ready = !!all.data && !!highlights.data;
  const lay = useData(getLayout);
  const tg = useData(getTagGraph);
  const halves = useMemo(() => {
    if (!ready || lay.loading) return null;
    const L = lay.data;
    const attach = attachMap(items, L ? [...L.top, ...L.bottom] : undefined);
    const byId = new Map(items.map((it) => [it.id, it]));
    const hitById = new Map(hits.map((h) => [h.id, h]));
    return (['dedicated', 'common'] as SectionId[]).map((id) => ({
      id,
      mosaic: placeAttached(L
        ? mosaicFromLayout(id === 'dedicated' ? L.top : L.bottom, byId, hitById)
        : buildMosaic(sectionItems(id, items, hl), sectionHighlights(id, hl), hits.filter((h) => hitSection(h) === id)), attach),
    }));
  }, [ready, lay.loading, items, hl, hits]);
  const graph = useMemo(() => (tg.loading || !ready ? null : tg.data ? graphFromApi(tg.data.nodes, tg.data.edges) : buildTagGraph(items, tagsOf(items))), [ready, tg.loading, items]);
  const openTag = async (tag: string) => {
    const list = (await tagItems(tag)) || ctxItems(`tag:${tag}`, items, hl);
    if (list.length) navigate(itemHref(list[0].id, `tag:${tag}`));
  };
  const tagLabel = (n: { tag: string; kind: string }) => n.kind === 'category' ? categories.data?.find((c) => c.slug === n.tag)?.name || n.tag : n.kind === 'hashtag' ? '#' + n.tag : n.tag;
  const hrefFor = (id: SectionId) => (t: Tile) => (t.hit ? withParam(route, 'watch', t.id) : itemHref(t.id, `rel:${id}:${t.id}`));
  const first = items[items.length - 1], last = items[0];
  const modes = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState(0);
  const onModesScroll = () => { const el = modes.current; if (el?.clientHeight) { saveModesTop(el.scrollTop); setMode(Math.round(el.scrollTop / el.clientHeight)); } };
  useEffect(() => {
    if (!ready) return;
    const want = modesTopSaved();
    let n = 0;
    const go = () => { const el = modes.current; if (!el) return; el.scrollTop = want; onModesScroll(); if (Math.abs(el.scrollTop - want) > 2 && ++n < 40) setTimeout(go, 50); };
    go();
  }, [ready]);
  const openHit = (id?: string) => navigate(withParam(route, 'watch', id), { replace: !!watch || !id, keepScroll: true });

  return (
    <>
      <div class="modes" ref={modes} onScroll={onModesScroll}>
        <section class="mode mode-mosaic" id="mode-mosaic" aria-label="Mosaic mode">
          {!halves ? <div class="skeleton-cloud" aria-hidden="true" /> : halves.map((h) => h.mosaic.tiles.length > 0 && (
            <MosaicView key={h.id} id={`m-${h.id}`} title={SECTION_TITLE[h.id]} mosaic={h.mosaic} hrefFor={hrefFor(h.id)} />
          ))}
        </section>
        <section class="mode" id="mode-tags" aria-label="Tag graph mode">
          {graph && graph.nodes.length > 0 && (
            <TagGraphView nodes={graph.nodes} edges={graph.edges} labelFor={tagLabel} onOpen={openTag} />
          )}
        </section>
        <section class="mode" id="mode-time" aria-label="Timeline mode">
          {all.data && <TimelineView items={items} hrefFor={(it) => itemHref(it.id)} />}
        </section>
      </div>
      <header class="home-pill fui">
        <h1><span class="logo" aria-hidden="true" />{SITE_NAME}</h1>
        {all.error ? <p class="error" role="alert">Could not load the archive: {all.error.message}</p> : all.data && (
          <p class="stats-line">
            <b>{items.length}</b> videos{first && last && <> · <b>{spanOf(first.taken_at, last.taken_at)}</b></>} · <b>{places(items).length}</b> places · <b>{people(items).length}</b> people
          </p>
        )}
      </header>
      <nav class="mode-dots fui" aria-label="Modes">
        {MODES.map(([mid, label], i) => (
          <button key={mid} aria-label={label} aria-current={mode === i ? 'true' : undefined} title={label}
            onClick={() => document.getElementById(mid)?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth' })}>
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
