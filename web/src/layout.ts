// The mosaics' layout, computed in the browser until the API serves GET /v1/layout:
// tiles grouped by highlight, placed so videos that share tags sit close, sized by recency × importance.
import type { Hit } from './monitor';
import { titleOf, whatOf } from './monitor';
import { itemTags } from './tags';
import type { Highlight, Item, Tag } from './types';
import { cover } from './util';

export interface Tile {
  id: string;
  attachedTo?: string;               // an image shown beside the video it belongs with
  hit?: Hit;
  item?: Item;
  x: number; y: number; r: number;   // centre and half-size, in layout units
  cover?: string;
  video?: string;
  group: string;                      // highlight title (or "Detected")
  date?: string;
  text: string;                       // short description
  tags: Set<string>;
  more?: Tile[];                      // a "more" cluster: tiles too small to show on their own
  kids?: Tile[];                      // attached images, drawn as insets inside the video's tile
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
  const given = (it as { importance?: number }).importance;
  if (typeof given === 'number') return Math.max(0, Math.min(1, given));
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
    const g = (it.highlights || []).find((h) => hlIds.has(h.id))?.title || '';
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
  return finish(tiles, names, byGroup);
}

function finish(tiles: Tile[], names: string[], byGroup: Map<string, Tile[]>): Mosaic {
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
export interface GNode { tag: string; kind: string; count: number; x: number; y: number; r: number; rank: number; facet?: string; category?: string; facetName?: string }
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
  return layoutGraph(top, edges);
}

function layoutGraph(top: Tag[], edges: GEdge[]): { nodes: GNode[]; edges: GEdge[] } {
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
  // Final relaxation: no two circles overlap (with padding). Positions scale with zoom, so this holds at every zoom.
  for (let pass = 0; pass < 400; pass++) {
    let moved = false;
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const p = nodes[i], q = nodes[j];
      let dx = q.x - p.x, dy = q.y - p.y;
      let d = Math.hypot(dx, dy);
      if (d < 1e-6) { dx = 0.01 * (j - i); dy = 0.01; d = Math.hypot(dx, dy); }
      const min = (p.r + q.r) * 1.15;
      if (d < min) { const f = (min - d) / 2 / d; p.x -= dx * f; p.y -= dy * f; q.x += dx * f; q.y += dy * f; moved = true; }
    }
    if (!moved) break;
  }
  return { nodes, edges };
}

const FEEDISH = new Set(['reels', 'posts', 'stories', 'feed', '']);

/** The API's layout for one half (x, y in 0..1, size 0.15..1) as a mosaic. */
export function mosaicFromLayout(lt: { id: string; kind: string; x: number; y: number; size: number; level?: number; label?: string; taken_at?: string }[], items: Map<string, Item>, hits: Map<string, Hit>, exponent = 2): Mosaic {
  const span = Math.max(6, Math.sqrt(lt.length) * 4.5);
  const tiles: Tile[] = [];
  for (const t of lt) {
    const it = t.kind === 'item' ? items.get(t.id) : undefined;
    const h = t.kind === 'hit' ? hits.get(t.id) : undefined;
    if (!it && !h) continue;
    const label = (t.label || '').trim();
    const group = h ? (label || 'Detected') : FEEDISH.has(label.toLowerCase()) ? '' : label;
    const m = it ? it.media[0] || it.repost_of?.media?.[0] : undefined;
    tiles.push({
      id: t.id, item: it, hit: h, x: (t.x - 0.5) * span, y: (t.y - 0.5) * span, r: 1.6 * Math.pow(Math.max(0.005, Math.min(1, t.level ? [1, 0.5, 0.25, 0.125][t.level - 1] ?? t.size : t.size)), exponent / 2), // area ∝ size ^ display_exponent; size from the level (1-4) when given
      cover: it ? cover(it) : h!.frame || h!.video?.thumbnail || undefined, video: it ? (m?.type === 'video' ? m.url : undefined) : h!.clip || undefined,
      group, date: it?.taken_at || t.taken_at || h?.video?.posted_at || undefined, text: it ? it.summary || it.caption || '' : `${whatOf(h!)} · ${titleOf(h!)}`,
      tags: it ? tagSet(it) : hitTags(h!),
    });
  }
  // Nudge overlapping tiles apart; the API's positions stay the backbone.
  for (let step = 0; step < 60; step++) {
    for (let i = 0; i < tiles.length; i++) for (let j = i + 1; j < tiles.length; j++) {
      const a = tiles[i], b = tiles[j];
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 0.01, min = (a.r + b.r) * 1.05;
      if (d < min) { const f = (min - d) / 2 / d; a.x -= dx * f; a.y -= dy * f; b.x += dx * f; b.y += dy * f; }
    }
  }
  const byGroup = new Map<string, Tile[]>();
  tiles.forEach((t) => byGroup.set(t.group, [...(byGroup.get(t.group) || []), t]));
  const names = [...byGroup.keys()].sort((a, b) => byGroup.get(b)!.length - byGroup.get(a)!.length);
  return finish(tiles, names, byGroup);
}

