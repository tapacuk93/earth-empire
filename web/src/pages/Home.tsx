import { useEffect, useRef, useState } from 'preact/hooks';
import { getAllItems } from '../api';
import { Bars, DotMap, Kpis, Legend, MediaStrip, MonthBand, Treemap } from '../components/Charts';
import { Feed } from '../components/Feed';
import { Icon } from '../components/icons';
import { hitSlide } from '../components/MonitorCard';
import { KindTabs, useCategories, useData, useHighlights, useProfile } from '../components/Profile';
import { VideoFeed } from '../components/VideoFeed';
import { SITE_NAME } from '../config';
import { ctxItems, itemHref } from '../context';
import { getPublished, titleOf, whatOf, type Hit } from '../monitor';
import { navigate, settleScroll, type Route } from '../router';
import { highlightSection, hitSection, SECTION_TITLE, SECTIONS, type SectionId } from '../sections';
import { categoryCounts, kinds, moments, months, people, places, sectionItems, tagsOf } from '../stats';
import type { Highlight, Item } from '../types';
import { fmtShort, fmtTime, setMeta } from '../util';

export function withParam(r: Route, name: string, value: string | undefined): string {
  const q = new URLSearchParams(r.query);
  if (value) q.set(name, value); else q.delete(name);
  const s = q.toString();
  return r.path + (s ? '?' + s : '');
}
const setParam = (r: Route, name: string, value: string | undefined) => navigate(withParam(r, name, value), { replace: true, keepScroll: true });

