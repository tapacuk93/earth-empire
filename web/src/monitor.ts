// The monitor: videos from official accounts that mention the watched phrases.
// PROVISIONAL: CONTRACT.md's Monitor section is not written yet. Everything the site reads from
// those endpoints passes through `normalize`, so adapting to the final shape touches only this file.
import { ApiError } from './api';
import { API_BASE, MOCK } from './config';
import { adminToken } from './live';

export interface Match { phrase?: string; text?: string; at?: number | null }
export interface MonitorVideo {
  id: string;
  title: string;
  url: string;              // the video
  cover?: string;
  account?: string;         // who posted it
  accountName?: string;
  platform?: string;
  sourceUrl?: string;
  takenAt?: string;
  foundAt?: string;
  confidence?: number;      // 0..1
  low: boolean;             // a low-confidence hit
  matches: Match[];
  transcript?: string;
  published: boolean;
  item?: string;            // the archive item, when it has one
}
export interface VideoPage { videos: MonitorVideo[]; next: string | null }

export const LOW_CONFIDENCE = 0.6;
type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export function normalize(r: Raw): MonitorVideo {
  const m0 = Array.isArray(r.media) ? r.media.find((m: Raw) => m.type === 'video') || r.media[0] : null;
  const src: Raw = r.source && typeof r.source === 'object' ? r.source : {};
  let conf = r.confidence ?? r.score ?? null;
  if (typeof conf === 'number' && conf > 1) conf = conf / 100;
  const account = src.account || src.username || r.account || r.channel || r.author || undefined;
  return {
    id: String(r.id),
    title: r.title || r.summary || r.caption || r.description || 'Video',
    url: r.video_url || m0?.url || r.url,
    cover: r.cover || m0?.cover || m0?.thumbnail || r.thumbnail || undefined,
    account: account ? String(account).replace(/^@/, '') : undefined,
    accountName: src.name || r.account_name || r.channel_name || undefined,
    platform: src.platform || r.platform || undefined,
    sourceUrl: src.url || r.source_url || undefined,
    takenAt: r.taken_at || r.published_at_source || r.posted_at || undefined,
    foundAt: r.found_at || r.created_at || undefined,
    confidence: typeof conf === 'number' ? conf : undefined,
    low: r.low_confidence ?? (typeof conf === 'number' ? conf < LOW_CONFIDENCE : false),
    matches: (r.matches || r.hits || []).map((m: Raw) => (typeof m === 'string' ? { text: m } : { phrase: m.phrase, text: m.text || m.quote, at: m.at ?? m.start ?? null })),
    transcript: typeof r.transcript === 'string' ? r.transcript : r.transcript?.text,
    published: !!(r.published ?? r.published_at),
    item: r.item_id || r.item || undefined,
  };
}

const list = (j: Raw): Raw[] => j.videos || j.items || j.published || [];

async function get(path: string): Promise<Raw> {
  const r = await fetch(API_BASE + path, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new ApiError(r.status, `${r.status} for ${path}`);
  return r.json();
}

// ---- mock ----
let mockData: Promise<MonitorVideo[]> | null = null;
const mockVideos = () => (mockData ??= fetch('/mock/monitor.json').then((r) => r.json()).then((j: Raw) => list(j).map(normalize)));

/** Found videos, highest confidence first. */
export async function getMonitorVideos(before?: string): Promise<VideoPage> {
  if (MOCK) {
    const all = (await mockVideos()).slice().sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
    return { videos: all, next: null };
  }
  const j = await get(`/v1/monitor/videos?sort=confidence&limit=50${before ? '&before=' + encodeURIComponent(before) : ''}`);
  const videos = list(j).map(normalize).sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
  return { videos, next: j.next ?? null };
}

/** The monitor videos that went public, newest first. */
export async function getPublished(): Promise<MonitorVideo[]> {
  if (MOCK) return (await mockVideos()).filter((v) => v.published);
  try { return list(await get('/v1/published?limit=50')).map(normalize); }
  catch (e) { if (e instanceof ApiError && e.status === 404) return []; throw e; } // not deployed yet
}

/** Owner only: publish a found video. */
export async function publishVideo(id: string): Promise<void> {
  if (MOCK) {
    if (adminToken() !== 'owner') throw new ApiError(401, '401 Unauthorized');
    (await mockVideos()).forEach((v) => { if (v.id === id) v.published = true; });
    return;
  }
  const r = await fetch(`${API_BASE}/v1/monitor/videos/${encodeURIComponent(id)}/publish`, { method: 'POST', headers: { Authorization: `Bearer ${adminToken()}` } });
  if (!r.ok) throw new ApiError(r.status, `${r.status} publishing ${id}`);
}
