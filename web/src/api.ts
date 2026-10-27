import { API_BASE, MOCK } from './config';
import { computeTags, hasTag } from './tags';
import type { Category, Highlight, Item, ItemPage, ItemQuery, Profile, Tag } from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const cache = new Map<string, Promise<unknown>>();
const itemsById = new Map<string, Item>();

/** Items already seen in a list, so opening one renders at once. */
export function knownItem(id: string): Item | undefined { return itemsById.get(id); }
function remember(items: Item[]) { for (const it of items) itemsById.set(it.id, it); }

async function getJSON<T>(path: string): Promise<T> {
  const url = API_BASE + path;
  let p = cache.get(url) as Promise<T> | undefined;
  if (!p) {
    p = fetch(url, { headers: { Accept: 'application/json' } }).then(async (r) => {
      if (!r.ok) throw new ApiError(r.status, `${r.status} ${r.statusText} for ${path}`);
      return r.json() as Promise<T>;
    });
    cache.set(url, p);
    p.catch(() => cache.delete(url));
  }
  return p;
}

function qs(q: ItemQuery): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
}

// ---- mock: the fixture, filtered the way the API documents ----
interface Fixture { profile: Profile; highlights: Highlight[]; categories: Category[]; items: Item[] }
let fixture: Promise<Fixture> | null = null;
const loadFixture = (): Promise<Fixture> => (fixture ??= fetch("/mock/fixture.json").then((r) => r.json() as Promise<Fixture>));
const delay = <T,>(v: T) => new Promise<T>((res) => setTimeout(() => res(v), 60));

