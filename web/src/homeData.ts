// Home's data from the API (CONTRACT.md "The API": /v1/layout, /v1/items/{id}/related,
// /v1/tags/graph). Each returns null when the API cannot serve it (or in the mock), and the
// caller falls back to computing the same thing in the browser (src/layout.ts).
import { getAllItems, getItems } from './api';
import { API_BASE, MOCK } from './config';
import type { Item } from './types';

export interface LayoutTile { id: string; kind: 'item' | 'hit'; x: number; y: number; size: number; label?: string; taken_at?: string; attached_to?: string | null }
export interface Layout { top: LayoutTile[]; bottom: LayoutTile[]; exponent: number }
export interface Related { id: string; kind: 'item' | 'hit'; half?: string; score?: number; item?: Item }
export interface GraphNode { tag: string; kinds?: string[]; count: number; level: number; facet?: string; facet_name?: string; category?: string }
export interface GraphEdge { a: string; b: string; count: number; weight?: number }

async function get<T>(path: string): Promise<T | null> {
  if (MOCK) return null;
  try {
    const r = await fetch(API_BASE + path, { headers: { Accept: 'application/json' } });
    return r.ok ? ((await r.json()) as T) : null;
  } catch { return null; }
}

let layout: Promise<Layout | null> | null = null;
export const getLayout = () => (layout ??= get<{ halves: { top: LayoutTile[]; bottom: LayoutTile[] }; display_exponent?: number }>('/v1/layout').then((j) => (j?.halves ? { ...j.halves, exponent: j.display_exponent || 2 } : null)));

export const getRelated = (id: string, limit = 40) =>
  get<{ related: Related[] }>(`/v1/items/${encodeURIComponent(id)}/related?limit=${limit}`).then((j) => j?.related || null);

let graph: Promise<{ nodes: GraphNode[]; edges: GraphEdge[] } | null> | null = null;
export const getTagGraph = () => (graph ??= get<{ nodes: GraphNode[]; edges: GraphEdge[] }>('/v1/tags/graph?max_nodes=300').then((j) => (j?.nodes?.length ? j : null)));

/** A tag's items, newest first, from the API's `items?tag=`. */
export async function tagItems(tag: string): Promise<Item[] | null> {
  if (MOCK) return null;
  try { return (await getItems({ tag, limit: 100 })).items; } catch { return null; }
}

// ---- facets (CONTRACT.md "Facets"): AI-defined groupings that replace fixed places and categories ----
export interface FacetCategory { id: string; name: string; description?: string; count: number; item_ids: string[] }
export interface Facet { id: string; name: string; description?: string; categories: FacetCategory[] }
let facets: Promise<Facet[] | null> | null = null;
export function getFacets(): Promise<Facet[] | null> {
  if (MOCK) {
    return (facets ??= getAllItems().then((items) => {
      const group = (id: string, name: string, key: (it: Item) => string[]) => {
        const m = new Map<string, string[]>();
        items.forEach((it) => key(it).forEach((k) => m.set(k, [...(m.get(k) || []), it.id])));
        return { id, name, categories: [...m.entries()].map(([n, ids]) => ({ id: n.toLowerCase().replace(/[^a-z0-9]+/g, '-'), name: n, count: ids.length, item_ids: ids })).sort((a, b) => b.count - a.count) };
      };
      return [
        group('topic', 'Topic', (it) => (it.categories || []).map((c) => c[0].toUpperCase() + c.slice(1))),
        group('place', 'Place', (it) => [it.location?.name || it.analysis?.where?.place].filter((x): x is string => !!x)),
      ];
    }));
  }
  return (facets ??= get<{ facets: Facet[] }>('/v1/facets').then((j) => (j?.facets?.length ? j.facets : null)));
}