/** The API's tag graph (levels 0..3) laid out in the browser. */
export function graphFromApi(nodesIn: { tag: string; kinds?: string[]; count: number; level: number; facet?: string; facet_name?: string; category?: string }[], edgesIn: { a: string; b: string; count: number }[]): { nodes: GNode[]; edges: GEdge[] } {
  const sorted = nodesIn.slice().sort((a, b) => a.level - b.level || b.count - a.count);
  const tags: Tag[] = sorted.map((n) => ({ tag: n.tag, kind: n.kinds?.[0] || 'keyword', count: n.count }));
  const index = new Map(tags.map((t, i) => [t.tag, i]));
  const edges: GEdge[] = edgesIn.map((e) => ({ a: index.get(e.a)!, b: index.get(e.b)!, w: e.count })).filter((e) => e.a !== undefined && e.b !== undefined);
  const g = layoutGraph(tags, edges);
  // Level 0 are the facets' categories: they open that category, not a tag.
  g.nodes.forEach((n, i) => { const src = sorted[i]; if (src.facet) { n.facet = src.facet; n.category = src.category; n.facetName = src.facet_name; n.kind = 'facet'; } });
  return g;
}

export const isVideo = (it: Item) => (it.media[0] || it.repost_of?.media?.[0])?.type === 'video' || (it.media.length > 1 && it.media.some((m) => m.type === 'video'));

/** image id -> the video it is attached to: the API's `attached_to`, else its most similar video. */
export function attachMap(items: Item[], given?: { id: string; attached_to?: string | null }[]): Map<string, string> {
  const out = new Map<string, string>();
  given?.forEach((t) => { if (t.attached_to) out.set(t.id, t.attached_to); });
  const videos = items.filter(isVideo);
  for (const it of items) {
    if (isVideo(it) || out.has(it.id) || !videos.length) continue;
    const a = tagSet(it);
    let best = videos[0], bs = -1;
    for (const v of videos) { const sc = similarity(a, tagSet(v)); if (sc > bs || (sc === bs && v.taken_at > best.taken_at)) { best = v; bs = sc; } }
    out.set(it.id, best.id);
  }
  return out;
}

/** In the wheel an image follows the video it is attached to; when that video is not in the list, it keeps its place. */
export function withAttachments(list: Item[], attach: Map<string, string>, keep?: string): Item[] {
  const byParent = new Map<string, Item[]>();
  const ids = new Set(list.map((x) => x.id));
  list.forEach((x) => { const p = attach.get(x.id); if (p && ids.has(p)) byParent.set(p, [...(byParent.get(p) || []), x]); });
  const out: Item[] = [];
  for (const x of list) {
    const p = attach.get(x.id);
    if (p && ids.has(p) && x.id !== keep) continue;
    out.push(x);
    (byParent.get(x.id) || []).forEach((img) => { if (img.id !== keep) out.push(img); });
  }
  return out;
}

