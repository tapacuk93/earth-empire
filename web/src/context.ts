// A context is where an item was opened from: the vertical feed then moves through that context.
//   all · section:<id> · tag:<tag> · month:YYYY-MM · place:<name> · cat:<slug> · person:<who> · hl:<id> · q:<text> · kind:<kind>
import type { Category, Highlight, Item } from './types';
import { hasTag } from './tags';
import { SECTION_TITLE, sectionItems, type SectionId } from './sections';
import { relatedOrder } from './layout';

let facetIndex = new Map<string, { name: string; ids: string[] }>();
/** Facet categories by "<facet>:<category>", so facet contexts resolve synchronously. */
export function setFacets(list: { id: string; name: string; categories: { id: string; name: string; item_ids: string[] }[] }[]) {
  facetIndex = new Map(list.flatMap((f) => f.categories.map((c) => [`${f.id}:${c.id}`, { name: c.name, ids: c.item_ids }] as const)));
}

export const itemHref = (id: string, ctx = 'all') => `/item/${encodeURIComponent(id)}${ctx && ctx !== 'all' ? `?ctx=${encodeURIComponent(ctx)}` : ''}`;

const split = (ctx: string): [string, string] => { const i = ctx.indexOf(':'); return i < 0 ? [ctx, ''] : [ctx.slice(0, i), ctx.slice(i + 1)]; };

export function ctxItems(ctx: string, items: Item[], highlights: Highlight[]): Item[] {
  const [k, v] = split(ctx || 'all');
  const lv = v.toLowerCase();
  switch (k) {
    case 'section': return sectionItems(v as SectionId, items, highlights);
    case 'rel': {
      // rel:<section>:<id> - that half, most related to the opened video first, then the other half's most related.
      const [sec, ...rest] = v.split(':');
      const anchor = items.find((it) => it.id === rest.join(':'));
      if (sec === 'all') return anchor ? relatedOrder(anchor, items, []) : items;
      if (!anchor) return sectionItems(sec as SectionId, items, highlights);
      const other: SectionId = sec === 'dedicated' ? 'common' : 'dedicated';
      return relatedOrder(anchor, sectionItems(sec as SectionId, items, highlights), sectionItems(other, items, highlights));
    }
    case 'tag': return items.filter((it) => hasTag(it, v));
    case 'facet': { const ids = new Set(facetIndex.get(v)?.ids || []); return items.filter((it) => ids.has(it.id)); }
    case 'month': return items.filter((it) => it.taken_at.startsWith(v));
    case 'place': return items.filter((it) => (it.location?.name || it.analysis?.where?.place || '').toLowerCase() === lv);
    case 'cat': return items.filter((it) => it.categories?.includes(v));
    case 'person': return items.filter((it) => it.analysis?.people?.some((p) => p.who?.toLowerCase() === lv));
    case 'kind': return items.filter((it) => it.kind === v);
    case 'q': {
      const words = lv.split(/\s+/).filter(Boolean);
      return items.filter((it) => { const hay = JSON.stringify([it.caption, it.summary, it.description, it.hashtags, it.location, it.analysis]).toLowerCase(); return words.every((w) => hay.includes(w)); });
    }
    case 'hl': {
      const h = highlights.find((x) => x.id === v);
      const byId = new Map(items.map((it) => [it.id, it]));
      return h ? h.item_ids.map((id) => byId.get(id)).filter((x): x is Item => !!x) : [];
    }
    default: return items;
  }
}

export function ctxLabel(ctx: string, cats: Category[] = [], highlights: Highlight[] = []): string {
  const [k, v] = split(ctx || 'all');
  switch (k) {
    case 'section': return SECTION_TITLE[v as SectionId] || v;
    case 'rel': return 'Related';
    case 'tag': return `Tag: ${v}`;
    case 'facet': return facetIndex.get(v)?.name || v;
    case 'month': return new Intl.DateTimeFormat('en', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(v + '-01T00:00:00Z'));
    case 'place': return v;
    case 'cat': return cats.find((c) => c.slug === v)?.name || v;
    case 'person': return v;
    case 'q': return `“${v}”`;
    case 'hl': return highlights.find((h) => h.id === v)?.title || 'Highlight';
    default: return 'Everything';
  }
}
