// The live, uncached parts of the API: status, the owner's token, and the monitor's phrases.
import { useEffect, useState } from 'preact/hooks';
import { ApiError } from './api';
import { API_BASE, MOCK } from './config';

// ---- the owner's token: kept in this browser only ----
const TOKEN_KEY = 'ee-admin-token';
export function adminToken(): string { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }
export function setAdminToken(t: string) {
  try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); } catch { /* blocked */ }
  verified = t ? Promise.resolve(true) : Promise.resolve(false); // set only after checkAdmin accepted it
  ownerListeners.forEach((f) => f());
}

// ---- owner mode: on only once the stored token passed GET /v1/admin/me ----
let verified: Promise<boolean> | null = null;
const ownerListeners = new Set<() => void>();
export function ownerCheck(): Promise<boolean> {
  return (verified ??= (async () => {
    const t = adminToken();
    if (!t) return false;
    try {
      const ok = await checkAdmin(t);
      if (!ok) { try { localStorage.removeItem(TOKEN_KEY); } catch { /* blocked */ } }
      return ok;
    } catch { return false; } // unreachable API: stay a visitor this time, keep the token
  })());
}
/** `undefined` while checking. */
export function useOwner(): boolean | undefined {
  const [ok, setOk] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    let live = true;
    const run = () => ownerCheck().then((v) => live && setOk(v));
    run();
    ownerListeners.add(run);
    return () => { live = false; ownerListeners.delete(run); };
  }, []);
  return ok;
}

async function call<T>(method: string, path: string, body?: unknown, admin = false): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (admin) headers.Authorization = `Bearer ${adminToken()}`;
  const r = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' });
  if (!r.ok) throw new ApiError(r.status, `${r.status} ${r.statusText} for ${method} ${path}`);
  return (r.status === 204 ? undefined : await r.json()) as T;
}

// ---- status (CONTRACT.md "Status") ----
export type State = 'ok' | 'degraded' | 'down' | 'off';
export interface Component { id: string; name?: string; state: State; last_success?: string | null; last_error?: { at?: string; message?: string } | null; details?: Record<string, unknown> }
export interface Job { component: string; what: string; item?: string | null; progress?: number | null; started_at?: string; elapsed_s?: number }
export interface StatusEvent { at: string; component: string; kind?: string; text: string; item?: string | null; ok?: boolean }
export interface Status { generated_at: string; overall: State; components: Component[]; activity?: { jobs?: Job[]; events?: StatusEvent[] } }

export async function getStatus(): Promise<Status> {
  if (MOCK) return mockStatus();
  return call<Status>('GET', '/v1/status', undefined, !!adminToken());
}

