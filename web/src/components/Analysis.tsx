import type { Analysis as A, Appearance, Item } from '../types';
import { fmtDate, fmtTime, igProfile } from '../util';

const BASIS: Record<string, string> = {
  tag: 'named from a photo tag', mention: 'named from a mention', caption: 'named in the caption', speech: 'named in the speech',
  'on-screen text': 'named in on-screen text', 'description only': 'not named; described only',
};

export type Seek = (media: number, at: number) => void;

function Who({ who }: { who?: string | null }) {
  if (!who) return <span class="who unnamed">Unnamed person</span>;
  if (who.startsWith('@')) return <a class="who" href={igProfile(who)} rel="external noopener">{who}</a>;
  return <span class="who">{who}</span>;
}

function Appears({ a, seek, multi, hasVideo }: { a: Appearance; seek: Seek; multi: boolean; hasVideo: (i: number) => boolean }) {
  const m = a.media ?? 0;
  const where = multi ? `slide ${m + 1}` : '';
  if (typeof a.from === 'number' && hasVideo(m)) {
    const label = `${where ? where + ', ' : ''}${fmtTime(a.from)}${typeof a.to === 'number' ? '–' + fmtTime(a.to) : ''}`;
    return <button class="seek" onClick={() => seek(m, a.from!)} aria-label={`Play from ${label}`}>{label}</button>;
  }
  return where ? <button class="seek" onClick={() => seek(m, 0)}>{where}</button> : null;
}

function Chips({ list, search }: { list?: string[]; search?: boolean }) {
  if (!list?.length) return null;
  return <ul class="tags" role="list">{list.map((x) => <li key={x}>{search ? <a class="tag" href={`/?q=${encodeURIComponent(x)}`}>{x}</a> : <span class="tag">{x}</span>}</li>)}</ul>;
}

export function AnalysisView({ item, a, seek }: { item: Item; a: A; seek: Seek }) {
  const hasVideo = (i: number) => item.media[i]?.type === 'video';
  const multi = item.media.length > 1;
  const when = a.when && [a.when.date && fmtDate(a.when.date), a.when.time_of_day, a.when.season, a.when.occasion].filter(Boolean).join(' · ');
  const where = a.where && [a.where.place, a.where.kind, a.where.country].filter(Boolean).join(' · ');
  const events = (a.events || []).slice().sort((x, y) => (x.media ?? 0) - (y.media ?? 0) || x.at - y.at);
  const things = [...(a.objects || []), ...(a.animals || []), ...(a.brands || [])];

  return (
    <section class="analysis" aria-labelledby="analysis-h">
      <h2 id="analysis-h">What’s in it</h2>
      {a.what && <p class="what">{a.what}</p>}

      {(when || where || a.mood || a.music || (a.language && a.language !== "none")) && (
        <dl class="facts">
          {when && <div><dt>When</dt><dd>{when}{a.when?.basis && <span class="basis">from {a.when.basis}</span>}</dd></div>}
          {where && <div><dt>Where</dt><dd>{where}{a.where?.basis && <span class="basis">from {a.where.basis}</span>}</dd></div>}
          {a.mood && <div><dt>Mood</dt><dd>{a.mood}</dd></div>}
          {a.language && a.language !== 'none' && <div><dt>Language</dt><dd>{a.language}</dd></div>}
          {a.music && <div><dt>Music</dt><dd>{a.music}</dd></div>}
        </dl>
      )}

      {!!a.people?.length && (
        <section aria-labelledby="people-h">
          <h3 id="people-h">People</h3>
          <ul class="people" role="list">
            {a.people.map((p, i) => (
              <li key={i} class="person">
                <div class="person-head">
                  <Who who={p.who} />
                  {p.role && <span class="role">{p.role}</span>}
                </div>
                {p.description && <p>{p.description}</p>}
                <p class="basis">{!p.who && p.basis && p.basis !== 'description only' ? `not named; known from the ${p.basis}` : BASIS[p.basis || ''] || (p.basis ? `basis: ${p.basis}` : '')}</p>
                {!!p.appears?.length && (
                  <p class="appears"><span class="muted">Appears </span>
                    {p.appears.map((ap, j) => <Appears key={j} a={ap} seek={seek} multi={multi} hasVideo={hasVideo} />)}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {!!events.length && (
        <section aria-labelledby="events-h">
          <h3 id="events-h">Timeline</h3>
          <ol class="timeline">
            {events.map((e, i) => {
              const m = e.media ?? 0;
              const label = `${multi ? `Slide ${m + 1}, ` : ''}${fmtTime(e.at)}`;
              return (
                <li key={i}>
                  <button class="event" onClick={() => seek(m, e.at)} disabled={!hasVideo(m)}>
                    <span class="at">{label}</span><span>{e.text}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {a.speech?.transcript && (
        <section aria-labelledby="speech-h">
          <h3 id="speech-h">Transcript{a.speech.language && <span class="muted"> · {a.speech.language}</span>}</h3>
          <blockquote class="transcript">{a.speech.transcript}</blockquote>
        </section>
      )}

      {!!a.on_screen_text?.length && (
        <section aria-labelledby="ost-h">
          <h3 id="ost-h">On-screen text</h3>
          <ul class="ost" role="list">{a.on_screen_text.map((t, i) => <li key={i}>“{t}”</li>)}</ul>
        </section>
      )}

      {!!things.length && (<section aria-labelledby="obj-h"><h3 id="obj-h">Things seen</h3><Chips list={things} /></section>)}

      {a.context && (<section aria-labelledby="ctx-h"><h3 id="ctx-h">Context</h3><p>{a.context}</p></section>)}

      {!!a.keywords?.length && (<section aria-labelledby="kw-h"><h3 id="kw-h">Keywords</h3><Chips list={a.keywords} search /></section>)}

      <p class="muted small">Described by {a.model ? a.model : 'Claude'}{a.analyzed_at ? ` on ${fmtDate(a.analyzed_at)}` : ''}. People are named only from what the post itself says.</p>
    </section>
  );
}