export function SearchBox({ route }: { route: Route }) {
  const q = route.query.get('q') || '';
  const [v, setV] = useState(q);
  const timer = useRef<number>();
  useEffect(() => { if (document.activeElement?.id !== 'q') setV(q); }, [q]);
  const commit = (val: string) => setParam(route, 'q', val.trim() || undefined);
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

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

function Panel({ id, title, sub, children, class: cls }: { id: string; title: string; sub?: string; children: preact.ComponentChildren; class?: string }) {
  return (
    <section class={`ipanel ${cls || ''}`} aria-labelledby={id}>
      <header class="ipanel-head"><h2 id={id}>{title}</h2>{sub && <p class="muted">{sub}</p>}</header>
      {children}
    </section>
  );
}

function Selection({ title, items, ctx, onClear }: { title?: string; items: Item[]; ctx: string; onClear: () => void }) {
  if (!title) return null;
  return (
    <div class="selection" role="status">
      <p class="sel-head"><b>{title}</b> · {plural(items.length, 'item')}
        {items.length > 0 && <a class="btn small" href={itemHref(items[0].id, ctx)}>Open the feed</a>}
        <button class="btn small ghost" onClick={onClear}>Clear</button></p>
      <MediaStrip items={items} ctx={ctx} label={`Items: ${title}`} />
    </div>
  );
}

function SectionPanel({ id, items, highlights, hits, onHit }: { id: SectionId; items: Item[]; highlights: Highlight[]; hits: Hit[]; onHit: (id: string) => void }) {
  const ctx = `section:${id}`;
  const ppl = people(items).slice(0, 8);
  const plc = places(items).slice(0, 8);
  const mom = moments(items, 6);
  const k = kinds(items);
  const videos = items.filter((it) => (it.media[0] || it.repost_of?.media?.[0])?.type === 'video').length;
  return (
    <Panel id={`sec-${id}`} title={SECTION_TITLE[id]} class={`sec sec-${id}`}
      sub={highlights.length ? `Highlights: ${highlights.map((h) => h.title).join(', ')}` : undefined}>
      <Kpis items={[
        { label: 'Items', value: items.length }, { label: 'Videos', value: videos },
        { label: 'Stories', value: k.story || 0 }, { label: 'Places', value: plc.length }, { label: 'People named', value: ppl.length },
        ...(hits.length ? [{ label: 'Detected', value: hits.length }] : []),
      ]} />
      <div class="sec-cols">
        {ppl.length > 0 && (
          <div><h3>People</h3><ul class="chips-list">{ppl.map((p) => (
            <li key={p.who}><a class="chip" href={itemHref(p.items[0], `person:${p.who}`)}>{p.who}<span class="chip-count">{p.count}</span></a></li>))}</ul></div>
        )}
        {plc.length > 0 && (
          <div><h3>Places</h3><ul class="chips-list">{plc.map((p) => (
            <li key={p.name}><a class="chip" href={itemHref(p.items[0], `place:${p.name}`)}>{p.name}<span class="chip-count">{p.count}</span></a></li>))}</ul></div>
        )}
        {highlights.length > 0 && (
          <div><h3>Highlights</h3><ul class="chips-list">{highlights.map((h) => (
            <li key={h.id}><a class="chip" href={`/highlight/${encodeURIComponent(h.id)}`}>{h.title}<span class="chip-count">{h.item_ids.length}</span></a></li>))}</ul></div>
        )}
      </div>
      {mom.length > 0 && (
        <div><h3>Key moments</h3>
          <ol class="moments">{mom.map((m) => (
            <li key={m.item.id + m.text}>
              <a href={itemHref(m.item.id, ctx)}><time dateTime={m.item.taken_at}>{fmtShort(m.item.taken_at)}</time>
                {typeof m.at === 'number' && <span class="at">{fmtTime(m.at)}</span>}<span>{m.text}</span></a>
            </li>))}</ol>
        </div>
      )}
      {hits.length > 0 && (
        <div><h3>Detected and published</h3>
          <ul class="strip" aria-label={`Detected and published: ${SECTION_TITLE[id]}`}>
            {hits.map((h) => {
              const img = h.frame || h.video?.thumbnail;
              return (
                <li key={h.id}>
                  <button class="strip-btn" onClick={() => onHit(h.id)} aria-label={`Fullscreen: ${titleOf(h)}`}>
                    {img ? <img src={img} alt="" loading="lazy" width={120} height={160} /> : <span class="strip-ph">{whatOf(h)}</span>}
                    <span class="strip-meta" aria-hidden="true">▶ {whatOf(h)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <h3>Media</h3>
      <MediaStrip items={items} ctx={ctx} label={`Media: ${SECTION_TITLE[id]}`} />
    </Panel>
  );
}

export function Home({ route }: { route: Route }) {
  const profile = useProfile();
  const highlights = useHighlights();
  const categories = useCategories();
  const all = useData(getAllItems);
  const published = useData(getPublished);
  const sel = { m: route.query.get('m') || undefined, p: route.query.get('p') || undefined, t: route.query.get('t') || undefined, c: route.query.get('c') || undefined };
  const kind = route.query.get('kind') || undefined;
  const q = route.query.get('q') || undefined;
  const watch = route.query.get('watch') || undefined;

  useEffect(() => {
    const p = profile.data;
    setMeta(SITE_NAME, p ? `The archive of @${p.username} as data: when, where, who and what, from every post, reel, story and highlight.` : undefined, p?.avatar || undefined);
  }, [profile.data]);
  useEffect(() => { if (all.data) settleScroll(); }, [!!all.data]);

  const items = all.data || [];
  const hl = highlights.data || [];
  const hits = published.data || [];
  const mo = months(items);
  const pl = places(items);
  const ppl = people(items);
  const k = kinds(items);
  const tagLabel = (t: { tag: string; kind: string }) => t.kind === 'category' ? categories.data?.find((c) => c.slug === t.tag)?.name || t.tag : t.kind === 'hashtag' ? '#' + t.tag : t.tag;
  const seen = new Set<string>();
  const tags = tagsOf(items).filter((t) => t.kind !== 'category' && t.tag.length <= 32 && !seen.has(t.tag) && seen.add(t.tag)).slice(0, 36).map((t) => ({ ...t, label: tagLabel(t) }));
  const cats = categoryCounts(items, categories.data || []);
  const sections = SECTIONS.map((id) => ({ id, hl: hl.filter((h) => highlightSection(h) === id), items: sectionItems(id, items, hl), hits: hits.filter((h) => hitSection(h) === id) }))
    .filter((s) => s.items.length || s.hits.length);
  const first = items[items.length - 1], last = items[0];
  const openHit = (id?: string) => navigate(withParam(route, 'watch', id), { replace: !!watch || !id, keepScroll: true });
  const pick = (name: string) => (v: string | undefined) => setParam(route, name, v);

  return (
    <>
      <header class="hero">
        <p class="eyebrow">{profile.data ? <>The Instagram archive of <a href={`https://www.instagram.com/${profile.data.username}/`} rel="external noopener">@{profile.data.username}</a>, described by Claude</> : 'An Instagram archive, described by Claude'}</p>
        <h1>{SITE_NAME}, in data</h1>
        {all.error ? <p class="error" role="alert">Could not load the archive: {all.error.message}</p> : !all.data ? <div class="kpis skeleton-kpis" aria-hidden="true" /> : (
          <Kpis items={[
            { label: 'Items', value: items.length, hint: first && last ? `${fmtShort(first.taken_at)} – ${fmtShort(last.taken_at)}` : undefined },
            { label: 'Reels', value: k.reel || 0 }, { label: 'Posts', value: (k.post || 0) + (k.carousel || 0) }, { label: 'Stories', value: k.story || 0 },
            { label: 'Places', value: pl.length }, { label: 'People named', value: ppl.length }, { label: 'Months', value: mo.filter((m) => m.total).length },
          ]} />
        )}
      </header>

      {sections.map((s) => <SectionPanel key={s.id} id={s.id} items={s.items} highlights={s.hl} hits={s.hits} onHit={openHit} />)}

      {mo.length > 0 && (
        <Panel id="p-time" title="Timeline" sub="Activity by month. Pick a month to see it.">
          <Legend />
          <MonthBand months={mo} active={sel.m} onPick={pick('m')} />
          <Selection title={sel.m && mo.find((m) => m.key === sel.m)?.label} items={sel.m ? ctxItems(`month:${sel.m}`, items, hl) : []} ctx={`month:${sel.m}`} onClear={() => pick('m')(undefined)} />
        </Panel>
      )}

      {pl.length > 0 && (
        <Panel id="p-map" title="Places" sub="Where things happened, from locations and the analyses.">
          <div class="map-cols">
            <DotMap places={pl} active={sel.p} onPick={pick('p')} />
            <Bars rows={pl.slice(0, 12).map((p) => ({ id: p.name, name: p.country ? `${p.name} · ${p.country}` : p.name, count: p.count }))} active={sel.p} onPick={pick('p')} label="Places by number of items" />
          </div>
          <Selection title={sel.p} items={sel.p ? ctxItems(`place:${sel.p}`, items, hl) : []} ctx={`place:${sel.p}`} onClear={() => pick('p')(undefined)} />
        </Panel>
      )}

      {tags.length > 0 && (
        <Panel id="p-tags" title="Themes" sub="Tags from the analyses, sized by how many items carry them; and the categories.">
          <Treemap tags={tags} active={sel.t} onPick={pick('t')} label="Tags by number of items" />
          <Selection title={sel.t && `Tag: ${sel.t}`} items={sel.t ? ctxItems(`tag:${sel.t}`, items, hl) : []} ctx={`tag:${sel.t}`} onClear={() => pick('t')(undefined)} />
          {cats.length > 0 && <><h3>Categories</h3>
            <Bars rows={cats.map((c) => ({ id: c.slug, name: c.name, count: c.count }))} active={sel.c} onPick={pick('c')} label="Categories by number of items" />
            <Selection title={sel.c && cats.find((c) => c.slug === sel.c)?.name} items={sel.c ? ctxItems(`cat:${sel.c}`, items, hl) : []} ctx={`cat:${sel.c}`} onClear={() => pick('c')(undefined)} /></>}
        </Panel>
      )}

      <Panel id="p-all" title="Everything, by date" sub="Search and filter every item.">
        <div class="filters">
          <SearchBox route={route} />
          <KindTabs active={kind} onPick={(v) => setParam(route, 'kind', v)} />
        </div>
        <Feed query={{ kind, q }} layout="timeline" ctx={q ? `q:${q}` : kind ? `kind:${kind}` : 'all'} emptyText={q ? `Nothing matches “${q}”.` : 'Nothing here yet.'} />
      </Panel>

      {watch && hits.length > 0 && (
        <VideoFeed title="Detected and published" videos={hits.map(hitSlide)} start={watch} onClose={() => openHit(undefined)}
          onIndex={(id) => history.replaceState(history.state, '', withParam(route, 'watch', id))} />
      )}
    </>
  );
}
