// Home's main screen: every video (items with video and the approved monitor hits), grouped into
// sections by subject (the AI's facet categories). Newest first, by the hour: each level down counts
// as an hour older (LEVEL_HOURS), so the level only decides between videos that arrived about the
// same time; a category with the newest video rises to the top.
// L1: posts and dedicated highlights -> Featured. L2: shared highlights -> one section per theme (the
// AI facet that splits them best), the rest under More highlights.
// L3: reposts. L4: stories in no highlight. Hits -> Found by AI, at their own levels.
// Levels come from /v1/layout; without it they are derived the way the backend assigns them.
import type { Facet, LayoutTile } from './homeData';
import { importance, isVideo } from './layout';
import type { Hit } from './monitor';
import { heardOf, LANG, titleOf } from './monitor';
import { highlightSection } from './sections';
import type { Highlight, Item } from './types';
import { cover } from './util';
import { t } from './i18n';

export interface VTile {
  id: string;
  item?: Item;
  hit?: Hit;
  level: number;          // 1 (most important) .. 4
  score: number;          // importance 0..1; orders tiles inside a section
  cover?: string;
  video?: string;
  date?: string;
  added?: string;         // when it arrived: the post's time, or when a found clip was published
  text: string;
  audio?: Audio;          // what was heard in it
  rank?: number;          // freshness × level (rankOf): the order on Home
}
/**
 * What sounds in a video. `heard`: the phrase spoken - its highlight's name (highlights are named
 * after what is said in them), or for a found clip the words around
 * the match. Else the post's own description (see describe), or none.
 */
