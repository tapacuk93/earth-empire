// Everything the infographics show, computed from the items.
import { computeTags } from './tags';
import type { Category, Item, Tag } from './types';

export interface Month { key: string; label: string; date: Date; total: number; byKind: Record<string, number> }
export interface Place { name: string; country?: string; lat?: number; lng?: number; count: number; items: string[] }
export interface PersonStat { who: string; count: number; basis?: string; items: string[] }
export interface Moment { item: Item; at?: number; media?: number; text: string }

const monthFmt = new Intl.DateTimeFormat('en', { month: 'short', year: 'numeric', timeZone: 'UTC' });
export const monthKey = (iso: string) => iso.slice(0, 7);

export function months(items: Item[]): Month[] {
  const map = new Map<string, Month>();
  for (const it of items) {
    const k = monthKey(it.taken_at);
    if (!/^\d{4}-\d{2}$/.test(k)) continue;
    let m = map.get(k);
    if (!m) { const d = new Date(k + '-01T00:00:00Z'); m = { key: k, label: monthFmt.format(d), date: d, total: 0, byKind: {} }; map.set(k, m); }
    m.total++;
    m.byKind[it.kind] = (m.byKind[it.kind] || 0) + 1;
  }
  const list = [...map.values()].sort((a, b) => a.key.localeCompare(b.key));
  if (list.length < 2) return list;
  // Fill the empty months, so the band is a true time axis.
  const out: Month[] = [];
  const d = new Date(list[0].date);
  const end = list[list.length - 1].date;
  while (d <= end) {
    const k = d.toISOString().slice(0, 7);
    out.push(map.get(k) || { key: k, label: monthFmt.format(d), date: new Date(d), total: 0, byKind: {} });
    d.setUTCMonth(d.getUTCMonth() + 1);
  }
  return out;
}

export function places(items: Item[]): Place[] {
  const map = new Map<string, Place>();
  for (const it of items) {
    const loc = it.location;
    const w = it.analysis?.where;
    const name = loc?.name || w?.place;
    if (!name || /^(unknown|not stated|unclear)/i.test(name)) continue;
    const key = name.toLowerCase();
    let p = map.get(key);
    if (!p) { p = { name, country: w?.country || undefined, count: 0, items: [] }; map.set(key, p); }
    if (typeof loc?.lat === 'number' && typeof loc?.lng === 'number') { p.lat = loc.lat; p.lng = loc.lng; }
    p.count++;
    p.items.push(it.id);
  }
  return [...map.values()].sort((a, b) => b.count - a.count);
}

export function people(items: Item[]): PersonStat[] {
  const map = new Map<string, PersonStat>();
  for (const it of items) {
    const seen = new Set<string>();
    for (const p of it.analysis?.people || []) {
      if (!p.who) continue; // only people the post itself names
      const k = p.who.toLowerCase();
      if (seen.has(k)) continue;
      seen.add(k);
      let s = map.get(k);
      if (!s) { s = { who: p.who, count: 0, basis: p.basis, items: [] }; map.set(k, s); }
      s.count++;
      s.items.push(it.id);
    }
  }
  return [...map.values()].sort((a, b) => b.count - a.count);
}

/** Key moments: the timeline events of videos, else each item's one-line summary. */
export function moments(items: Item[], max = 8): Moment[] {
  const out: Moment[] = [];
  for (const it of items) {
    const ev = it.analysis?.events?.[0];
    if (ev) out.push({ item: it, at: ev.at, media: ev.media, text: ev.text });
    else if (it.summary) out.push({ item: it, text: it.summary });
    if (out.length >= max) break;
  }
  return out;
}

export function kinds(items: Item[]): Record<string, number> {
  const out: Record<string, number> = {};
  items.forEach((it) => { out[it.kind] = (out[it.kind] || 0) + 1; });
  return out;
}

export const tagsOf = (items: Item[]): Tag[] => computeTags(items);

export function categoryCounts(items: Item[], cats: Category[]): { slug: string; name: string; count: number }[] {
  const names = new Map(cats.map((c) => [c.slug, c.name]));
  const map = new Map<string, number>();
  items.forEach((it) => (it.categories || []).forEach((c) => map.set(c, (map.get(c) || 0) + 1)));
  return [...map.entries()].map(([slug, count]) => ({ slug, name: names.get(slug) || slug, count })).sort((a, b) => b.count - a.count);
}
