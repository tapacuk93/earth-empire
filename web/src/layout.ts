// The mosaics' layout, computed in the browser until the API serves GET /v1/layout:
// tiles grouped by highlight, placed so videos that share tags sit close, sized by recency × importance.
import type { Hit } from './monitor';
import { titleOf, whatOf } from './monitor';
import { itemTags } from './tags';
import type { Highlight, Item, Tag } from './types';
import { cover } from './util';

export interface Tile {
  id: string;
  hit?: Hit;
  item?: Item;
  x: number; y: number; r: number;   // centre and half-size, in layout units
  cover?: string;
  video?: string;
  group: string;                      // highlight title (or "Detected")
  date?: string;
  text: string;                       // short description
  tags: Set<string>;
}
export interface Group { name: string; x: number; y: number; r: number }
export interface Mosaic { tiles: Tile[]; groups: Group[]; width: number; height: number }

const tagSet = (it: Item) => new Set([...itemTags(it).values()].map((t) => t.tag));
const hitTags = (h: Hit) => new Set([h.phrase, h.matched, h.source?.name, h.platform, h.language].filter(Boolean).map((s) => String(s).toLowerCase()));

export function similarity(a: Set<string>, b: Set<string>): number {
  if (!a.size || !b.size) return 0;
  let n = 0;
  for (const t of a) if (b.has(t)) n++;
  return n / (a.size + b.size - n);
}

function importance(it: Item): number {
  const c = it.counts || {};
  const engagement = Math.log10(1 + (c.likes || 0) + (c.views || 0) / 10 + (c.plays || 0) / 10) / 5;
  const people = Math.min(1, (it.analysis?.people?.length || 0) / 3);
  const events = Math.min(1, (it.analysis?.events?.length || 0) / 4);
  return Math.min(1, 0.35 + 0.35 * Math.min(1, engagement) + 0.15 * people + 0.15 * events);
}
function recency(iso: string | undefined, newest: number): number {
  const t = iso ? Date.parse(iso) : NaN;
  if (isNaN(t)) return 0.5;
  return Math.exp(-Math.max(0, newest - t) / (365 * 864e5));
}