export interface Audio { kind: 'heard' | 'speech' | 'music' | 'none'; text: string }
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
/** The local calendar day of a time ('' when unknown), so "today" means the viewer's today. */
export function dayOf(s?: string | null): string {
  const t = s ? Date.parse(s) : NaN;
  if (isNaN(t)) return '';
  const d = new Date(t);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
// days. One: the weight halves every 24 hours, so the newest lead and a level up is worth a day.
export const RECENCY_HALF_LIFE = 1;
/** How much older one level down counts as: L2 an hour newer than an L1 comes first. */
export const LEVEL_HOURS = 1;
/** freshness × level: the level's weight, halved every `halfLife` days since it arrived (continuously). */
export function rankOf(t: VTile, halfLife = RECENCY_HALF_LIFE, now = Date.now()): number {
  // newest first, by the hour; each level down counts as LEVEL_HOURS older, so the level decides
  // only between videos that arrived about the same time
  const at = t.added ? Date.parse(t.added) : NaN;
  const age = isNaN(at) ? 3650 : Math.max(0, (now - at) / 864e5) + (t.level - 1) * LEVEL_HOURS / 24;
  return 0.5 ** (age / (halfLife > 0 ? halfLife : RECENCY_HALF_LIFE));
}
const plural = (n: number) => `${n} ${t(n === 1 ? 'video' : 'videos')}`;
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

/**
 * The post's own description as a label: its caption (first line, without hashtags or mentions), else
 * the first sentence of its description. The backend's heard job finds when it sounds in the video.
 */
/** The post's own name: its caption's first line, without hashtags and mentions (never a generated text). */
export function describe(it: Item): string {
  return (it.caption || '').split(/\n/).map((l) => l.replace(/[#@][\p{L}\p{N}_.]+/gu, '').replace(/\s+/g, ' ').trim()).find(Boolean) || '';
}

/**
 * One label per card, and only one the owner gave: his own label, the highlight's name (written out
 * when he shortened it), or the post's own caption. Nothing generated, and not a phrase the monitor
 * happened to hear in it (a lecture saying "три" is not a "3" video). Else no label. A recommendation
 * card (a monitor hit, on Home only once the owner adds it with "+") is labelled with its matched phrase.
 */
export function audioOf(it: Item, _labels?: Map<string, string>): Audio {
  if (it.heard?.by === 'owner' && it.heard.text) return { kind: 'heard', text: it.heard.text };
  const title = (it.highlights || []).map((h) => (h.title_translated || h.title_full || h.title).trim()).find(Boolean);
  if (title) return { kind: 'heard', text: title };
  const said = describe(it);
  return said ? { kind: 'heard', text: said } : { kind: 'none', text: '' };
}

export function buildSections(items: Item[], highlights: Highlight[], hits: Hit[], layout?: LayoutTile[], facets?: Facet[] | null, halfLife = RECENCY_HALF_LIFE): VSection[] {
  const rankOf_ = (t: VTile) => rankOf(t, halfLife);
  const given = new Map((layout || []).map((t) => [t.id, t]));
  const byScore = (a: VTile, b: VTile) => rankOf_(b) - rankOf_(a) || b.score - a.score || (b.added || '').localeCompare(a.added || '');

  // A highlight's fuller label (from what its videos say) where the backend has one, else its name.
  const labels = new Map(highlights.map((h) => [h.id, h.heard_label || h.title]));
  const tiles: VTile[] = items.filter(isVideo).map((it) => {
    const g = given.get(it.id);
    const level = g?.level && g.level >= 1 && g.level <= 4 ? g.level : itemLevel(it, highlights);
    return {
      id: it.id, item: it, level, score: it.importance ?? g?.importance ?? importance(it),
      cover: cover(it), video: videoOf(it), date: it.taken_at, added: it.taken_at, text: it.summary || it.description || it.caption || '',
      audio: audioOf(it, labels),
    };
  });
  for (const h of hits.filter((h) => h.clip || h.frame || h.video?.thumbnail)) {
    tiles.push({
      id: h.id, hit: h, level: given.get(h.id)?.level || hitLevel(h), score: h.confidence ?? 0.5,
      cover: h.frame || h.video?.thumbnail || undefined, video: h.clip || undefined,
      date: h.video?.posted_at || h.found_at, added: h.published_at || h.found_at || h.video?.posted_at || undefined, text: titleOf(h),
      audio: heardOf(h) ? { kind: 'heard', text: heardOf(h) } : undefined,
    });
  }

  for (const t of tiles) t.rank = rankOf_(t);

  // Sections by subject: each video in the biggest category of the facet that splits them best; the
  // ones left go through the next facet.
  const groups: { id: string; title: string; about?: string; tiles: VTile[] }[] = [];
  let rest = tiles;
  for (let round = 0; round < 2 && rest.length >= MIN_THEME; round++) {
    const facet = themeFacet(facets || [], new Set(rest.map((t) => t.id)));
    if (!facet) break;
    const cats = facet.categories.map((c) => ({ c, ids: new Set(c.item_ids), tiles: [] as VTile[] }));
    const left: VTile[] = [];
    for (const t of rest) {
      const home = cats.filter((x) => x.ids.has(t.id)).sort((a, b) => b.c.count - a.c.count)[0];
      (home ? home.tiles : left).push(t);
    }
    for (const x of cats) {
      // every category with a video is a section, however small (every video is categorized)
      if (x.tiles.length) groups.push({ id: `${facet.id}:${x.c.id}`, title: x.c.name, about: x.c.description, tiles: x.tiles });
    }
    rest = left;
    facets = (facets || []).filter((f) => f !== facet);
  }
  // The rest, until the backend has placed them (every video ends up in a category).
  if (rest.length) groups.push({ id: 'more', title: t('Categorization in progress'), tiles: rest });

  // The section whose best video ranks highest (freshness × level) first.
  const top = (l: VTile[]) => Math.max(...l.map(rankOf_));
  const best = (l: VTile[]) => Math.min(...l.map((t) => t.level));
  return groups
    .sort((a, b) => top(b.tiles) - top(a.tiles) || (a.id === 'more' ? 1 : 0) - (b.id === 'more' ? 1 : 0))
    .map((g) => {
      const dates = g.tiles.map((t) => t.date || '').filter(Boolean).sort();
      const level = best(g.tiles);
      return { id: g.id, title: g.title, subtitle: [g.about, plural(g.tiles.length), span(dates[0], dates[dates.length - 1])].filter(Boolean).join(' · '),
        tiles: g.tiles.sort(byScore), level, compact: level >= 3 };
    });
}

export type Size = 'xl' | 'wide' | 'm';
/**
 * A tile's footprint in a grid `cols` wide: the most important tiles get the space. The first
 * section's L1 videos lead (on a phone the first fills the width); every other section opens with
 * one large tile and keeps the rest readable.
 */
export function sizeOf(t: VTile, rank: number, n: number, cols: number, lead = false): Size {
  if (cols < 2 || t.level >= 3) return 'm';
  const heroes = Math.max(1, Math.floor(cols / 4));
  if (lead && t.level === 1) return rank < heroes && n >= 3 ? 'xl' : rank < heroes + Math.floor(cols / 2) && n > cols ? 'wide' : 'm';
  return rank === 0 && n >= 4 && cols >= 4 ? 'xl' : rank === 0 && n >= 2 ? 'wide' : 'm';
}
