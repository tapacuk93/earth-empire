import { heardOf, isLow, labelOf, safeUrl, titleOf, whatOf, type Hit } from '../monitor';
import type { FeedVideo } from './VideoFeed';
import { fmtShort, fmtTime } from '../util';
import { Icon } from './icons';

export const confPct = (c?: number) => (typeof c === 'number' ? `${Math.round(c * 100)}%` : '');

/** What a hit is, where it was heard, how sure, and the words around it. */
/** A hit's facts. `fold` keeps the transcript, translation and notes behind a toggle, so the clip keeps the screen. */
export function HitMeta({ h, full, fold }: { h: Hit; full?: boolean; fold?: boolean }) {
  const at = safeUrl(h.at_url) || safeUrl(h.video?.url);
  return (
    <>
      {heardOf(h) && <p class="heard-chip" title="What sounds in the clip" lang={h.excerpt?.language || undefined}>“{heardOf(h)}”</p>}
      <p class="mon-src">{h.source?.name || (h.account ? '@' + h.account : '')}{h.platform && ` · ${h.platform}`}
        {h.video?.posted_at && <> · <time dateTime={h.video.posted_at}>{fmtShort(h.video.posted_at)}</time></>}</p>
      <p class="mon-title">{titleOf(h)}</p>
      <p class="mon-what">{h.kind === 'language' ? 'Language: ' : 'Name: '}<b>{whatOf(h)}</b>
        {h.kind === 'name' && h.phrase && <span class="muted"> (phrase “{h.phrase}”)</span>}
        {typeof h.start === 'number' && <span class="muted"> at {fmtTime(h.start)}</span>}</p>
      <p class="mon-tags">
        {typeof h.confidence === 'number' && <span class={`conf ${isLow(h) ? 'low' : ''}`}>{labelOf(h)} · {confPct(h.confidence)}</span>}
        {at && <a href={at} rel="external noopener">Open at the moment <Icon name="external" size={13} /></a>}
      </p>
      {fold ? (h.excerpt?.text || (full && h.notes?.length)) && <details class="mon-more"><summary>Transcript and notes</summary>
      {h.excerpt?.text && <blockquote class="mon-quote" lang={h.excerpt.language || undefined}>{h.excerpt.text}</blockquote>}
      {full && h.excerpt?.en && h.excerpt.en !== h.excerpt.text && <p class="mon-en">{h.excerpt.en}</p>}
      {full && !!h.notes?.length && <ul class="mon-notes">{h.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      </details> : <>
      {h.excerpt?.text && <blockquote class="mon-quote" lang={h.excerpt.language || undefined}>{h.excerpt.text}</blockquote>}
      {full && h.excerpt?.en && h.excerpt.en !== h.excerpt.text && <p class="mon-en">{h.excerpt.en}</p>}
      {full && !!h.notes?.length && <ul class="mon-notes">{h.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      </>}
    </>
  );
}

export function HitCard({ h, onWatch, children }: { h: Hit; onWatch: () => void; children?: preact.ComponentChildren }) {
  const img = h.frame || h.video?.thumbnail;
  return (
    <li class={`mon-card ${isLow(h) ? 'is-low' : ''}`}>
      <button class="mon-thumb" onClick={onWatch} aria-label={`Fullscreen: ${titleOf(h)}`}>
        {img ? <img src={img} alt="" loading="lazy" decoding="async" width={270} height={480} /> : <span class="mon-noimg">{whatOf(h)}</span>}
        <span class="mon-play" aria-hidden="true"><Icon name="play" size={22} /></span>
      </button>
      <div class="mon-body">
        <HitMeta h={h} full />
        {h.clip && <audio class="mon-clip" controls preload="none" src={h.clip} aria-label={`Clip around the moment: ${titleOf(h)}`} />}
        {children}
      </div>
    </li>
  );
}

/** A hit in the fullscreen mode: its frame with the clip around the moment. */
export const hitSlide = (h: Hit): FeedVideo => ({
  id: h.id, url: h.clip || '', cover: h.frame || h.video?.thumbnail || undefined, label: titleOf(h), overlay: <HitMeta h={h} />,
});
