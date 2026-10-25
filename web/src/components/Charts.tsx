// Small dependency-free charts: KPI tiles, the month band, a dot map, a treemap and bar lists.
// Every mark that does something is a real button or link with a text label.
import type { ComponentChildren } from 'preact';
import type { Month, Place } from '../stats';
import type { Item, Tag } from '../types';
import { itemHref } from '../context';
import { cover, fmtShort, KIND_LABEL } from '../util';

export const KIND_ORDER = ['reel', 'post', 'carousel', 'story'];

export function Kpis({ items }: { items: { label: string; value: string | number; hint?: string }[] }) {
  return (
    <dl class="kpis">
      {items.map((k) => (
        <div key={k.label} class="kpi"><dt>{k.label}</dt><dd>{k.value}</dd>{k.hint && <span class="kpi-hint">{k.hint}</span>}</div>
      ))}
    </dl>
  );
}

export function Legend() {
  return (
    <ul class="legend" aria-label="Kinds">
      {KIND_ORDER.map((k) => <li key={k}><span class={`sw k-${k}`} aria-hidden="true" />{KIND_LABEL[k]}</li>)}
    </ul>
  );
}

/** Activity by month: one stacked bar per month, a true time axis. */
export function MonthBand({ months, active, onPick }: { months: Month[]; active?: string; onPick: (key: string | undefined) => void }) {
  const max = Math.max(1, ...months.map((m) => m.total));
  const years = new Set<string>();
  return (
    <div class="band-wrap">
      <ol class="band" style={{ '--n': String(months.length) }}>
        {months.map((m) => {
          const y = m.key.slice(0, 4);
          const newYear = !years.has(y);
          years.add(y);
          return (
            <li key={m.key} class={newYear ? 'year-start' : ''}>
              <button class="band-bar" aria-pressed={active === m.key} disabled={!m.total}
                aria-label={`${m.label}: ${m.total} item${m.total === 1 ? '' : 's'}`} title={`${m.label}: ${m.total}`}
                onClick={() => onPick(active === m.key ? undefined : m.key)}>
                <span class="stack" style={{ height: `${(m.total / max) * 100}%` }}>
                  {KIND_ORDER.filter((k) => m.byKind[k]).map((k) => <span key={k} class={`seg k-${k}`} style={{ flexGrow: m.byKind[k] }} />)}
                </span>
              </button>
              <span class="band-label" aria-hidden="true">{newYear ? m.label : m.label.slice(0, 3)}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Places with coordinates on a fitted lat/lng plot; the rest listed by name. */
export function DotMap({ places, active, onPick }: { places: Place[]; active?: string; onPick: (name: string | undefined) => void }) {
  const pts = places.filter((p) => typeof p.lat === 'number' && typeof p.lng === 'number');
  if (!pts.length) return null;
  let [minX, maxX, minY, maxY] = [180, -180, 90, -90];
  pts.forEach((p) => { minX = Math.min(minX, p.lng!); maxX = Math.max(maxX, p.lng!); minY = Math.min(minY, p.lat!); maxY = Math.max(maxY, p.lat!); });
  const span = Math.max(8, maxX - minX, (maxY - minY) * 1.6);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const W = 100, H = 62;
  const x = (lng: number) => ((lng - cx) / span) * W * 0.8 + W / 2;
  const y = (lat: number) => H / 2 - ((lat - cy) / (span / 1.6)) * H * 0.8;
  const maxC = Math.max(...pts.map((p) => p.count));
  const step = span > 60 ? 30 : span > 20 ? 10 : span > 6 ? 2 : 1;
  const grid: ComponentChildren[] = [];
  for (let g = Math.ceil((cx - span) / step) * step; g <= cx + span; g += step) grid.push(<line key={`v${g}`} x1={x(g)} x2={x(g)} y1={0} y2={H} />);
  for (let g = Math.ceil((cy - span) / step) * step; g <= cy + span; g += step) grid.push(<line key={`h${g}`} x1={0} x2={W} y1={y(g)} y2={y(g)} />);
  return (
    <svg class="dotmap" viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Places on a map">
      <g class="grid-lines" aria-hidden="true">{grid}</g>
      {pts.map((p) => {
        const r = 1.4 + 3.2 * Math.sqrt(p.count / maxC);
        return (
          <g key={p.name} class={`dot ${active === p.name ? 'on' : ''}`} role="button" tabIndex={0} aria-pressed={active === p.name}
            aria-label={`${p.name}${p.country ? ', ' + p.country : ''}: ${p.count} item${p.count === 1 ? '' : 's'}`}
            onClick={() => onPick(active === p.name ? undefined : p.name)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(active === p.name ? undefined : p.name); } }}>
            <circle cx={x(p.lng!)} cy={y(p.lat!)} r={r} />
            <text x={x(p.lng!) + r + 0.8} y={y(p.lat!) + 1}>{p.name}</text>
          </g>
        );
      })}
    </svg>
  );
}

// Squarified treemap (Bruls, Huizing, van Wijk).
interface Rect { x: number; y: number; w: number; h: number }
function squarify<T extends { v: number }>(data: T[], box: Rect): (T & Rect)[] {
  const out: (T & Rect)[] = [];
  const total = data.reduce((s, d) => s + d.v, 0) || 1;
  const scale = (box.w * box.h) / total;
  let rest = data.map((d) => ({ ...d, a: d.v * scale }));
  let r = { ...box };
  while (rest.length) {
    const short = Math.min(r.w, r.h);
    let row: typeof rest = [];
    let worst = Infinity;
    for (const d of rest) {
      const next = [...row, d];
      const sum = next.reduce((s, q) => s + q.a, 0);
      const mx = Math.max(...next.map((q) => q.a)), mn = Math.min(...next.map((q) => q.a));
      const w = Math.max((short * short * mx) / (sum * sum), (sum * sum) / (short * short * mn));
      if (w > worst) break;
      worst = w; row = next;
    }
    const sum = row.reduce((s, q) => s + q.a, 0);
    const thick = sum / short;
    let off = 0;
    for (const d of row) {
      const len = d.a / thick;
      out.push(r.w >= r.h ? { ...d, x: r.x, y: r.y + off, w: thick, h: len } : { ...d, x: r.x + off, y: r.y, w: len, h: thick });
      off += len;
    }
    r = r.w >= r.h ? { x: r.x + thick, y: r.y, w: r.w - thick, h: r.h } : { x: r.x, y: r.y + thick, w: r.w, h: r.h - thick };
    rest = rest.slice(row.length);
  }
  return out;
}

const GROUP: Record<string, string> = { person: 'people', place: 'places', country: 'places', object: 'things', animal: 'things', brand: 'things', category: 'cats', hashtag: 'tags', keyword: 'tags', mood: 'tags', occasion: 'tags' };

export function Treemap({ tags, active, onPick, label }: { tags: (Tag & { label: string })[]; active?: string; onPick: (t: string | undefined) => void; label: string }) {
  const cells = squarify(tags.map((t) => ({ ...t, v: t.count })), { x: 0, y: 0, w: 100, h: 100 });
  return (
    <ul class="treemap" aria-label={label}>
      {cells.map((c) => (
        <li key={`${c.kind}:${c.tag}`} style={{ left: `${c.x}%`, top: `${c.y}%`, width: `${c.w}%`, height: `${c.h}%` }}>
          <button class={`cell g-${GROUP[c.kind] || 'tags'}`} aria-pressed={active === c.tag} onClick={() => onPick(active === c.tag ? undefined : c.tag)}
            aria-label={`${c.label}, ${c.kind}, ${c.count} item${c.count === 1 ? '' : 's'}`} title={`${c.label} · ${c.count}`}>
            <span class="cell-label">{c.label}</span><span class="cell-n">{c.count}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function Bars({ rows, active, onPick, label }: { rows: { id: string; name: string; count: number }[]; active?: string; onPick: (id: string | undefined) => void; label: string }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <ul class="hbars" aria-label={label}>
      {rows.map((r) => (
        <li key={r.id}>
          <button aria-pressed={active === r.id} onClick={() => onPick(active === r.id ? undefined : r.id)} aria-label={`${r.name}: ${r.count}`}>
            <span class="hbar-name">{r.name}</span>
            <span class="hbar-track" aria-hidden="true"><span class="hbar-val" style={{ width: `${(r.count / max) * 100}%` }} /></span>
            <span class="hbar-n">{r.count}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Media inside a panel: a strip of covers that open the vertical feed in this context. */
export function MediaStrip({ items: all, ctx, label, max = 24, videosFirst }: { items: Item[]; ctx: string; label: string; max?: number; videosFirst?: boolean }) {
  if (!all.length) return null;
  const isVideo = (it: Item) => (it.media[0] || it.repost_of?.media?.[0])?.type === 'video';
  const items = videosFirst ? [...all.filter(isVideo), ...all.filter((it) => !isVideo(it))] : all;
  return (
    <ul class="strip" aria-label={label}>
      {items.slice(0, max).map((it) => {
        const src = cover(it);
        const video = (it.media[0] || it.repost_of?.media?.[0])?.type === 'video';
        return (
          <li key={it.id}>
            <a href={itemHref(it.id, ctx)} aria-label={`${KIND_LABEL[it.kind]}, ${fmtShort(it.taken_at)}: ${it.summary || it.caption || ''}`.slice(0, 200)}>
              {src ? <img src={src} alt="" loading="lazy" decoding="async" width={120} height={160} /> : <span class="strip-ph">{it.summary}</span>}
              <span class="strip-meta" aria-hidden="true">{video ? '▶ ' : ''}{fmtShort(it.taken_at)}</span>
            </a>
          </li>
        );
      })}
      {items.length > max && <li class="strip-more"><a href={itemHref(items[max].id, ctx)}>+{items.length - max} more</a></li>}
    </ul>
  );
}
