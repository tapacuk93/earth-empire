import type { Item, Media } from './types';
import { SITE_NAME } from './config';

const dateFmt = new Intl.DateTimeFormat('en', { year: 'numeric', month: 'long', day: 'numeric' });
const dateTimeFmt = new Intl.DateTimeFormat('en', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const shortFmt = new Intl.DateTimeFormat('en', { year: 'numeric', month: 'short', day: 'numeric' });
const numFmt = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

const valid = (s?: string | null) => !!s && !isNaN(Date.parse(s));
export const fmtDate = (s?: string | null) => (valid(s) ? dateFmt.format(new Date(s!)) : s || '');
export const fmtDateTime = (s?: string | null) => (valid(s) ? dateTimeFmt.format(new Date(s!)) : s || '');
export const fmtShort = (s?: string | null) => (valid(s) ? shortFmt.format(new Date(s!)) : s || '');
export const fmtCount = (n?: number | null) => (typeof n === 'number' ? numFmt.format(n) : '');

export function fmtTime(sec?: number | null): string {
  if (typeof sec !== 'number' || !isFinite(sec)) return '';
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export const KIND_LABEL: Record<string, string> = { post: 'Post', carousel: 'Carousel', reel: 'Reel', story: 'Story' };
export const KIND_PLURAL: Record<string, string> = { post: 'Posts', carousel: 'Carousels', reel: 'Reels', story: 'Stories' };

export const igProfile = (u: string) => `https://www.instagram.com/${encodeURIComponent(u.replace(/^@/, ''))}/`;

/** Alt text for one piece of an item's media, from the analysis when the source had none. */
export function altFor(item: Item, i = 0, m?: Media): string {
  const kind = m?.type === 'video' ? 'Video' : 'Photo';
  const n = item.media.length > 1 ? ` ${i + 1} of ${item.media.length}` : '';
  const text = item.alt_text || item.analysis?.what || item.description || item.summary || item.caption || '';
  return `${kind}${n}${text ? ': ' + text : ''}`.slice(0, 400);
}

export function itemTitle(item: Item): string {
  const t = item.summary || item.caption || `${KIND_LABEL[item.kind] || 'Item'} from ${fmtDate(item.taken_at)}`;
  return t.length > 90 ? t.slice(0, 87).trimEnd() + '…' : t;
}

/** The frame that stands for a piece of media: the backend's chosen `cover`, else `thumbnail`. */
export const posterOf = (m: Media) => m.cover || m.thumbnail || undefined;

export function cover(item: Item): string | undefined {
  const m = item.media[0] || item.repost_of?.media?.[0];
  return m ? posterOf(m) || (m.type === 'image' ? m.url : undefined) : undefined;
}

function setTag(attr: 'name' | 'property', key: string, value: string) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) { el = document.createElement('meta'); el.setAttribute(attr, key); document.head.appendChild(el); }
  el.content = value;
}

/** Keeps the tab title and share tags in step with the page (prerendered pages ship them already). */
export function setMeta(title: string, description?: string, image?: string, noindex = false) {
  const full = title === SITE_NAME ? title : `${title} · ${SITE_NAME}`;
  document.title = full;
  setTag('property', 'og:title', full);
  setTag('name', 'twitter:title', full);
  if (description) {
    setTag('name', 'description', description);
    setTag('property', 'og:description', description);
    setTag('name', 'twitter:description', description);
  }
  if (image) {
    const abs = new URL(image, location.href).href;
    setTag('property', 'og:image', abs);
    setTag('name', 'twitter:image', abs);
  }
  setTag('property', 'og:url', location.href);
  const robots = document.head.querySelector('meta[name="robots"]');
  if (noindex && !robots) setTag('name', 'robots', 'noindex');
  if (!noindex && robots) robots.remove();
}

export const prefersReducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