/** One half: its items (grouped by their highlight in this half, or "Feed") and hits. */
export function buildMosaic(items: Item[], halfHighlights: Highlight[], hits: Hit[]): Mosaic {
  const hlIds = new Map(halfHighlights.map((h) => [h.id, h.title]));
  const newest = Math.max(0, ...items.map((i) => Date.parse(i.taken_at) || 0), ...hits.map((h) => Date.parse(h.video?.posted_at || h.found_at || '') || 0));
  const tiles: Tile[] = [];
  for (const it of items) {
    const m = it.media[0] || it.repost_of?.media?.[0];
    const g = (it.highlights || []).find((h) => hlIds.has(h.id))?.title || 'Feed';
    const s = 0.6 + 1.6 * recency(it.taken_at, newest) * importance(it);
    tiles.push({ id: it.id, item: it, x: 0, y: 0, r: s, cover: cover(it), video: m?.type === 'video' ? m.url : undefined, group: g,
      date: it.taken_at, text: it.summary || it.caption || '', tags: tagSet(it) });
  }
  for (const h of hits) {
    const s = 0.6 + 1.6 * recency(h.video?.posted_at || h.found_at, newest) * (h.confidence ?? 0.5);
    tiles.push({ id: h.id, hit: h, x: 0, y: 0, r: s, cover: h.frame || h.video?.thumbnail || undefined, video: h.clip || undefined, group: 'Detected',
      date: h.video?.posted_at || h.found_at, text: `${whatOf(h)} · ${titleOf(h)}`, tags: hitTags(h) });
  }
  // Groups on a spiral, biggest first; tiles start around their group's centre.
  const byGroup = new Map<string, Tile[]>();
  tiles.forEach((t) => byGroup.set(t.group, [...(byGroup.get(t.group) || []), t]));
  const names = [...byGroup.keys()].sort((a, b) => byGroup.get(b)!.length - byGroup.get(a)!.length);
  const centres = new Map<string, { x: number; y: number }>();
  // Each group's rough radius from its tile count; groups sit just outside the first one.
  const rad = (n: string) => 1.3 * Math.sqrt(byGroup.get(n)!.reduce((s, t) => s + t.r * t.r * 4, 0)) / 1.6;
  names.forEach((n, i) => {
    const a = i * 2.4, d = i === 0 ? 0 : rad(names[0]) + rad(n) + 0.8 * Math.sqrt(i);
    centres.set(n, { x: Math.cos(a) * d * 1.3, y: Math.sin(a) * d });
  });
  tiles.forEach((t, i) => { const c = centres.get(t.group)!; const a = i * 2.39996; const d = Math.sqrt(i % 40) * 1.2; t.x = c.x + Math.cos(a) * d; t.y = c.y + Math.sin(a) * d; });
  // A small force layout: similar tiles attract, every pair repels when overlapping, groups pull home.
  const n = tiles.length;
  const sim: number[][] = n <= 600 ? tiles.map((a) => tiles.map((b) => (a === b ? 0 : similarity(a.tags, b.tags)))) : [];
  for (let step = 0; step < 120; step++) {
    const k = 0.05 * (1 - step / 140);
    for (let i = 0; i < n; i++) {
      const a = tiles[i];
      let fx = 0, fy = 0;
      const c = centres.get(a.group)!;
      fx += (c.x - a.x) * 0.02; fy += (c.y - a.y) * 0.02;
      for (let j = 0; j < n; j++) {
        if (i === j) continue;
        const b = tiles[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.hypot(dx, dy) || 0.01;
        const min = (a.r + b.r) * 1.08;
        if (d < min) { fx -= (dx / d) * (min - d) * 0.5; fy -= (dy / d) * (min - d) * 0.5; }
        else if (sim.length && sim[i][j] > 0) { fx += (dx / d) * sim[i][j] * k * 4; fy += (dy / d) * sim[i][j] * k * 4; }
      }
      a.x += fx; a.y += fy;
    }
  }
  const groups: Group[] = names.map((name) => {
    const ts = byGroup.get(name)!;
    const x = ts.reduce((s, t) => s + t.x, 0) / ts.length, y = ts.reduce((s, t) => s + t.y, 0) / ts.length;
    const r = Math.max(...ts.map((t) => Math.hypot(t.x - x, t.y - y) + t.r));
    return { name, x, y, r };
  });
  let [x0, x1, y0, y1] = [Infinity, -Infinity, Infinity, -Infinity];
  tiles.forEach((t) => { x0 = Math.min(x0, t.x - t.r); x1 = Math.max(x1, t.x + t.r); y0 = Math.min(y0, t.y - t.r); y1 = Math.max(y1, t.y + t.r); });
  const ox = (x0 + x1) / 2, oy = (y0 + y1) / 2;
  tiles.forEach((t) => { t.x -= ox; t.y -= oy; });
  groups.forEach((g) => { g.x -= ox; g.y -= oy; });
  return { tiles, groups, width: isFinite(x1 - x0) ? x1 - x0 : 1, height: isFinite(y1 - y0) ? y1 - y0 : 1 };
}

/** The opened video's half, most related first, then the other half's most related. */
export function relatedOrder(anchor: Item, half: Item[], other: Item[]): Item[] {
  const a = tagSet(anchor);
  const score = (it: Item) => similarity(a, tagSet(it));
  const mine = half.filter((x) => x.id !== anchor.id).sort((x, y) => score(y) - score(x) || y.taken_at.localeCompare(x.taken_at));
  const theirs = other.filter((x) => x.id !== anchor.id && !half.some((h) => h.id === x.id)).map((x) => [x, score(x)] as const)
    .filter(([, s]) => s > 0).sort((x, y) => y[1] - x[1]).slice(0, 30).map(([x]) => x);
  return [anchor, ...mine, ...theirs];
}

// ---- the tag graph ----
export interface GNode { tag: string; kind: string; count: number; x: number; y: number; r: number; rank: number }
export interface GEdge { a: number; b: number; w: number }

export function buildTagGraph(items: Item[], tags: Tag[], max = 160): { nodes: GNode[]; edges: GEdge[] } {
  const seen = new Set<string>();
  const top = tags.filter((t) => t.tag.length <= 32 && !seen.has(t.tag) && seen.add(t.tag)).slice(0, max);
  const index = new Map(top.map((t, i) => [t.tag, i]));
  const co = new Map<string, number>();
  for (const it of items) {
    const ids = [...new Set([...itemTags(it).values()].map((t) => index.get(t.tag)).filter((x): x is number => x !== undefined))].sort((a, b) => a - b);
    for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) { const k = `${ids[i]}:${ids[j]}`; co.set(k, (co.get(k) || 0) + 1); }
  }
  const edges: GEdge[] = [...co.entries()].map(([k, w]) => { const [a, b] = k.split(':').map(Number); return { a, b, w }; });
  const maxC = Math.max(1, ...top.map((t) => t.count));
  const nodes: GNode[] = top.map((t, i) => {
    const a = i * 2.39996, d = Math.sqrt(i) * 3;
    return { tag: t.tag, kind: t.kind, count: t.count, x: Math.cos(a) * d, y: Math.sin(a) * d, r: 0.8 + 3 * Math.sqrt(t.count / maxC), rank: i };
  });
  for (let step = 0; step < 150; step++) {
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const p = nodes[i], q = nodes[j];
      const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 0.01;
      const min = (p.r + q.r) * 1.6;
      if (d < min) { const f = (min - d) * 0.25; p.x -= (dx / d) * f; p.y -= (dy / d) * f; q.x += (dx / d) * f; q.y += (dy / d) * f; }
    }
    for (const e of edges) {
      const p = nodes[e.a], q = nodes[e.b];
      const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 0.01;
      const f = Math.min(0.2, 0.02 * e.w) * (d - (p.r + q.r) * 2) / d;
      p.x += dx * f; p.y += dy * f; q.x -= dx * f; q.y -= dy * f;
    }
    nodes.forEach((p) => { p.x *= 0.995; p.y *= 0.995; });
  }
  return { nodes, edges };
}
