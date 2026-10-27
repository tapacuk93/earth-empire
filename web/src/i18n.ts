// The site in the visitor's language (CONTRACT.md "Translations"): the browser's language goes to the
// API as ?lang= (items, highlights and categories come back translated where the backend has them),
// and the site's own words (i18n/strings.json) are looked up in /v1/i18n. The owner, signed in,
// always sees the originals. English, or no translation yet: the original text.
import { API_BASE, MOCK } from './config';

function pick(): string | null {
  try { if (localStorage.getItem('ee-admin-token')) return null; } catch { /* blocked */ }
  const tag = (typeof navigator !== 'undefined' && (navigator.languages?.[0] || navigator.language)) || '';
  const m = /^([a-z]{2,3})\b/i.exec(tag);
  const lang = m ? m[1].toLowerCase() : null;
  return lang && lang !== 'en' ? lang : null;
}

export const LANG: string | null = MOCK ? null : pick();
let strings: Record<string, string> = {};

/** `path` with ?lang= for the endpoints the backend translates. */
export function withLang(path: string): string {
  if (!LANG || !/^\/v1\/(items|facets|highlights)/.test(path)) return path;
  return path + (path.includes('?') ? '&' : '?') + 'lang=' + LANG;
}

/** The site's own word or phrase in the visitor's language. */
export const t = (s: string): string => strings[s] || s;

/** Load the site's words before the first render (at most `wait` ms; the originals otherwise). */
export async function loadStrings(wait = 1500): Promise<void> {
  if (!LANG) return;
  document.documentElement.lang = LANG;
  const got = fetch(`${API_BASE}/v1/i18n?lang=${LANG}`).then((r) => (r.ok ? r.json() : null))
    .then((j: { strings?: Record<string, string> } | null) => { strings = j?.strings || {}; }).catch(() => undefined);
  await Promise.race([got, new Promise((r) => setTimeout(r, wait))]);
}
