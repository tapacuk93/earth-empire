// Home's main screen: every video (items with video and the approved monitor hits), grouped into
// sections by the four levels of CONTRACT.md "Home layout", most important first within each.
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
  audio?: Audio;          // what was heard in it
}
/**
 * What sounds in a video. `heard`: the phrase spoken - its highlight's name (highlights are named
 * after what is said in them), a phrase the monitor matched, or for a found clip the words around
 * the match. Else the language spoken, the music, or none.
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

const langName = (code?: string | null) => {
  if (!code) return '';
  if (code.length > 3) return code[0].toUpperCase() + code.slice(1); // already a name ("English")
  if (LANG[code]) return LANG[code];
  try { return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) || code; } catch { return code; }
};
/** The first clause of a free-text note ("Song by X (original reel's music); …" -> "Song by X"). */
const clause = (s: string) => s.split(/[;(]/)[0].trim().replace(/[.,]$/, '');

export function audioOf(it: Item): Audio {
  const titles = [...new Set((it.highlights || []).map((h) => h.title.trim()).filter(Boolean))];
  if (titles.length) return { kind: 'heard', text: titles.join(' · ') };
  const hits = it.detection?.hits || [];
  const names = [...new Set(hits.filter((h) => h.kind === 'name' && h.phrase).map((h) => h.phrase!))];
  if (names.length) return { kind: 'heard', text: names.join(' · ') };
  const langs = [...new Set(hits.filter((h) => h.kind === 'language').map((h) => `${langName(h.lang)} speech`))];
  if (langs.length) return { kind: 'speech', text: langs.join(' · ') };
  const speech = it.analysis?.speech;
  if (speech?.language && speech.transcript && !/^(und|unknown|none|n\/a|mul|zxx)$/i.test(speech.language.trim())) return { kind: 'speech', text: `${langName(speech.language.length <= 3 ? speech.language.toLowerCase() : speech.language)} speech` };
  const music = it.music?.title ? [it.music.title, it.music.artist].filter(Boolean).join(' · ') : it.analysis?.music ? clause(it.analysis.music) : '';
  return music ? { kind: 'music', text: music } : { kind: 'none', text: 'No speech detected' };
}

export function buildSections(items: Item[], highlights: Highlight[], hits: Hit[], layout?: LayoutTile[], facets?: Facet[] | null): VSection[] {
  const given = new Map((layout || []).map((t) => [t.id, t]));
  const byScore = (a: VTile, b: VTile) => a.level - b.level || b.score - a.score || (b.date || '').localeCompare(a.date || '');

  const tiles: VTile[] = items.filter(isVideo).map((it) => {
    const g = given.get(it.id);
    const level = g?.level && g.level >= 1 && g.level <= 4 ? g.level : itemLevel(it, highlights);
    return {
      id: it.id, item: it, level, score: it.importance ?? g?.importance ?? importance(it),
      cover: cover(it), video: videoOf(it), date: it.taken_at, text: it.summary || it.description || it.caption || '',
      audio: audioOf(it),
    };
  });
  for (const h of hits.filter((h) => h.clip || h.frame || h.video?.thumbnail)) {
    tiles.push({
      id: h.id, hit: h, level: given.get(h.id)?.level || hitLevel(h), score: h.confidence ?? 0.5,
      cover: h.frame || h.video?.thumbnail || undefined, video: h.clip || undefined,
      date: h.video?.posted_at || h.found_at, text: titleOf(h),
      audio: { kind: 'heard', text: heardOf(h) },
    });
  }

  // Sections by subject: each video in the biggest category of the facet that splits them best; the
  // ones left go through the next facet; categories under three videos give theirs back.
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
      if (x.tiles.length >= MIN_THEME) groups.push({ id: `${facet.id}:${x.c.id}`, title: x.c.name, about: x.c.description, tiles: x.tiles });
      else left.push(...x.tiles);
    }
    rest = left;
    facets = (facets || []).filter((f) => f !== facet);
  }
  if (rest.length) groups.push({ id: 'more', title: groups.length ? 'More videos' : 'Videos', tiles: rest });

  // The most important sections first: their best level, then their weight.
  const LW = [1, 0.5, 0.25, 0.125];
  const weight = (l: VTile[]) => l.reduce((s, t) => s + LW[t.level - 1] * (0.5 + t.score), 0);
  const best = (l: VTile[]) => Math.min(...l.map((t) => t.level));
  return groups
    .sort((a, b) => (a.id === 'more' ? 1 : 0) - (b.id === 'more' ? 1 : 0) || best(a.tiles) - best(b.tiles) || weight(b.tiles) - weight(a.tiles))
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