function matches(it: Item, q: string): boolean {
  const hay = [it.caption, it.summary, it.description, ...(it.hashtags ?? []).map((h) => '#' + h), ...(it.mentions ?? []).map((m) => '@' + m),
    it.location?.name, ...(it.highlights ?? []).map((h) => h.title), it.repost_of?.author, it.repost_of?.caption,
    it.analysis ? JSON.stringify(it.analysis) : ''].join(' \n').toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

/** Filters and pages a full list the way the API documents. */
function localPage(all: Item[], q: ItemQuery): ItemPage {
  let list = all.slice().sort((a, b) => b.taken_at.localeCompare(a.taken_at));
  if (q.kind) list = list.filter((x) => x.kind === q.kind);
  if (q.category) list = list.filter((x) => x.categories?.includes(q.category!));
  if (q.highlight) list = list.filter((x) => x.highlights?.some((h) => h.id === q.highlight));
  if (q.tag) list = list.filter((x) => hasTag(x, q.tag!));
  if (q.q) list = list.filter((x) => matches(x, q.q!));
  if (q.before) { const i = list.findIndex((x) => x.id === q.before); list = i >= 0 ? list.slice(i + 1) : []; }
  const limit = q.limit ?? 24;
  const page = list.slice(0, limit);
  return { items: page, next: list.length > limit ? page[page.length - 1].id : null };
}

async function mockItems(q: ItemQuery): Promise<ItemPage> {
  return delay(localPage((await loadFixture()).items, q));
}

// Until the API serves /v1/tags (and items?tag=), tags come from every item, read once.
let allItems: Promise<Item[]> | null = null;
/** Every public item, read once (the infographics are computed from them). */
export function getAllItems(): Promise<Item[]> {
  if (MOCK) return loadFixture().then((f) => { remember(f.items); return f.items.slice().sort((a, b) => b.taken_at.localeCompare(a.taken_at)); });
  return (allItems ??= (async () => {
    const out: Item[] = [];
    let before: string | undefined;
    for (let i = 0; i < 200; i++) {
      const page = await getJSON<ItemPage>('/v1/items' + qs({ limit: 100, before }));
      out.push(...page.items);
      if (!page.next) break;
      before = page.next;
    }
    remember(out);
    return out;
  })().catch((e) => { allItems = null; throw e; }));
}

let serverTags: Promise<Tag[] | null> | null = null;
function tryServerTags(): Promise<Tag[] | null> {
  return (serverTags ??= getJSON<{ tags: Tag[] }>('/v1/tags').then((r) => r.tags, (e) => {
    if (e instanceof ApiError && e.status >= 400 && e.status < 500) return null; // not deployed yet
    serverTags = null;
    throw e;
  }));
}

export async function getTags(): Promise<Tag[]> {
  if (MOCK) return delay(computeTags((await loadFixture()).items));
  const server = await tryServerTags();
  if (server) return server;
  return computeTags(await getAllItems());
}

// ---- the public API ----
export async function getProfile(): Promise<Profile> {
  return MOCK ? delay((await loadFixture()).profile) : getJSON<Profile>('/v1/profile');
}

export async function getItems(q: ItemQuery): Promise<ItemPage> {
  let page: ItemPage;
  if (MOCK) page = await mockItems(q);
  else if (q.tag && !(await tryServerTags())) page = localPage(await getAllItems(), q);
  else page = await getJSON<ItemPage>('/v1/items' + qs(q));
  remember(page.items);
  return page;
}

/**
 * What is happening in an item, in the viewer's language (GET /v1/items/{id}/explain): a post by its own
 * description, translated; anything else from its analysis. Null when the API cannot answer (or in the mock).
 */
export async function getExplain(id: string, lang: string): Promise<{ text: string; mode: 'caption' | 'analysis'; lang: string } | null> {
  if (MOCK) return null;
  try { return await getJSON(`/v1/items/${encodeURIComponent(id)}/explain?lang=${encodeURIComponent(lang)}`); } catch { return null; }
}

export async function getItem(id: string): Promise<Item> {
  if (MOCK) {
    const it = (await loadFixture()).items.find((x) => x.id === id);
    if (!it) throw new ApiError(404, `no item ${id}`);
    return delay(it);
  }
  const it = await getJSON<Item>('/v1/items/' + encodeURIComponent(id));
  remember([it]);
  return it;
}

export async function getHighlights(): Promise<Highlight[]> {
  return MOCK ? delay((await loadFixture()).highlights) : (await getJSON<{ highlights: Highlight[] }>('/v1/highlights')).highlights;
}

export async function getCategories(): Promise<Category[]> {
  return MOCK ? delay((await loadFixture()).categories) : (await getJSON<{ categories: Category[] }>('/v1/categories')).categories;
}

/** Every item of a highlight, in the highlight's own order. */
export async function getHighlightItems(h: Highlight): Promise<Item[]> {
  const got = new Map<string, Item>();
  let before: string | undefined;
  for (let guard = 0; guard < 20; guard++) {
    const page = await getItems({ highlight: h.id, limit: 100, before });
    page.items.forEach((x) => got.set(x.id, x));
    if (!page.next) break;
    before = page.next;
  }
  const missing = h.item_ids.filter((id) => !got.has(id));
  await Promise.all(missing.map((id) => getItem(id).then((x) => got.set(id, x)).catch(() => undefined)));
  const ordered = h.item_ids.map((id) => got.get(id)).filter((x): x is Item => !!x);
  return ordered.length ? ordered : [...got.values()];
}


// ---- Home's items page by page (scroll pagination): newest first, the next page when the viewer nears
// the end. One shared list, so returning to Home keeps what was loaded.
export interface PagedItems { items: Item[]; done: boolean; error?: Error }
const PAGE = 100;
let paged: PagedItems & { next?: string; busy?: Promise<void> } = { items: [], done: false };
const listeners = new Set<(p: PagedItems) => void>();
const emit = () => { const v = { items: paged.items, done: paged.done, error: paged.error }; listeners.forEach((f) => f(v)); };

export function morePagedItems(): Promise<void> {
  if (paged.done || paged.busy) return paged.busy || Promise.resolve();
  paged.busy = (async () => {
    try {
      if (MOCK) {
        paged.items = await getAllItems();
        paged.done = true;
      } else {
        const page = await getJSON<ItemPage>('/v1/items' + qs({ limit: PAGE, before: paged.next }));
        remember(page.items);
        paged.items = [...paged.items, ...page.items];
        paged.next = page.next || undefined;
        paged.done = !page.next;
      }
      paged.error = undefined;
    } catch (e) {
      paged.error = e as Error;
    } finally {
      paged.busy = undefined;
      emit();
    }
  })();
  return paged.busy;
}

export function watchPagedItems(f: (p: PagedItems) => void): () => void {
  listeners.add(f);
  return () => listeners.delete(f);
}
export const pagedNow = (): PagedItems => ({ items: paged.items, done: paged.done, error: paged.error });
