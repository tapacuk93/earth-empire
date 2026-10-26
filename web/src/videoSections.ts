// Home's main screen: every video (items with video and the approved monitor hits), grouped into
// sections by the four levels of CONTRACT.md "Home layout", most important first within each.
// L1: posts and dedicated highlights -> Featured. L2: shared highlights -> one section per theme (the
// AI facet that splits them best), the rest under More highlights.
// L3: reposts. L4: stories in no highlight. Hits -> Found by AI, at their own levels.
// Levels come from /v1/layout; without it they are derived the way the backend assigns them.
import type { Facet, LayoutTile } from './homeData';
import { importance, isVideo } from './layout';
import type { Hit } from './monitor';
import { titleOf, whatOf } from './monitor';
import { highlightSection } from './sections';
import type { Highlight, Item } from './types';
import { cover } from './util';

export interface VTile {
  id: string;
  item?: Item;
  hit?: Hit;
  level: number;          // 1 (most important) .. 4
  score: number;          // importance 0..1; orders tiles inside a section
  cover?: string;
  video?: string;
  date?: string;
  text: string;
  label?: string;         // the highlight it belongs to, shown on large tiles
}
export interface VSection { id: string; title: string; subtitle: string; tiles: VTile[]; level: number; compact: boolean }

const videoOf = (it: Item) => [...it.media, ...(it.repost_of?.media || [])].find((m) => m.type === 'video')?.url;
const hitLevel = (h: Hit) => { const l = (h as { level?: number | null }).level; return typeof l === 'number' && l >= 1 && l <= 4 ? l : 2; };

/** An item's level as the backend's placement assigns it (CONTRACT.md: dedicated/post 1, shared 2, repost 3, story 4). */
export function itemLevel(it: Item, highlights: Highlight[]): number {
  if (it.repost_of) return 3;
  const mine = highlights.filter((h) => it.highlights?.some((x) => x.id === h.id));
  if (!mine.length) return it.kind === 'story' ? 4 : 1;
  return mine.some((h) => highlightSection(h, highlights) === 'dedicated') ? 1 : 2;
}

function span(a?: string, b?: string): string {
  const fmt = (s: string) => new Date(s).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
  if (!a || !b || isNaN(Date.parse(a)) || isNaN(Date.parse(b))) return '';
  const [x, y] = [fmt(a), fmt(b)];
  return x === y ? x : `${x} – ${y}`;
}
const plural = (n: number) => `${n} video${n === 1 ? '' : 's'}`;
const MIN_THEME = 3;

/** The facet that groups these videos best: the most of them in categories of at least three, none holding over 60%. */
export function themeFacet(facets: Facet[], ids: Set<string>): Facet | undefined {
  let best: Facet | undefined, bestN = 0;
  for (const f of facets) {
    const sizes = f.categories.map((c) => c.item_ids.filter((id) => ids.has(id)).length);
    const total = sizes.reduce((s, n) => s + n, 0);
    const n = sizes.filter((x) => x >= MIN_THEME).reduce((s, x) => s + x, 0);
    if (total && Math.max(...sizes) / total <= 0.6 && sizes.filter((x) => x >= MIN_THEME).length >= 2 && n > bestN) { best = f; bestN = n; }
  }
  return best;
}