/** Checks the token with GET /v1/admin/me. */
export async function checkAdmin(token: string): Promise<boolean> {
  if (MOCK) return token === 'owner';
  const r = await fetch(API_BASE + '/v1/admin/me', { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' });
  if (r.status === 401 || r.status === 403) return false;
  if (!r.ok) throw new ApiError(r.status, `${r.status} for /v1/admin/me`);
  return !!(await r.json()).ok;
}

// ---- the monitor's phrases ----
export interface Phrase { text: string; variants?: string[]; mishearings?: string[]; claude_variants?: string[]; updated_at?: string }

let mockPhrases: Phrase[] = [{ text: 'тарас' }, { text: 'тарас маслов' }, { text: 'маслов' }].map((p) => ({ ...p, variants: mockVariants(p.text) }));
function mockVariants(t: string): string[] {
  const map: Record<string, string> = { а: 'a', б: 'b', в: 'v', г: 'h', д: 'd', е: 'e', є: 'ie', ж: 'zh', з: 'z', и: 'y', і: 'i', ї: 'i', й: 'i', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'kh', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'shch', ь: '', ю: 'iu', я: 'ia' };
  const lat = [...t.toLowerCase()].map((c) => map[c] ?? c).join('');
  return [...new Set([lat, t.replace(/а/g, 'о'), t.toUpperCase()])].filter((v) => v !== t);
}

export async function getPhrases(): Promise<Phrase[]> {
  if (MOCK) return mockPhrases.map((p) => ({ ...p }));
  return (await call<{ phrases: Phrase[] }>('GET', '/v1/monitor/phrases', undefined, !!adminToken())).phrases || [];
}

export async function savePhrases(texts: string[]): Promise<Phrase[]> {
  if (MOCK) {
    if (adminToken() !== 'owner') throw new ApiError(401, '401 Unauthorized');
    mockPhrases = texts.map((text) => ({ text, variants: mockVariants(text) }));
    return getPhrases();
  }
  const r = await call<{ phrases?: Phrase[] } | undefined>('PUT', '/v1/monitor/phrases', { phrases: texts }, true);
  return r?.phrases || getPhrases();
}

export async function rescan(): Promise<unknown> {
  if (MOCK) { if (adminToken() !== 'owner') throw new ApiError(401, '401 Unauthorized'); return { ok: true }; }
  return call('POST', '/v1/monitor/rescan', {}, true);
}

// ---- mock status ----
function mockStatus(): Status {
  const now = Date.now();
  const ago = (s: number) => new Date(now - s * 1000).toISOString();
  return {
    generated_at: ago(0), overall: 'degraded',
    components: [
      { id: 'api', name: 'API', state: 'ok', last_success: ago(2), last_error: null, details: { requests_5m: 312, p95_ms: 41 } },
      { id: 'db', name: 'Database', state: 'ok', last_success: ago(2), details: { items: 28, published: 28, size_mb: 3.2 } },
      { id: 'workers', name: 'Workers', state: 'ok', last_success: ago(30), details: { running: 2 } },
      { id: 'analyzer', name: 'Analyzer', state: 'ok', last_success: ago(140), details: { analyzed_today: 14, daily_cap: 40 } },
      { id: 'collector', name: 'Collector', state: 'degraded', last_success: ago(3600), last_error: { at: ago(600), message: 'Instagram asked to slow down; waiting 15 min' }, details: { last_run_items: 6 } },
      { id: 'monitor', name: 'Monitor', state: 'ok', last_success: ago(90), details: { channels: 12, videos_checked_today: 210 } },
      { id: 'x_poster', name: 'X poster', state: 'off', last_success: null, details: {} },
      { id: 'site', name: 'Site', state: 'ok', last_success: ago(1800), details: { pages: 39 } },
      { id: 'queues', name: 'Queues', state: 'ok', details: { analyze: { pending: 4, failed: 1 }, x: { pending: 28, posted: 0 } } },
      { id: 'disk', name: 'Disk', state: 'ok', details: { used_pct: 61 } },
    ],
    activity: {
      jobs: [
        { component: 'analyzer', what: 'Describing a reel', item: 'ig_3400000000000000008', progress: 0.62, started_at: ago(48), elapsed_s: 48 },
        { component: 'monitor', what: 'Transcribing a news video', item: null, progress: 0.3, started_at: ago(20), elapsed_s: 20 },
      ],
      events: [
        { at: ago(60), component: 'analyzer', kind: 'analyzed', text: 'Described a carousel', item: 'ig_3400000000000000002', ok: true },
        { at: ago(600), component: 'collector', kind: 'rate_limit', text: 'Instagram asked to slow down', item: null, ok: false },
        { at: ago(1800), component: 'site', kind: 'deploy', text: 'Site rebuilt with 39 pages', item: null, ok: true },
      ],
    },
  };
}

// ---- suggested phrases (CONTRACT.md: GET /v1/monitor/phrases → "suggested") ----
export interface PhraseSuggestion { text: string; reason?: string }
interface PhrasesResponse { phrases: Phrase[]; suggested?: { text: string; why?: string; state?: string }[] }
const REJECT_KEY = 'ee-rejected-phrases';
function rejectedLocal(): string[] { try { return JSON.parse(localStorage.getItem(REJECT_KEY) || '[]'); } catch { return []; } }

/** Claude's proposals from the highlight titles. The mock suggests the titles themselves. */
export async function getPhraseSuggestions(current: string[], highlightTitles: () => Promise<string[]>): Promise<PhraseSuggestion[]> {
  if (!MOCK) {
    const r = await call<PhrasesResponse>('GET', '/v1/monitor/phrases', undefined, true);
    return (r.suggested || []).filter((x) => !x.state || x.state === 'suggested').map((x) => ({ text: x.text, reason: x.why }));
  }
  const have = new Set(current.map((t) => t.trim().toLowerCase()));
  const rejected = new Set(rejectedLocal());
  const titles = await highlightTitles();
  return [...new Set(titles.map((t) => t.trim().toLowerCase()))].filter((t) => t && !have.has(t) && !rejected.has(t)).map((text) => ({ text, reason: 'from a highlight title' }));
}

/** Accepts a suggestion; returns the phrase list after it. */
export async function acceptPhraseSuggestion(text: string, current: string[]): Promise<Phrase[]> {
  if (MOCK) return savePhrases([...new Set([...current, text])]);
  return (await call<PhrasesResponse>('POST', `/v1/monitor/phrases/suggested/${encodeURIComponent(text)}/accept`, {}, true)).phrases || [];
}

export async function rejectPhraseSuggestion(text: string) {
  if (MOCK) { try { localStorage.setItem(REJECT_KEY, JSON.stringify([...new Set([...rejectedLocal(), text.toLowerCase()])])); } catch { /* blocked */ } return; }
  await call('POST', `/v1/monitor/phrases/suggested/${encodeURIComponent(text)}/reject`, {}, true);
}
