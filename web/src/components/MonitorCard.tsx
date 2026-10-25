import type { MonitorVideo } from '../monitor';
import { fmtShort } from '../util';
import { Icon } from './icons';

export const confPct = (c?: number) => (typeof c === 'number' ? `${Math.round(c * 100)}%` : '');

export function MonitorMeta({ v }: { v: MonitorVideo }) {
  return (
    <>
      <p class="mon-src">{v.accountName || (v.account ? '@' + v.account : v.platform)}{v.takenAt && <> · <time dateTime={v.takenAt}>{fmtShort(v.takenAt)}</time></>}</p>
      <p class="mon-title">{v.title}</p>
      {v.matches[0]?.text && <p class="mon-quote">“{v.matches[0].text}”</p>}
      <p class="mon-tags">
        {typeof v.confidence === 'number' && <span class={`conf ${v.low ? 'low' : ''}`}>{v.low ? 'Low confidence · ' : 'Confidence '}{confPct(v.confidence)}</span>}
        {v.sourceUrl && <a href={v.sourceUrl} rel="external noopener">Source <Icon name="external" size={13} /></a>}
      </p>
    </>
  );
}

export function MonitorCard({ v, onWatch, children }: { v: MonitorVideo; onWatch: () => void; children?: preact.ComponentChildren }) {
  return (
    <li class={`mon-card ${v.low ? 'is-low' : ''}`}>
      <button class="mon-thumb" onClick={onWatch} aria-label={`Watch fullscreen: ${v.title}`}>
        {v.cover ? <img src={v.cover} alt="" loading="lazy" decoding="async" width={270} height={480} /> : <span />}
        <span class="mon-play" aria-hidden="true"><Icon name="play" size={22} /></span>
      </button>
      <div class="mon-body">
        <MonitorMeta v={v} />
        {children}
      </div>
    </li>
  );
}
