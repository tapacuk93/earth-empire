// Home's two sections (CONTRACT.md "Monitor" calls them dedicated = upper, common = lower).
// Upper: the highlights with few items, plus the regular posts. Lower: the highlights with many.
// The split is by item count: a highlight with at most `threshold` items is upper. The threshold
// starts at the median count; VITE_SECTION_THRESHOLD or `?split=N` in the address overrides it.
// Published hits land in the section the owner chose (`section`).
import type { Highlight, Item } from './types';
import type { Hit } from './monitor';

export type SectionId = 'dedicated' | 'common';
export const SECTION_TITLE: Record<SectionId, string> = { dedicated: 'Posts and short highlights', common: 'Long highlights' };
export const SECTION_SHORT: Record<SectionId, string> = { dedicated: 'upper', common: 'lower' };
export const SECTIONS: SectionId[] = ['dedicated', 'common'];

export function threshold(highlights: Highlight[]): number {
  const fromUrl = Number(new URLSearchParams(location.search).get('split'));
  if (fromUrl > 0) return fromUrl;
  const fromEnv = Number(import.meta.env.VITE_SECTION_THRESHOLD);
  if (fromEnv > 0) return fromEnv;
  const counts = highlights.map((h) => h.item_ids.length).sort((a, b) => a - b);
  if (!counts.length) return 0;
  const mid = counts.length >> 1;
  return counts.length % 2 ? counts[mid] : (counts[mid - 1] + counts[mid]) / 2;
}

export function highlightSection(h: Highlight, all: Highlight[]): SectionId {
  return h.item_ids.length <= threshold(all) ? 'dedicated' : 'common';
}

export function sectionHighlights(id: SectionId, all: Highlight[]): Highlight[] {
  return all.filter((h) => highlightSection(h, all) === id);
}

/** Upper: items of the short highlights and every regular (non-story) post; lower: items of the long highlights. */
export function sectionItems(id: SectionId, items: Item[], all: Highlight[]): Item[] {
  const ids = new Set(sectionHighlights(id, all).map((h) => h.id));
  return items.filter((it) => (it.highlights || []).some((h) => ids.has(h.id)) || (id === 'dedicated' && it.kind !== 'story'));
}

const norm = (v: unknown): SectionId | undefined => (v === 'dedicated' ? 'dedicated' : v === 'common' ? 'common' : undefined);
/** Where a published hit sits; null when it is not published. */
export const hitSection = (h: Hit): SectionId | null => (h.published_at ? norm((h as { section?: unknown }).section) || 'common' : null);
