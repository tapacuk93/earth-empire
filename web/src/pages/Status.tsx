import { useEffect, useState } from 'preact/hooks';
import { getStatus, type Component, type State, type Status } from '../live';
import { getMonitorStatus } from '../monitor';
import { useData } from '../components/Profile';
import { Kpis } from '../components/Charts';
import { fmtDateTime, setMeta } from '../util';

const STATE_LABEL: Record<State, string> = { ok: 'Working', degraded: 'Degraded', down: 'Down', off: 'Off' };
const rel = (s?: string | null) => {
  if (!s) return 'never';
  const d = (Date.now() - Date.parse(s)) / 1000;
  if (isNaN(d)) return s;
  if (d < 60) return `${Math.max(0, Math.round(d))} s ago`;
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  return fmtDateTime(s);
};
const pct = (p?: number | null) => (typeof p === 'number' ? Math.round(p > 1 ? p : p * 100) : null);

function Pill({ state }: { state: State }) {
  return <span class={`state s-${state}`}><span class="dot" aria-hidden="true" />{STATE_LABEL[state] || state}</span>;
}

function Details({ d }: { d?: Record<string, unknown> }) {
  const entries = Object.entries(d || {});
  if (!entries.length) return null;
  return (
    <dl class="kv">
      {entries.map(([k, v]) => (
        <div key={k}><dt>{k.replace(/_/g, ' ')}</dt>
          <dd>{Array.isArray(v) ? v.map((x) => (typeof x === 'object' ? JSON.stringify(x) : String(x))).join(', ')
            : v && typeof v === 'object'
            ? Object.entries(v as Record<string, unknown>).map(([a, b]) => `${a.replace(/_/g, ' ')}: ${typeof b === 'object' ? JSON.stringify(b) : String(b)}`).join(' · ')
            : String(v)}</dd></div>
      ))}
    </dl>
  );
}

function ComponentCard({ c }: { c: Component }) {
  return (
    <li class={`comp s-${c.state}`}>
      <div class="comp-head"><h3>{c.name || c.id}</h3><Pill state={c.state} /></div>
      <p class="muted small">Last success {rel(c.last_success)}</p>
      {c.last_error?.message && <p class="comp-err"><span class="sr-only">Last error: </span>{c.last_error.message} <span class="muted small">({rel(c.last_error.at)})</span></p>}
      <Details d={c.details} />
    </li>
  );
}

function MonitorStats() {
  const m = useData(getMonitorStatus);
  return (
    <section class="panel" aria-labelledby="stats-h">
      <h2 id="stats-h">Monitor stats</h2>
      {m.error ? <p class="muted">Not available: {m.error.message}</p> : !m.data ? <p class="muted">Loading…</p> : <Details d={m.data} />}
    </section>
  );
}

export function StatusPage() {
  const [st, setSt] = useState<Status>();
  const [err, setErr] = useState<string>();
  useEffect(() => { setMeta('Status', 'Live activity and health of Earth Empire’s parts.', undefined, true); }, []);
  useEffect(() => {
    let live = true, timer = 0;
    const tick = () => {
      if (!document.hidden) getStatus().then((s) => { if (live) { setSt(s); setErr(undefined); } }, (e) => live && setErr(e.message));
      timer = window.setTimeout(tick, 4000);
    };
    tick();
    const vis = () => { if (!document.hidden) { clearTimeout(timer); tick(); } };
    document.addEventListener('visibilitychange', vis);
    return () => { live = false; clearTimeout(timer); document.removeEventListener('visibilitychange', vis); };
  }, []);

  const jobs = st?.activity?.jobs || [];
  const events = st?.activity?.events || [];
  return (
    <>
      <header class="page-head">
        <h1>Status</h1>
        {st ? <p class="lead">Overall: <Pill state={st.overall} /> <span class="muted small">updated {rel(st.generated_at)}, refreshes every 4 s</span></p>
          : <p class="muted">{err ? `Could not load the status: ${err}` : 'Loading…'}</p>}
        {st && err && <p class="error small" role="alert">Last refresh failed: {err}</p>}
      </header>
      {st && (
        <>
          <Kpis items={(['ok', 'degraded', 'down', 'off'] as State[]).map((s) => ({ label: STATE_LABEL[s], value: st.components.filter((c) => c.state === s).length }))
            .concat([{ label: 'Running now', value: st.activity?.jobs?.length || 0 }])} />
          <section aria-labelledby="comp-h">
            <h2 id="comp-h" class="sr-only">Components</h2>
            <ul class="comps" role="list">{st.components.map((c) => <ComponentCard key={c.id} c={c} />)}</ul>
          </section>
          <section class="panel" aria-labelledby="act-h">
            <h2 id="act-h">Activity</h2>
            <h3>Working on now</h3>
            {jobs.length ? (
              <ul class="jobs" role="list">
                {jobs.map((j, i) => {
                  const p = pct(j.progress);
                  return (
                    <li key={i}>
                      <span class="job-what"><b>{j.component}</b> · {j.item ? <a href={`/item/${encodeURIComponent(j.item)}`}>{j.what}</a> : j.what}</span>
                      {p !== null && <progress max={100} value={p} aria-label={`${j.what}: ${p}%`} />}
                      <span class="muted small">{p !== null ? `${p}% · ` : ''}{typeof j.elapsed_s === 'number' ? `${Math.round(j.elapsed_s)} s` : rel(j.started_at)}</span>
                    </li>
                  );
                })}
              </ul>
            ) : <p class="muted">Nothing running right now.</p>}
            <h3>Latest events</h3>
            <ol class="events">
              {events.map((e, i) => (
                <li key={i} class={e.ok === false ? 'bad' : ''}>
                  <time dateTime={e.at} title={fmtDateTime(e.at)}>{rel(e.at)}</time>
                  <span class="ev-comp">{e.component}</span>
                  <span>{e.ok === false && <span class="sr-only">Failed: </span>}{e.item ? <a href={`/item/${encodeURIComponent(e.item)}`}>{e.text}</a> : e.text}</span>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
      <MonitorStats />
    </>
  );
}
