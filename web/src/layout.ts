// Home's computations in the browser: similarity and importance, related order, the tag graph,
// and which video each image is attached to.
import { itemTags } from './tags';
import type { Item, Tag } from './types';

const tagSet = (it: Item) => new Set([...itemTags(it).values()].map((t) => t.tag));

export function similarity(a: Set<string>, b: Set<string>): number {
  if (!a.size || !b.size) return 0;
  let n = 0;
  for (const t of a) if (b.has(t)) n++;
  return n / (a.size + b.size - n);
}

export function importance(it: Item): number {
  const given = (it as { importance?: number }).importance;
  if (typeof given === 'number') return Math.max(0, Math.min(1, given));
  const c = it.counts || {};
  const engagement = Math.log10(1 + (c.likes || 0) + (c.views || 0) / 10 + (c.plays || 0) / 10) / 5;
  const people = Math.min(1, (it.analysis?.people?.length || 0) / 3);
  const events = Math.min(1, (it.analysis?.events?.length || 0) / 4);
  return Math.min(1, 0.35 + 0.35 * Math.min(1, engagement) + 0.15 * people + 0.15 * events);
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

