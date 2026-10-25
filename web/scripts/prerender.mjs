// After `vite build`: writes one small HTML shell per shareable route, each with its own title,
// description, Open Graph and Twitter card tags and a plain-HTML copy of the content (for
// crawlers, link previews and readers without JavaScript). The app replaces that copy on boot.
//
//   dist/index.html                     home
//   dist/item/<id>/index.html           every item
//   dist/highlight/<id>/index.html      every highlight
//   dist/category/<slug>/index.html     every category
//   dist/404.html                       generic shell: the SPA fallback (see README, CloudFront)
//   dist/sitemap.xml, dist/robots.txt
//
// Env: VITE_API_BASE (as for the build; `mock` reads mock/fixture.json), SITE_URL (default
// https://empire.earth). If the API cannot be reached the build still succeeds with the generic
// shells only, so routes keep working; their previews are generic until the next build.
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(ROOT, 'dist');
const API = (process.env.VITE_API_BASE || readEnvFile().VITE_API_BASE || 'https://api.empire.earth').replace(/\/+$/, '');
const SITE = (process.env.SITE_URL || 'https://empire.earth').replace(/\/+$/, '');
const NAME = 'Earth Empire';
const IOS_APP_ID = process.env.VITE_IOS_APP_ID || readEnvFile().VITE_IOS_APP_ID || '';

function readEnvFile() {
  const out = {};
  for (const f of ['.env', '.env.production']) {
    try {
      for (const line of readFileSync(join(ROOT, f), 'utf8').split('\n')) {
        const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*)\s*$/);
        if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, '');
      }
    } catch { /* none */ }
  }
  return out;
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const abs = (u) => (!u ? '' : /^https?:\/\//.test(u) ? u : SITE + (u.startsWith('/') ? '' : '/') + u);
const clip = (s, n = 200) => { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };
const day = (s) => { const d = new Date(s); return isNaN(d) ? '' : d.toISOString().slice(0, 10); };
const KIND = { post: 'Post', carousel: 'Carousel', reel: 'Reel', story: 'Story' };
const coverOf = (it) => { const m = it.media?.[0] || it.repost_of?.media?.[0]; return m ? m.cover || m.thumbnail || (m.type === 'image' ? m.url : '') : ''; };
const titleOf = (it) => clip(it.summary || it.caption || `${KIND[it.kind] || 'Item'} from ${day(it.taken_at)}`, 90);

async function getJSON(path) {
  const r = await fetch(API + path, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(20000) });
  if (!r.ok) throw new Error(`${r.status} for ${path}`);
  return r.json();
}

async function loadData() {
  if (API === 'mock') return JSON.parse(readFileSync(join(ROOT, 'mock/fixture.json'), 'utf8'));
  const [profile, { highlights }, { categories }] = await Promise.all([getJSON('/v1/profile'), getJSON('/v1/highlights'), getJSON('/v1/categories')]);
  const items = [];
  let before = '';
  for (let i = 0; i < 1000; i++) {
    const page = await getJSON(`/v1/items?limit=100${before ? '&before=' + encodeURIComponent(before) : ''}`);
    items.push(...page.items);
    if (!page.next) break;
    before = page.next;
  }
  return { profile, highlights, categories, items };
}

function head({ title, description, image, url, type = 'website', video, noindex }) {
  const full = title === NAME ? NAME : `${title} · ${NAME}`;
  const t = [
    `<title>${esc(full)}</title>`,
    `<meta name="description" content="${esc(description)}">`,
    url && `<link rel="canonical" href="${esc(url)}">`,
    noindex && '<meta name="robots" content="noindex">',
    `<meta property="og:site_name" content="${NAME}">`,
    `<meta property="og:type" content="${type}">`,
    `<meta property="og:title" content="${esc(full)}">`,
    `<meta property="og:description" content="${esc(description)}">`,
    url && `<meta property="og:url" content="${esc(url)}">`,
    image && `<meta property="og:image" content="${esc(abs(image))}">`,
    video && `<meta property="og:video" content="${esc(abs(video.url))}">`,
    video && '<meta property="og:video:type" content="video/mp4">',
    video?.width && `<meta property="og:video:width" content="${video.width}">`,
    video?.height && `<meta property="og:video:height" content="${video.height}">`,
    `<meta name="twitter:card" content="${image ? 'summary_large_image' : 'summary'}">`,
    `<meta name="twitter:title" content="${esc(full)}">`,
    `<meta name="twitter:description" content="${esc(description)}">`,
    image && `<meta name="twitter:image" content="${esc(abs(image))}">`,
    IOS_APP_ID && url && `<meta name="apple-itunes-app" content="app-id=${esc(IOS_APP_ID)}, app-argument=${esc(url)}">`,
  ];
  return t.filter(Boolean).join('\n');
}

