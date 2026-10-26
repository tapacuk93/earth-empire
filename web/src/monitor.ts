// The monitor (CONTRACT.md "Monitor"): hits - moments in public videos that sound like one of the
// owner's phrases, or Ukrainian/Russian speech where it is not expected.
import { ApiError } from './api';
import { API_BASE, MOCK } from './config';
import { adminToken } from './live';

export interface Hit {
  id: string;
  kind: 'name' | 'language';
  phrase?: string | null;
  matched?: string;
  confidence?: number;
  confidence_label?: 'likely' | 'possible' | 'low confidence' | string;
  notes?: string[];
  judge?: { by?: string; name_probability?: number; reason?: string } | null;
  language?: string;
  expected_languages?: string[];
  platform?: string;
  source_kind?: string;
  source?: { id?: string; name?: string; kind?: string | null; country?: string | null; source_kind?: string };
  account?: string | null;
  video?: { id?: string; url?: string; title?: string | null; posted_at?: string | null; duration?: number | null; thumbnail?: string | null };
  start?: number; end?: number;
  at_url?: string | null;
  excerpt?: { text?: string; start?: number; end?: number; language?: string; en?: string | null };
  clip?: string | null;
  frame?: string | null;
  found_at?: string;
  published_at?: string | null;
}
export interface HitPage { hits: Hit[]; next: string | null }

export const labelOf = (h: Hit) => h.confidence_label || (typeof h.confidence === 'number' ? (h.confidence >= 0.7 ? 'likely' : h.confidence >= 0.4 ? 'possible' : 'low confidence') : '');
export const isLow = (h: Hit) => labelOf(h) === 'low confidence';
export const LANG: Record<string, string> = { uk: 'Ukrainian', ru: 'Russian', en: 'English' };
export const whatOf = (h: Hit) => (h.kind === 'language' ? `${LANG[h.matched || ''] || h.matched} speech` : `“${h.matched || h.phrase}”`);
/**
 * What sounds in the clip, as short as a highlight name ("в Тараса 3"): the words around the match
 * in the transcript (two on each side), else the first words, else the match itself.
 */
export function heardOf(h: Hit): string {
  const text = (h.excerpt?.text || '').replace(/\s+/g, ' ').trim();
  const words = text ? text.split(' ') : [];
  const key = (h.kind === 'name' ? h.matched || h.phrase || '' : '').toLowerCase().split(' ')[0];
  const at = key ? words.findIndex((w) => w.toLowerCase().includes(key)) : -1;
  const strip = (s: string) => s.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');
  if (at >= 0) return words.slice(Math.max(0, at - 2), at + 3).map(strip).filter(Boolean).join(' ');
  if (words.length) return words.slice(0, 6).map(strip).filter(Boolean).join(' ') + (words.length > 6 ? '…' : '');
  return h.kind === 'language' ? whatOf(h) : h.matched || h.phrase || '';
}
export const titleOf = (h: Hit) => h.video?.title || `${whatOf(h)} in ${h.source?.name || h.account || h.platform || 'a video'}`;
/** Only links a person can open: never a signed storage URL. */
export const safeUrl = (u?: string | null) => (u && /^https?:\/\//.test(u) && !/X-Amz-Signature=/i.test(u) ? u : undefined);

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const t = adminToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const r = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' });
  if (!r.ok) {
    let detail = '';
    try { const j = await r.json(); detail = j.detail || j.error || ''; } catch { /* not JSON */ }
    throw new ApiError(r.status, `${r.status}${detail ? ': ' + detail : ''}`);
  }
  return r.json() as Promise<T>;
}

// ---- mock ----
let mock: Promise<Hit[]> | null = null;
const mockHits = () => (mock ??= fetch('/mock/monitor.json').then((r) => r.json()).then((j: { hits: Hit[] }) => j.hits));
const ownerOk = () => { if (adminToken() !== 'owner') throw new ApiError(401, '401: owner token required'); };

/** Hits, highest confidence first. */
export async function getHits(opts: { kind?: string; before?: string; limit?: number } = {}): Promise<HitPage> {
  if (MOCK) {
    let all = (await mockHits()).slice().sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
    if (opts.kind) all = all.filter((h) => h.kind === opts.kind);
    const i = opts.before ? all.findIndex((h) => h.id === opts.before) + 1 : 0;
    const n = opts.limit ?? 30;
    const page = all.slice(i, i + n);
    return { hits: page, next: i + n < all.length ? page[page.length - 1].id : null };
  }
  const p = new URLSearchParams({ sort: 'confidence', limit: String(opts.limit ?? 30) });
  if (opts.kind) p.set('kind', opts.kind);
  if (opts.before) p.set('before', opts.before);
  const j = await req<HitPage>('GET', '/v1/monitor/hits?' + p);
  return { hits: j.hits || [], next: j.next ?? null };
}

/** The hits the owner published, newest first: Home's monitor row. */
export async function getPublished(): Promise<Hit[]> {
  if (MOCK) return (await mockHits()).filter((h) => h.published_at).sort((a, b) => String(b.published_at).localeCompare(String(a.published_at)));
  try { return (await req<HitPage>('GET', '/v1/published?limit=50')).hits || []; }
  catch (e) { if (e instanceof ApiError && e.status === 404) return []; throw e; }
}

export async function setPublished(id: string, on: boolean, section?: string, level?: number): Promise<Hit> {
  if (MOCK) {
    ownerOk();
    const h = (await mockHits()).find((x) => x.id === id)! as Hit & { section?: string | null };
    h.published_at = on ? new Date().toISOString() : null;
    h.section = on ? section || 'common' : null;
    (h as Hit & { level?: number | null }).level = on ? level ?? null : null;
    return { ...h };
  }
  return req<Hit>('POST', `/v1/monitor/hits/${encodeURIComponent(id)}/${on ? 'publish' : 'unpublish'}`, on ? { ...(section ? { section } : {}), ...(level ? { level } : {}) } : undefined);
}

/** Ask the monitor to scan at least n more videos. */
export async function fetchMore(n: number): Promise<{ n?: number; queued?: number; to_discover?: number }> {
  if (MOCK) { ownerOk(); return { n, queued: Math.min(n, 7), to_discover: Math.max(0, n - 7) }; }
  return req('POST', '/v1/monitor/fetch', { n });
}

/** The monitor's own numbers: queues, totals, throughput, caps, stops. */
export async function getMonitorStatus(): Promise<Record<string, unknown>> {
  if (MOCK) return { totals: { videos: 1240, scanned: 1187, hits: 4 }, queue: { youtube: { queued: 12, running: 1 }, telegram: { queued: 30 } }, cpu_per_audio: 0.21, usage: { videos_today: 210, cap: 600 }, stops: [] };
  return req('GET', '/v1/monitor/status');
}