export function buildSections(items: Item[], highlights: Highlight[], hits: Hit[], layout?: LayoutTile[], facets?: Facet[] | null): VSection[] {
  const given = new Map((layout || []).map((t) => [t.id, t]));
  const byScore = (a: VTile, b: VTile) => a.level - b.level || b.score - a.score || (b.date || '').localeCompare(a.date || '');
  const shared = new Map(highlights.filter((h) => highlightSection(h, highlights) === 'common').map((h) => [h.id, h.title]));

  const tiles: VTile[] = items.filter(isVideo).map((it) => {
    const g = given.get(it.id);
    const level = g?.level && g.level >= 1 && g.level <= 4 ? g.level : itemLevel(it, highlights);
    return {
      id: it.id, item: it, level, score: it.importance ?? g?.importance ?? importance(it),
      cover: cover(it), video: videoOf(it), date: it.taken_at, text: it.summary || it.description || it.caption || '',
      label: it.highlights?.find((h) => shared.has(h.id))?.title || it.highlights?.[0]?.title,
    };
  });
  const found: VTile[] = hits.filter((h) => h.clip || h.frame || h.video?.thumbnail).map((h) => ({
    id: h.id, hit: h, level: given.get(h.id)?.level || hitLevel(h), score: h.confidence ?? 0.5,
    cover: h.frame || h.video?.thumbnail || undefined, video: h.clip || undefined,
    date: h.video?.posted_at || h.found_at, text: `${whatOf(h)} · ${titleOf(h)}`, label: h.source?.name || h.platform,
  }));

  const out: VSection[] = [];
  const add = (id: string, title: string, subtitle: string, list: VTile[], level: number) => {
    if (list.length) out.push({ id, title, subtitle, tiles: list.sort(byScore), level, compact: level >= 3 });
  };
  add('featured', 'Featured', 'Posts and dedicated highlights, the most important first', tiles.filter((t) => t.level === 1), 1);
  const ai = () => add('ai', 'Found by AI', 'Public videos elsewhere that mention Earth Empire, rated by Claude and approved', found, Math.min(...found.map((t) => t.level)));
  if (found.some((t) => t.level <= 2)) ai();
  // Level 2: one section per theme, the largest (and most important) first; each video in its biggest theme.
  const l2 = tiles.filter((t) => t.level === 2);
  const facet = themeFacet(facets || [], new Set(l2.map((t) => t.id)));
  const cats = (facet?.categories || []).map((c) => ({ c, ids: new Set(c.item_ids) }));
  const groups = new Map<string, VTile[]>(), rest: VTile[] = [];
  for (const t of l2) {
    const home = cats.filter((x) => x.ids.has(t.id)).sort((a, b) => b.c.count - a.c.count)[0];
    if (home) groups.set(home.c.id, [...(groups.get(home.c.id) || []), t]); else rest.push(t);
  }
  const weight = (l: VTile[]) => l.length * (0.5 + l.reduce((s, t) => s + t.score, 0) / l.length);
  const about = (l: VTile[], what?: string) => {
    const dates = l.map((t) => t.date || '').filter(Boolean).sort();
    return [what, plural(l.length), span(dates[0], dates[dates.length - 1])].filter(Boolean).join(' · ');
  };
  [...groups.entries()].filter(([, l]) => l.length >= MIN_THEME || !rest.push(...l)).sort((a, b) => weight(b[1]) - weight(a[1])).forEach(([id, list]) => {
    const c = cats.find((x) => x.c.id === id)!.c;
    add(`theme:${id}`, c.name, about(list, c.description), list, 2);
  });
  add('highlights', groups.size ? 'More from the highlights' : 'Highlights', about(rest, 'From the shared highlights'), rest, 2);
  if (!found.some((t) => t.level <= 2)) ai();
  add('reposts', 'Reposts', 'Videos shared from other accounts', tiles.filter((t) => t.level === 3), 3);
  add('stories', 'Stories', 'Moments from stories kept outside any highlight', tiles.filter((t) => t.level === 4), 4);
  return out;
}

export type Size = 'xl' | 'wide' | 'm';
/**
 * A tile's footprint in a grid `cols` wide: the most important tiles of the top levels get the
 * space, so on a phone (2 columns) the first Featured video fills the width and the rest stay readable.
 */
export function sizeOf(t: VTile, rank: number, n: number, cols: number): Size {
  if (cols < 2 || t.level >= 3) return 'm';
  const heroes = Math.max(1, Math.floor(cols / 4));
  if (t.level === 1) return rank < heroes && n >= 3 ? 'xl' : rank < heroes + Math.floor(cols / 2) && n > cols ? 'wide' : 'm';
  return rank === 0 && n >= 4 ? (cols >= 3 ? 'xl' : 'wide') : rank === 0 && n >= 2 ? 'wide' : 'm';
}