/** Places attached image tiles as small neighbours beside their video's tile; orphans are dropped. */
export function placeAttached(m: Mosaic, attach: Map<string, string>): Mosaic {
  const byId = new Map(m.tiles.map((t) => [t.id, t]));
  const count = new Map<string, number>();
  const tiles = m.tiles.filter((t) => {
    const p = attach.get(t.id);
    if (!p) return true;
    const parent = byId.get(p);
    if (!parent || attach.has(parent.id)) return false;
    const n = count.get(p) || 0;
    count.set(p, n + 1);
    t.attachedTo = p;
    t.r = parent.r * 0.38;
    t.x = parent.x + parent.r + t.r + 0.08;
    t.y = parent.y - parent.r + t.r + n * (2 * t.r + 0.08);
    t.group = parent.group;
    return true;
  });
  return { ...m, tiles };
}

// ---- packing: a gapless, ordered treemap over the whole half ----
export interface Packed { tile: Tile; x: number; y: number; w: number; h: number }

function hilbert(n: number, x: number, y: number): number {
  let d = 0;
  for (let s = n >> 1; s > 0; s >>= 1) {
    const rx = (x & s) > 0 ? 1 : 0, ry = (y & s) > 0 ? 1 : 0;
    d += s * s * ((3 * rx) ^ ry);
    if (ry === 0) { if (rx === 1) { x = s - 1 - x; y = s - 1 - y; } [x, y] = [y, x]; }
  }
  return d;
}

/** Squarified treemap that keeps the given order, so neighbours in the order stay neighbours. */
function squarifyOrdered<T>(data: { v: number; d: T }[], x0: number, y0: number, W: number, H: number): { d: T; x: number; y: number; w: number; h: number }[] {
  const out: { d: T; x: number; y: number; w: number; h: number }[] = [];
  const total = data.reduce((s, e) => s + e.v, 0) || 1;
  let rest = data.map((e) => ({ ...e, a: (e.v / total) * W * H }));
  let r = { x: x0, y: y0, w: W, h: H };
  while (rest.length) {
    const short = Math.min(r.w, r.h) || 1;
    let row: typeof rest = [], worst = Infinity;
    for (const e of rest) {
      const next = [...row, e];
      const sum = next.reduce((s, q) => s + q.a, 0);
      let mx = 0, mn = Infinity;
      for (const q of next) { mx = Math.max(mx, q.a); mn = Math.min(mn, q.a); }
      const w = Math.max((short * short * mx) / (sum * sum), (sum * sum) / (short * short * mn));
      if (w > worst) break;
      worst = w; row = next;
    }
    const sum = row.reduce((s, q) => s + q.a, 0);
    const last = row.length === rest.length;
    const thick = last ? (r.w >= r.h ? r.w : r.h) : sum / short;
    let off = 0;
    for (const e of row) {
      const len = (e.a / sum) * short;
      out.push(r.w >= r.h ? { d: e.d, x: r.x, y: r.y + off, w: thick, h: len } : { d: e.d, x: r.x + off, y: r.y, w: len, h: thick });
      off += len;
    }
    r = r.w >= r.h ? { x: r.x + thick, y: r.y, w: r.w - thick, h: r.h } : { x: r.x, y: r.y + thick, w: r.w, h: r.h - thick };
    rest = rest.slice(row.length);
  }
  return out;
}

export const MAX_ASPECT = 2.5;
/** 1 when the last pack kept areas exactly proportional; lower when it had to even them out to avoid slivers. */
export let lastAlpha = 1;
export const MIN_SIDE = 48;

/**
 * Packs a half into W×H with no free space and no slivers. Videos run along a Hilbert curve through
 * their similarity positions; each run of six is sorted by area and laid out as a squarified
 * treemap, area ∝ weight (size ^ display_exponent). Any tile that would be thinner than 1:2.5 or
 * smaller than 48 px a side joins a "more" tile, which shows its videos as you zoom in. Attached
 * images are insets inside their video's tile, not cells of their own.
 */