const template = readFileSync(join(DIST, 'index.html'), 'utf8');
if (!template.includes('<!--ee:head-->') || !template.includes('<!--ee:body-->')) throw new Error('dist/index.html lost its ee: markers');
function page(file, meta, body) {
  const html = template
    .replace(/<!--ee:head-->[\s\S]*?<!--\/ee:head-->/, head(meta))
    .replace('<!--ee:body-->', `<div class="prerender">${body}</div>`);
  const out = join(DIST, file);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, html);
}

const itemLink = (it) => `<li><a href="/item/${encodeURIComponent(it.id)}">${esc(titleOf(it))}</a> <small>${esc(KIND[it.kind] || '')} · ${day(it.taken_at)}</small></li>`;

let data = null;
try { data = await loadData(); } catch (e) { console.warn(`prerender: could not load data from ${API} (${e.message}); writing generic shells only`); }

const generic = { title: NAME, description: 'An archive of every post, reel, story and highlight, each one described.', url: SITE + '/' };
page('404.html', { ...generic, url: '' }, `<h1>${NAME}</h1><p>Loading…</p>`);
let count = 1;

if (!data) {
  page('index.html', generic, `<h1>${NAME}</h1>`);
} else {
  const { profile, highlights, categories, items } = data;
  const catName = Object.fromEntries(categories.map((c) => [c.slug, c.name]));
  const desc = `The archive of @${profile.username}${profile.full_name ? ` (${profile.full_name})` : ''}: every post, reel, story and highlight, described.`;
  page('index.html', { ...generic, description: desc, image: profile.avatar },
    `<h1>${esc(profile.full_name || profile.username)}</h1><p>${esc(profile.bio || '')}</p>` +
    `<h2>Highlights</h2><ul>${highlights.map((h) => `<li><a href="/highlight/${encodeURIComponent(h.id)}">${esc(h.title)}</a></li>`).join('')}</ul>` +
    `<h2>Categories</h2><ul>${categories.map((c) => `<li><a href="/category/${encodeURIComponent(c.slug)}">${esc(c.name)}</a></li>`).join('')}</ul>` +
    `<h2>Latest</h2><ul>${items.slice(0, 60).map(itemLink).join('')}</ul>`);

  for (const it of items) {
    const url = `${SITE}/item/${encodeURIComponent(it.id)}`;
    const m0 = it.media?.[0] || it.repost_of?.media?.[0];
    const a = it.analysis || {};
    const by = it.repost_of ? ` Sharing a ${it.repost_of.source_url?.includes('/reel/') ? 'reel' : 'post'} by @${it.repost_of.author}.` : '';
    const description = clip((it.description || it.summary || it.caption || a.what || '') + (it.description ? '' : by) + ` ${KIND[it.kind] || ''}, ${day(it.taken_at)}.`, 280);
    page(`item/${encodeURIComponent(it.id)}/index.html`,
      { title: titleOf(it), description, image: coverOf(it), url, type: 'article', video: m0?.type === 'video' ? m0 : null },
      `<article><h1>${esc(titleOf(it))}</h1><p><time datetime="${esc(it.taken_at)}">${day(it.taken_at)}</time> · ${esc(KIND[it.kind] || '')}</p>` +
      (coverOf(it) ? `<img src="${esc(coverOf(it))}" alt="${esc(clip(it.alt_text || a.what || it.summary || '', 300))}" width="360">` : '') +
      (it.description ? `<p>${esc(it.description)}</p>` : '') + (it.caption ? `<p>${esc(it.caption)}</p>` : '') + (a.what ? `<p>${esc(a.what)}</p>` : '') +
      (it.repost_of ? `<p>Original by <a href="${esc(it.repost_of.source_url || `https://www.instagram.com/${it.repost_of.author}/`)}">@${esc(it.repost_of.author)}</a></p>` : '') +
      ((it.categories || []).length ? `<p>${it.categories.map((c) => `<a href="/category/${encodeURIComponent(c)}">${esc(catName[c] || c)}</a>`).join(' · ')}</p>` : '') +
      `<p><a href="/">${NAME}</a></p></article>`);
    count++;
  }

  const byId = new Map(items.map((i) => [i.id, i]));
  for (const h of highlights) {
    const first = byId.get(h.item_ids[0]);
    const n = h.item_ids.length;
    page(`highlight/${encodeURIComponent(h.id)}/index.html`,
      { title: `${h.title} — highlight`, description: `The “${h.title}” highlight of @${profile.username}: ${n} stor${n === 1 ? 'y' : 'ies'}.`, image: h.cover || (first && coverOf(first)), url: `${SITE}/highlight/${encodeURIComponent(h.id)}` },
      `<h1>${esc(h.title)}</h1><ul>${h.item_ids.map((id) => byId.get(id)).filter(Boolean).map(itemLink).join('')}</ul>`);
    count++;
  }

  for (const c of categories) {
    const list = items.filter((i) => (i.categories || []).includes(c.slug));
    page(`category/${encodeURIComponent(c.slug)}/index.html`,
      { title: c.name, description: clip(c.description || `Everything in ${c.name}.`) + ` ${c.count ?? list.length} items.`, image: list[0] && coverOf(list[0]), url: `${SITE}/category/${encodeURIComponent(c.slug)}` },
      `<h1>${esc(c.name)}</h1><p>${esc(c.description || '')}</p><ul>${list.slice(0, 60).map(itemLink).join('')}</ul>`);
    count++;
  }

  page('monitor/index.html', { title: 'Monitor', description: 'Videos from official accounts that mention the watched phrases, by confidence.', url: `${SITE}/monitor`, image: profile.avatar }, '<h1>Monitor</h1>');
  page('status/index.html', { title: 'Status', description: 'Live activity and health of the archive’s parts.', url: `${SITE}/status`, image: profile.avatar }, '<h1>Status</h1>');
  count += 2;
  const urls = ['/', '/monitor', ...categories.map((c) => `/category/${encodeURIComponent(c.slug)}`), ...highlights.map((h) => `/highlight/${encodeURIComponent(h.id)}`), ...items.map((i) => `/item/${encodeURIComponent(i.id)}`)];
  writeFileSync(join(DIST, 'sitemap.xml'), `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.map((u) => `<url><loc>${esc(SITE + u)}</loc></url>`).join('\n')}\n</urlset>\n`);
}
writeFileSync(join(DIST, 'robots.txt'), `User-agent: *\nAllow: /\n${data ? `Sitemap: ${SITE}/sitemap.xml\n` : ''}`);
// App links: the apps' own files, served at /.well-known/ (see README for the CloudFront side).
mkdirSync(join(DIST, '.well-known'), { recursive: true });
// The repository root: web/.. here, or EE_REPO_ROOT / the box checkout when web/ is built from a copy.
const REPO = [process.env.EE_REPO_ROOT, join(ROOT, '..'), '/opt/earth-empire/repo'].find((d) => d && existsSync(join(d, 'ios'))) || join(ROOT, '..');
const AASA = join(REPO, 'ios/AppSiteAssociation/apple-app-site-association');
if (existsSync(AASA)) { JSON.parse(readFileSync(AASA, 'utf8')); copyFileSync(AASA, join(DIST, '.well-known/apple-app-site-association')); }
else console.warn('prerender: no ios/AppSiteAssociation/apple-app-site-association');
const findAssetLinks = (dir, depth = 0) => {
  if (!existsSync(dir) || depth > 4) return null;
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'build' || e.name.startsWith('.')) continue;
    const p = join(dir, e.name);
    if (e.isFile() && e.name === 'assetlinks.json') return p;
    if (e.isDirectory()) { const f = findAssetLinks(p, depth + 1); if (f) return f; }
  }
  return null;
};
const ASSETLINKS = findAssetLinks(join(REPO, 'android'));
if (ASSETLINKS) { JSON.parse(readFileSync(ASSETLINKS, 'utf8')); copyFileSync(ASSETLINKS, join(DIST, '.well-known/assetlinks.json')); }
else console.warn('prerender: no assetlinks.json under android/ yet');
console.log(`prerender: ${count} pages from ${API === 'mock' ? 'the mock fixture' : API}, site ${SITE}`);
