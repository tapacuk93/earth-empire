import type { Item, Tag, TagKind } from './types';

// Mirrors how the backend builds GET /v1/tags (CONTRACT.md), for the mock and for the fallback
// while an API without /v1/tags is deployed.
const NAMED = new Set(['tag', 'mention', 'caption']);

/** Every tag an item carries, as `<kind>:<tag>` keys; tags are lowercase. */
export function itemTags(it: Item): Map<string, { kind: TagKind; tag: string }> {
  const out = new Map<string, { kind: TagKind; tag: string }>();
  const add = (kind: TagKind, v?: string | null) => {
    const tag = (v || '').trim().toLowerCase();
    if (tag) out.set(`${kind}:${tag}`, { kind, tag });
  };
  const a = it.analysis;
  (it.categories || []).forEach((c) => add('category', c));
  (a?.keywords || []).forEach((k) => add('keyword', k));
  // People only by the name the post itself gives.
  (a?.people || []).forEach((p) => { if (p.who && NAMED.has(p.basis || '')) add('person', p.who); });
  add('place', it.location?.name);
  add('place', a?.where?.place);
  add('country', a?.where?.country);
  (a?.objects || []).forEach((o) => add('object', o));
  (a?.animals || []).forEach((o) => add('animal', o));
  (a?.brands || []).forEach((o) => add('brand', o));
  (it.hashtags || []).forEach((h) => add('hashtag', h));
  add('mood', a?.mood);
  add('occasion', a?.when?.occasion);
  return out;
}

/** `tag` matches any kind, case-insensitively, as the API's `items?tag=` does. */
export function hasTag(it: Item, tag: string): boolean {
  const t = tag.toLowerCase();
  for (const v of itemTags(it).values()) if (v.tag === t) return true;
  return false;
}

export function computeTags(items: Item[]): Tag[] {
  const tags = new Map<string, Tag>();
  for (const it of items) {
    for (const [key, t] of itemTags(it)) {
      const cur = tags.get(key);
      if (cur) cur.count++; else tags.set(key, { ...t, count: 1 });
    }
  }
  return [...tags.values()].sort((x, y) => y.count - x.count || x.tag.localeCompare(y.tag));
}