export function pack(m: Mosaic, W: number, H: number): Packed[] {
  const kids = new Map<string, Tile[]>();
  m.tiles.forEach((t) => { if (t.attachedTo) kids.set(t.attachedTo, [...(kids.get(t.attachedTo) || []), t]); });
  const parents = m.tiles.filter((t) => !t.attachedTo);
  if (!parents.length || W <= 0 || H <= 0) return [];
  parents.forEach((t) => { t.kids = kids.get(t.id); });
  let [x0, x1, y0, y1] = [Infinity, -Infinity, Infinity, -Infinity];
  parents.forEach((t) => { x0 = Math.min(x0, t.x); x1 = Math.max(x1, t.x); y0 = Math.min(y0, t.y); y1 = Math.max(y1, t.y); });
  const N = 256, sx = (x1 - x0) || 1, sy = (y1 - y0) || 1;
  const order = parents.map((t) => ({ t, h: hilbert(N, Math.min(N - 1, Math.floor(((t.x - x0) / sx) * (N - 1))), Math.min(N - 1, Math.floor(((t.y - y0) / sy) * (N - 1)))) }))
    .sort((a, b) => a.h - b.h).map((e) => e.t);
  const w = (t: Tile) => t.r * t.r;
  const minSide = Math.min(MIN_SIDE, Math.min(W, H) / 1.2);
  const total = order.reduce((s, t) => s + w(t), 0);
  // Tiles whose share of the area could never make a 48 px square start in the "more" tile.
  const tooSmall = new Set(order.filter((t) => (w(t) / total) * W * H < minSide * minSide * 1.15));
  const bad = (c: { w: number; h: number }) => Math.min(c.w, c.h) < minSide - 0.5 || Math.max(c.w, c.h) / Math.min(c.w, c.h) > MAX_ASPECT + 0.01;
  const layoutWith = (fold: Set<Tile>, alpha: number) => {
    const shown = order.filter((t) => !fold.has(t));
    const hidden = order.filter((t) => fold.has(t));
    const list: Tile[] = [...shown];
    if (hidden.length) {
      // The "+N" tile never takes more than a fifth of the screen; zooming in opens it up.
      const shownW = shown.reduce((s, t) => s + w(t), 0) || total;
      const cw = Math.max(Math.min(hidden.reduce((s, t) => s + w(t), 0), 0.25 * shownW), (minSide * minSide * 1.6 / (W * H)) * (shownW + 0.0001));
      const first = hidden[0];
      list.push({ ...first, id: `more:${first.id}`, r: Math.sqrt(cw), more: hidden, kids: undefined, group: '', text: `${hidden.length} more`, hit: undefined, item: undefined, video: undefined });
    }
    // Runs of six along the curve, largest first in each run.
    const runs: Tile[] = [];
    for (let i = 0; i < list.length; i += 6) runs.push(...list.slice(i, i + 6).sort((a, b) => w(b) - w(a)));
    return squarifyOrdered(runs.map((t) => ({ v: Math.pow(w(t), alpha), d: t })), 0, 0, W, H);
  };
  // First keep areas true to size and fold the smallest offenders into "more"; if too few tiles are
  // left for this box, even the areas out step by step until every tile is a reasonable shape.
  let cells = layoutWith(tooSmall, 1);
  for (let attempt = 0; attempt < 40; attempt++) {
    const wrong = cells.filter((c) => bad(c));
    if (!wrong.length) break;
    const victims = wrong.filter((c) => !c.d.more).sort((a, b) => w(a.d) - w(b.d));
    const left = order.filter((t) => !tooSmall.has(t)).length;
    if (!victims.length || left <= 3) break;
    tooSmall.add(victims[0].d);
    cells = layoutWith(tooSmall, 1);
  }
  let used = 1;
  for (const alpha of [0.7, 0.45, 0.25, 0]) {
    if (!cells.some((c) => bad(c))) break;
    cells = layoutWith(tooSmall, alpha);
    used = alpha;
  }
  lastAlpha = used;
  return cells.map((c) => ({ tile: c.d, x: c.x, y: c.y, w: c.w, h: c.h }));
}
