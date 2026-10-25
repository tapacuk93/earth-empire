import { useEffect, useState } from 'preact/hooks';
import { HitCard, hitSlide } from '../components/MonitorCard';
import { VideoFeed } from '../components/VideoFeed';
import { fetchMore, getHits, labelOf, setPublished, type Hit } from '../monitor';
import { navigate, type Route } from '../router';
import { setMeta } from '../util';
import { withParam } from './Home';
import { Bars, Kpis } from '../components/Charts';
import { hitSection, hitSuggestion, SECTION_TITLE, SECTIONS, type SectionId } from '../sections';

const KINDS: [string | undefined, string][] = [[undefined, 'All'], ['name', 'Names'], ['language', 'Language']];

export function DetectedPage({ route }: { route: Route }) {
  const kind = route.query.get('kind') || undefined;
  const watch = route.query.get('watch') || undefined;
  const [hits, setHits] = useState<Hit[]>();
  const [next, setNext] = useState<string | null>(null);
  const [err, setErr] = useState<string>();
  const [msg, setMsg] = useState('');
  const [n, setN] = useState(10);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setMeta('Detected', undefined, undefined, true); }, []);
  useEffect(() => {
    setHits(undefined); setErr(undefined);
    getHits({ kind }).then((p) => { setHits(p.hits); setNext(p.next); }, (e) => setErr(e.message));
  }, [kind]);

  const more = async () => {
    if (!next) return;
    setBusy(true);
    try { const p = await getHits({ kind, before: next }); setHits([...(hits || []), ...p.hits]); setNext(p.next); } catch (e) { setMsg(`Could not load more: ${(e as Error).message}`); }
    setBusy(false);
  };
  const fetchN = async (e: Event) => {
    e.preventDefault();
    setBusy(true); setMsg(`Asking the monitor for ${n} more videos…`);
    try {
      const r = await fetchMore(n);
      setMsg(`Queued ${r.queued ?? n} videos to scan${r.to_discover ? `; ${r.to_discover} more to discover further back` : ''}. New hits appear here as they are found.`);
    } catch (err) { setMsg(/429/.test((err as Error).message) ? 'The scan queue is full; try again later.' : `Could not ask for more: ${(err as Error).message}`); }
    setBusy(false);
  };
  const [pick, setPick] = useState<Record<string, SectionId>>({});
  const publish = async (h: Hit, on: boolean, section?: SectionId) => {
    try {
      const r = await setPublished(h.id, on, section);
      setHits((hs) => hs?.map((x) => (x.id === h.id ? { ...x, ...r, published_at: r.published_at ?? (on ? new Date().toISOString() : null), section: on ? (r as { section?: string }).section || section : null } as Hit : x)));
      setMsg(on ? `Published to Home, in “${SECTION_TITLE[section || 'common']}”.` : 'Removed from Home.');
    } catch (e) { setMsg(`Could not change it: ${(e as Error).message}`); }
  };
  const open = (id?: string) => navigate(withParam(route, 'watch', id), { replace: !!watch || !id, keepScroll: true });

  return (
    <>
      <header class="page-head">
        <h1>Detected</h1>
        <p class="lead">Moments the monitor heard, most certain first. No hit is certain: low-confidence ones are kept and marked, with the words around them.</p>
        <div class="row">
          <div class="kinds" role="group" aria-label="Kind of hit">
            {KINDS.map(([k, l]) => <button key={l} class="kind" aria-pressed={kind === k} onClick={() => navigate(withParam(route, 'kind', k), { replace: true, keepScroll: true })}>{l}</button>)}
          </div>
          {!!hits?.length && <button class="btn small ghost" onClick={() => open(hits[0].id)}>Fullscreen</button>}
        </div>
        <form class="row fetch" onSubmit={fetchN}>
          <label for="fetch-n">Scan more videos</label>
          <input id="fetch-n" type="number" min={1} max={50} value={n} onInput={(e) => setN(Math.max(1, Math.min(50, Number((e.target as HTMLInputElement).value) || 1)))} />
          <button class="btn small" type="submit" disabled={busy}>Fetch {n} more</button>
        </form>
        <p class="muted small" role="status">{msg}</p>
      </header>
      {!!hits?.length && (
        <section class="ipanel" aria-labelledby="det-sum">
          <header class="ipanel-head"><h2 id="det-sum">At a glance</h2><p class="muted">The hits loaded below</p></header>
          <Kpis items={[
            { label: 'Hits', value: hits.length }, { label: 'Likely', value: hits.filter((h) => labelOf(h) === 'likely').length },
            { label: 'Possible', value: hits.filter((h) => labelOf(h) === 'possible').length }, { label: 'Low confidence', value: hits.filter((h) => labelOf(h) === 'low confidence').length },
            { label: 'Published', value: hits.filter((h) => h.published_at).length },
          ]} />
          <div class="sec-cols">
            <div><h3>Confidence</h3><Bars label="Hits by confidence" onPick={() => undefined}
              rows={[9, 8, 7, 6, 5, 4, 3, 2, 1, 0].map((b) => ({ id: String(b), name: `${b * 10}–${b * 10 + 9}%`, count: hits.filter((h) => Math.min(9, Math.floor((h.confidence ?? 0) * 10)) === b).length })).filter((r) => r.count)} /></div>
            <div><h3>Where</h3><Bars label="Hits by platform" onPick={() => undefined}
              rows={Object.entries(hits.reduce((m, h) => { const k = h.source?.name || h.platform || '?'; m[k] = (m[k] || 0) + 1; return m; }, {} as Record<string, number>)).map(([name, count]) => ({ id: name, name, count })).sort((a, b) => b.count - a.count)} /></div>
          </div>
        </section>
      )}
      {err ? <p class="error" role="alert">Could not load the hits: {err}</p>
        : !hits ? <p class="muted">Loading…</p>
        : !hits.length ? <p class="empty">Nothing detected yet.</p>
        : (
          <ul class="mon-list" role="list">
            {hits.map((h) => (
              <HitCard key={h.id} h={h} onWatch={() => open(h.id)}>
                {(() => {
                  const sug = hitSuggestion(h);
                  const chosen = pick[h.id] || sug?.section || 'common';
                  return (
                    <>
                      {sug && <p class="suggest"><span class="muted">Suggested section:</span> <b>{SECTION_TITLE[sug.section]}</b>{sug.reason && <span class="muted"> — {sug.reason}</span>}</p>}
                      <p class="row">
                        {h.published_at
                          ? <><span class="kind-pill k-story">On Home · {SECTION_TITLE[hitSection(h)]}</span><button class="btn small ghost" onClick={() => publish(h, false)}>Remove</button></>
                          : <>
                              <label class="sr-only" for={`sec-${h.id}`}>Section for this hit</label>
                              <select id={`sec-${h.id}`} class="sec-pick" value={chosen} onChange={(e) => setPick({ ...pick, [h.id]: (e.target as HTMLSelectElement).value as SectionId })}>
                                {SECTIONS.map((s) => <option key={s} value={s}>{SECTION_TITLE[s]}{sug?.section === s ? ' (suggested)' : ''}</option>)}
                              </select>
                              <button class="btn small plus" onClick={() => publish(h, true, chosen)} aria-label={`Publish to Home in ${SECTION_TITLE[chosen]}: ${h.video?.title || h.matched}`}>+ Publish</button>
                            </>}
                      </p>
                    </>
                  );
                })()}
              </HitCard>
            ))}
          </ul>
        )}
      {next && <div class="more"><button class="btn" onClick={more} disabled={busy}>Load more</button></div>}
      {watch && !!hits?.length && (
        <VideoFeed title="Detected" start={watch} onClose={() => open(undefined)} videos={hits.map(hitSlide)}
          onIndex={(id) => history.replaceState(history.state, '', withParam(route, 'watch', id))} />
      )}
    </>
  );
}
