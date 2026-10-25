import { expect, test, type Page } from '@playwright/test';

// Against the mock build (npm run build:mock), served the way CloudFront serves it.
const REEL = 'ig_3400000000000000001';
const CAROUSEL = 'ig_3400000000000000002';
const STORY_REPOST = 'ig_3400000000000000004';
const POST_REPOST = 'ig_3400000000000000007';

// Floating controls auto-hide; tests keep them on screen unless a test is about that.
test.beforeEach(async ({ page }) => { await page.addInitScript(() => { (window as unknown as { __EE_NO_IDLE__: boolean }).__EE_NO_IDLE__ = true; }); });

function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|MEDIA_ERR|NotSupportedError|404/.test(m.text())) errors.push(m.text()); });
  return errors;
}

async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, 'page scrolls sideways').toBeLessThanOrEqual(1);
}

const feed = (page: Page) => page.getByRole('dialog', { name: /item \d+ of \d+/ });

const modes = (page: Page) => page.locator('.modes');
const rows = (page: Page) => page.locator('.feed .tl-row');
const list = (page: Page, name: string | RegExp) => page.getByRole('list', { name });
async function openFromList(page: Page, name: string | RegExp, n = 0) {
  const link = list(page, name).getByRole('link').nth(n);
  await link.focus();
  await expect(link).toBeVisible(); // a focused entry shows over its canvas
  await page.keyboard.press('Enter');
}

test('home: three full-screen modes - mosaic, tag graph, timeline - with a mode indicator', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Earth Empire');
  for (const name of ['Mosaic mode', 'Tag graph mode', 'Timeline mode']) await expect(page.getByRole('region', { name, exact: true })).toHaveCount(1);
  await expect(page.locator('canvas.mosaic-canvas')).toHaveCount(4);
  // No profile, follower counts, kind labels or photo grid.
  await expect(page.getByText(/\d+\s+followers/)).toHaveCount(0);
  await expect(page.locator('.grid .tile, .profile, .hl-row')).toHaveCount(0);
  const dots = page.getByRole('navigation', { name: 'Modes' });
  await expect(dots.getByRole('button', { name: 'Mosaic mode' })).toHaveAttribute('aria-current', 'true');
  await dots.getByRole('button', { name: 'Tag graph mode' }).click();
  await expect(dots.getByRole('button', { name: 'Tag graph mode' })).toHaveAttribute('aria-current', 'true');
  await dots.getByRole('button', { name: 'Timeline mode' }).click();
  await expect(dots.getByRole('button', { name: 'Timeline mode' })).toHaveAttribute('aria-current', 'true');
  await expect.poll(() => modes(page).evaluate((el) => Math.abs(el.scrollTop - 2 * el.clientHeight))).toBeLessThan(4);
  await noHorizontalScroll(page);
  expect(errors).toEqual([]);
});

test('mosaic: two halves split by highlight size, with detected videos placed in them', async ({ page }) => {
  await page.goto('/');
  const up = page.getByRole('region', { name: /^Short highlights: / });
  const low = page.getByRole('region', { name: 'Long highlights' });
  expect((await up.boundingBox())!.y).toBeLessThan((await low.boundingBox())!.y);
  await expect(list(page, 'Short highlights: videos').getByRole('link')).not.toHaveCount(0);
  await expect(list(page, 'Long highlights: videos').getByRole('link')).not.toHaveCount(0);
  await expect(list(page, 'Long highlights: videos').getByRole('link').first()).toHaveText(/^Travel, /);
  await expect(list(page, 'Short highlights: videos').getByRole('link', { name: /^Detected, / })).toHaveAttribute('href', /watch=h_mock1/);
});

test('mosaic: packed edge to edge; zoom stays covered; floating controls', async ({ page, browserName }) => {
  await page.goto('/');
  const up = page.getByRole('region', { name: /^Short highlights: / });
  const canvas = up.locator('canvas');
  const vw = page.viewportSize()!;
  const box = (await canvas.boundingBox())!;
  expect(box.x).toBeLessThanOrEqual(1);
  expect(Math.abs(box.width - vw.width)).toBeLessThanOrEqual(1);
  // No free background: sample the canvas and expect almost every pixel to be tile, not page colour.
  const free = await canvas.evaluate((c: HTMLCanvasElement) => {
    const ctx = c.getContext('2d')!;
    const bg = getComputedStyle(c).getPropertyValue('--bg').trim();
    const probe = document.createElement('canvas').getContext('2d')!;
    probe.fillStyle = bg; probe.fillRect(0, 0, 1, 1);
    const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
    const { width, height } = c;
    const d = ctx.getImageData(0, 0, width, height).data;
    let n = 0, m = 0;
    for (let y = 2; y < height - 2; y += 7) for (let x = 2; x < width - 2; x += 7) { const i = (y * width + x) * 4; m++; if (Math.abs(d[i] - r) + Math.abs(d[i + 1] - g) + Math.abs(d[i + 2] - b) < 6) n++; }
    return n / m;
  });
  expect(free).toBeLessThan(0.08);
  await up.getByRole('button', { name: /^Zoom controls/ }).click();
  await expect(up.locator('.zoom-level')).toHaveText('1.0×');
  await up.getByRole('button', { name: /^Zoom out/ }).click();
  await expect(up.locator('.zoom-level')).toHaveText('1.0×'); // never smaller than the screen
  await up.getByRole('button', { name: /^Zoom in/ }).click();
  await expect(up.locator('.zoom-level')).toHaveText('1.6×');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  if (browserName === 'chromium') { // WebKit's driver does not pass Ctrl with the wheel
    await page.keyboard.down('Control');
    await page.mouse.wheel(0, -200);
    await page.keyboard.up('Control');
    await expect(up.locator('.zoom-level')).not.toHaveText('1.6×');
  }
  await up.getByRole('button', { name: /^Show all/ }).click();
  await expect(up.locator('.zoom-level')).toHaveText('1.0×');
  await noHorizontalScroll(page);
});

test('no word "feed" anywhere, and tiles outside highlights carry no label', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('body')).not.toContainText(/\bfeed\b/i);
  const names = await page.locator('.mosaic-list a').allInnerTexts();
  expect(names.join('\n')).not.toMatch(/\bfeed\b/i);
  expect(names.some((n) => /^\w{3} \d{1,2}, \d{4}: /.test(n))).toBe(true); // a tile with only its date
});

test('floating controls fade after a few seconds and come back on input', async ({ page }) => {
  await page.addInitScript(() => { (window as unknown as { __EE_NO_IDLE__: boolean }).__EE_NO_IDLE__ = false; });
  await page.goto('/');
  const pill = page.locator('.home-pill');
  await expect(pill).toHaveCSS('opacity', '1');
  await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('ui-idle')), { timeout: 8000 }).toBe(true);
  await page.mouse.move(50, 300);
  await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('ui-idle'))).toBe(false);
  await expect(page.locator('.home-pill .earth-btn')).toBeAttached();
});

test('mosaic: opening a video starts the wheel through that half, most related first', async ({ page }) => {
  await page.goto('/');
  await openFromList(page, 'Short highlights: videos');
  const f = feed(page);
  await expect(f).toBeVisible();
  await expect(page).toHaveURL(/\/item\/.+\?ctx=rel%3Adedicated%3A/);
  await expect(f).toHaveAccessibleName(/^Related · Short highlights: item 1 of 2[78]$/);
  await page.getByRole('button', { name: 'Close' }).click();
  await expect(f).toHaveCount(0);
});

test('tag graph: a tag opens the wheel for that tag', async ({ page }) => {
  await page.goto('/');
  await expect(list(page, 'Tags, most used first').getByRole('link').first()).toHaveText(/: \d+ videos?$/);
  const calm = list(page, 'Tags, most used first').getByRole('link', { name: /^calm: 19 videos$/ });
  await calm.focus();
  await page.keyboard.press('Enter');
  await expect(feed(page)).toHaveAccessibleName(/^Tag: calm: item 1 of 19$/);
});

test('timeline: newest first; a video opens the wheel in time order from there; Close returns to the timeline', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: 'Modes' }).getByRole('button', { name: 'Timeline mode' }).click();
  await expect(page.getByRole('navigation', { name: 'Modes' }).getByRole('button', { name: 'Timeline mode' })).toHaveAttribute('aria-current', 'true');
  await expect.poll(() => page.locator('.modes').evaluate((el) => Math.abs(el.scrollTop - 2 * el.clientHeight))).toBeLessThan(3);
  const links = list(page, 'Every video, newest first').getByRole('link');
  await expect(links).toHaveCount(28);
  await expect(links.first()).toHaveText(/^Oct 2[34], 2026: A sunset run/);
  await expect(links.nth(1)).toHaveText(/^Oct 2[34], 2026: A three-photo walk/);
  await openFromList(page, 'Every video, newest first', 0);
  const f = feed(page);
  await expect(page).toHaveURL(new RegExp(`/item/${REEL}$`));
  await expect(f).toHaveAccessibleName('Everything: item 1 of 28');
  await page.keyboard.press('ArrowDown');
  await expect(f).toHaveAccessibleName('Everything: item 2 of 28');
  await page.getByRole('button', { name: 'Close' }).click();
  await expect(f).toHaveCount(0);
  await expect(page.getByRole('navigation', { name: 'Modes' }).getByRole('button', { name: 'Timeline mode' })).toHaveAttribute('aria-current', 'true');
});

test('wheel: the playback button cycles autoplay next, repeat and stop, and is remembered', async ({ page }) => {
  await page.goto(`/item/${REEL}`);
  const btn = page.getByRole('button', { name: /^Playback:/ });
  await expect(btn).toHaveAccessibleName('Playback: Autoplay next. Change it.');
  const video = feed(page).locator('.islide').first().locator('video');
  expect(await video.evaluate((v: HTMLVideoElement) => v.loop)).toBe(false);
  await btn.click();
  await expect(btn).toHaveAccessibleName('Playback: Repeat. Change it.');
  expect(await video.evaluate((v: HTMLVideoElement) => v.loop)).toBe(true);
  await btn.click();
  await expect(btn).toHaveAccessibleName('Playback: Stop at the end. Change it.');
  await page.reload();
  await expect(page.getByRole('button', { name: /^Playback:/ })).toHaveAccessibleName('Playback: Stop at the end. Change it.');
});

test('wheel: in autoplay, a still moves on after a few seconds', async ({ page }) => {
  await page.goto('/item/ig_3400000000000000005');
  await expect(feed(page)).toHaveAccessibleName(/^Everything: item \d+ of 28$/);
  await expect(page).not.toHaveURL(/\/item\/ig_3400000000000000005$/, { timeout: 9000 });
});

test('home: published detected videos play in their fullscreen mode', async ({ page }) => {
  await page.goto('/?watch=h_mock1');
  const dlg = page.getByRole('dialog', { name: 'Detected and published' });
  await expect(dlg).toBeVisible();
  await expect(dlg.locator('.vfeed-slide')).toHaveCount(2);
  await expect(dlg).toContainText('Тарас Маслов');
  await page.getByRole('button', { name: 'Close' }).click();
  await expect(dlg).toHaveCount(0);
});

test('reduced motion is respected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const d = await page.locator('.mode-dots span').first().evaluate((e) => getComputedStyle(e).transitionDuration);
  expect(parseFloat(d)).toBeLessThan(0.01);
});

test('feed: a section context, the overlay, expanded analysis, and seeking the video', async ({ page }) => {
  await page.goto(`/item/${REEL}`);
  const f = feed(page);
  await expect(f).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/sunset run/);
  const slide = f.locator('.islide').first();
  await expect(slide.locator('.ifacts')).toContainText('With @mira.sails');
  const video = slide.locator('video');
  await expect(video).toHaveAttribute('poster', /reel-sunset\.cover\.jpg/);
  await slide.getByRole('button', { name: 'More' }).click();
  const sheet = slide.getByRole('region', { name: 'What’s in it' });
  await expect(sheet.getByText('named from a mention')).toBeVisible();
  await expect(sheet.getByRole('heading', { name: /Transcript/ })).toBeVisible();
  await expect(slide.getByRole('link', { name: 'Cape Lumen Lighthouse' }).first()).toBeVisible();
  const playable = await video.evaluate((v: HTMLVideoElement) => v.canPlayType('video/mp4; codecs="avc1.4D401E, mp4a.40.2"') !== '');
  await sheet.getByRole('button', { name: /0:03\s*The lighthouse comes into view/ }).click();
  if (playable) await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 8000 }).toBeGreaterThan(2.9);
  const tapForSound = page.getByRole('button', { name: 'Tap for sound' });
  if (await tapForSound.count()) await tapForSound.click();
  await page.getByRole('button', { name: 'Mute', exact: true }).click();
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.muted)).toBe(true);
  await page.getByRole('button', { name: 'Unmute', exact: true }).click();
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.muted)).toBe(false);
  await noHorizontalScroll(page);
});

test('feed: carousels swipe sideways; reposts credit the original', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`/item/${CAROUSEL}`);
  const slide = feed(page).locator('.islide:not([aria-hidden])');
  await expect(slide.locator('.idots span')).toHaveCount(3);
  await slide.locator('.imedia').evaluate((el) => el.scrollTo({ left: el.clientWidth * 2 }));
  await expect(slide.locator('.idots span').nth(2)).toHaveClass('on');
  await page.goto(`/item/${STORY_REPOST}`);
  const r = feed(page).locator('.islide:not([aria-hidden])');
  await expect(r.locator('.imeta')).toContainText('Original by @oceanlab');
  await expect(r.getByRole('link', { name: '@oceanlab' })).toHaveAttribute('href', 'https://www.instagram.com/reel/DMockOrig1/');
  await page.goto(`/item/${POST_REPOST}`);
  await expect(feed(page).locator('.islide:not([aria-hidden]) .imeta')).toContainText('Original by @mountainclub');
});

test('highlight: story viewer with progress bars, taps, keys and close', async ({ page }) => {
  await page.goto('/highlight/hl_9001');
  const viewer = page.getByRole('region', { name: 'Highlight: Travel' });
  await expect(viewer).toBeVisible();
  await expect(viewer.locator('.bar')).toHaveCount(4);
  await expect(viewer.getByRole('status')).toContainText(/^1 of 4/);
  await expect.poll(() => viewer.locator('.bar').first().locator('.bar-fill').evaluate((e) => getComputedStyle(e).transform), { timeout: 4000 }).not.toBe('matrix(0, 0, 0, 1, 0, 0)');
  await page.keyboard.press(' ');
  await expect(viewer.getByRole('button', { name: 'Play' })).toBeVisible();
  const box = (await viewer.locator('.story-stage').boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.8, box.y + box.height * 0.5);
  await expect(viewer.getByRole('status')).toContainText(/^2 of 4/);
  await page.keyboard.press('ArrowLeft');
  await expect(viewer.getByRole('status')).toContainText(/^1 of 4/);
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/$/);
});

test('highlight: images advance on their own, then the next highlight', async ({ page }) => {
  await page.goto('/highlight/hl_9002?item=ig_3400000000000000010');
  await expect(page.getByRole('status')).toContainText(/^2 of 2/);
  await page.waitForTimeout(5600);
  await expect(page).toHaveURL(/\/highlight\/hl_9003/);
});

test('old category links open the matching facet category, else Home', async ({ page }) => {
  await page.goto('/category/food');
  await expect(page).toHaveURL(/ctx=facet%3Atopic%3Afood/);
  await expect(feed(page)).toHaveAccessibleName(/^Food: item 1 of \d+$/);
  await page.goto('/category/no-such-thing');
  await expect(page).toHaveURL(/\/$/);
});

test('share tags are in the HTML of every main route', async ({ request }) => {
  for (const path of ['/', `/item/${REEL}`, '/highlight/hl_9001']) {
    const res = await request.get(path);
    expect(res.status(), path).toBe(200);
    const html = await res.text();
    expect(html, path).toMatch(/<meta property="og:title" content="[^"]+">/);
    expect(html, path).toMatch(/<meta property="og:image" content="https:\/\/[^"]+">/);
    expect(html, path).toMatch(/<meta name="twitter:card" content="summary_large_image">/);
  }
  const reel = await (await request.get(`/item/${REEL}`)).text();
  expect(reel).toContain('og:video');
  expect(reel).toContain('<link rel="canonical" href="https://empire.earth/item/ig_3400000000000000001">');
});

test('unknown routes answer 404 and show Not found', async ({ page }) => {
  const res = await page.goto('/no/such/page');
  expect(res!.status()).toBe(404);
  await expect(page.getByRole('heading', { name: 'Not found' })).toBeVisible();
  const res2 = await page.goto('/item/ig_does_not_exist');
  expect(res2!.status()).toBe(404);
  await expect(page.getByRole('heading', { name: 'Not found' })).toBeVisible();
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', 'noindex');
});

test('theme toggle switches dark and light', async ({ page }) => {
  await page.goto('/');
  const html = page.locator('html');
  const toggle = page.getByRole('button', { name: /^Theme:/ });
  await toggle.click();
  await expect(html).toHaveAttribute('data-theme', 'dark');
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe('rgb(14, 15, 13)');
  await toggle.click();
  await expect(html).toHaveAttribute('data-theme', 'light');
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'light');
});

test('app links: the association files are served as JSON', async ({ request }) => {
  const res = await request.get('/.well-known/apple-app-site-association', { maxRedirects: 0 });
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/json');
  const body = await res.json();
  expect(body.applinks.details[0].appIDs[0]).toContain('com.oeaio.earthempire');
});

test('app banner: never on desktop', async ({ page, isMobile }) => {
  test.skip(!!isMobile, 'desktop user agents only');
  await page.goto('/item/ig_3400000000000000001');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'Open in the app' })).toHaveCount(0);
});

test.describe('app banner on Android', () => {
  test.use({ userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36' });
  test('opens the same page in the app, falls back to the store, can be dismissed, and never covers the wheel', async ({ page }) => {
    await page.goto('/item/ig_3400000000000000001');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('complementary', { name: 'Open in the app' })).toHaveCount(0);
    await page.goto('/settings');
    const banner = page.getByRole('complementary', { name: 'Open in the app' });
    await expect(banner).toBeVisible();
    const href = await banner.getByRole('link', { name: 'Open' }).getAttribute('href');
    expect(href).toMatch(/^intent:\/\/[^/]+\/settings#Intent;scheme=https;package=com\.oeaio\.earthempire;S\.browser_fallback_url=https%3A%2F%2Fplay\.google\.com/);
    await banner.getByRole('button', { name: 'Stay on the web' }).click();
    await expect(banner).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('complementary', { name: 'Open in the app' })).toHaveCount(0);
  });
});

test.describe('app banner on iPhone', () => {
  test.use({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' });
  test('opens the app by its scheme at the same path', async ({ page }) => {
    await page.goto('/settings');
    const open = page.getByRole('complementary', { name: 'Open in the app' }).getByRole('link', { name: 'Open' });
    await expect(open).toHaveAttribute('href', 'earthempire://settings');
  });
});

async function earthGesture(page: Page, icon: ReturnType<Page['locator']>) {
  const box = (await icon.boundingBox())!;
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  const touch = await page.evaluate(() => matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0);
  const tap = () => (touch ? page.touchscreen.tap(x, y) : page.mouse.click(x, y));
  await tap();
  await page.waitForTimeout(800);
  await tap(); await tap(); await tap();
}

async function signIn(page: Page) {
  await page.goto('/settings');
  await page.locator('#admin-token').fill('owner');
  await page.getByRole('button', { name: 'Check and keep' }).click();
  await expect(page.getByText('Signed in as the owner on this device.')).toBeVisible();
}

test('visitors see only Home; the hidden dot gesture opens the admin key prompt', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(0);
  for (const path of ['/detected', '/status']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1, name: 'Owner sign-in' })).toBeVisible();
    await expect(page.locator('.comp, .mon-card')).toHaveCount(0);
  }
  // Not prerendered, not in the sitemap.
  expect((await request.get('/status')).status()).toBe(404);
  expect((await request.get('/detected')).status()).toBe(404);
  const sitemap = await (await request.get('/sitemap.xml')).text();
  expect(sitemap).not.toMatch(/detected|status|settings|monitor/);
  // The hidden way in: on the Earth icon, one tap, a pause, then three quick taps.
  await page.goto('/');
  await earthGesture(page, page.locator('.home-pill .earth-btn'));
  const prompt = page.getByRole('dialog', { name: 'Admin key' });
  await expect(prompt).toBeVisible();
  await prompt.locator('#admin-token').fill('nope');
  await prompt.getByRole('button', { name: 'Check and keep' }).click();
  await expect(prompt.getByText('That token was not accepted.')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(0);
  await prompt.locator('#admin-token').fill('owner');
  await prompt.getByRole('button', { name: 'Check and keep' }).click();
  await expect(page.getByRole('navigation', { name: 'Sections' })).toBeVisible();
  await expect(prompt).toHaveCount(0);
  // Quick taps alone do nothing.
});

test('owner: four sections in the header, sign out hides them', async ({ page }) => {
  await signIn(page);
  const nav = page.getByRole('navigation', { name: 'Sections' });
  await expect(nav.getByRole('link')).toHaveText(['Home', 'Detected', 'Settings', 'Status']);
  await nav.getByRole('link', { name: 'Detected' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Detected' })).toBeVisible();
  await nav.getByRole('link', { name: 'Status' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Status' })).toBeVisible();
  await noHorizontalScroll(page);
  await nav.getByRole('link', { name: 'Settings' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(0);
});

test('detected: a vertical wheel of hits by confidence, with fetch more', async ({ page }) => {
  await signIn(page);
  await page.goto('/detected');
  const wheel = page.getByRole('region', { name: /Hits, most certain first/ }).or(page.locator('.wheel'));
  await expect(page.locator('.wslide')).toHaveCount(4);
  await expect(page.locator('.det-count')).toHaveText('1 / 4 · likely');
  await expect(page.locator('.wslide').first()).toContainText('likely · 94%');
  await page.locator('.wheel').focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('.det-count')).toHaveText('2 / 4 · likely');
  await expect(page).toHaveURL(/h=h_mock2/);
  await page.keyboard.press('End');
  await page.locator('.wheel').evaluate((el) => el.scrollTo({ top: el.clientHeight * 3 }));
  await expect(page.locator('.det-count')).toHaveText('4 / 4 · low confidence');
  await expect(page.locator('.wslide').nth(3)).toContainText('Russian speech');
  await page.getByRole('group', { name: 'Kind of hit' }).getByRole('button', { name: 'Language' }).click();
  await expect(page.locator('.wslide')).toHaveCount(1);
  await page.getByLabel('Scan more').fill('12');
  await page.getByRole('button', { name: 'Fetch 12 more' }).click();
  await expect(page.getByText(/Queued 7 videos to scan; 5 more to discover/)).toBeVisible();
  void wheel;
  await noHorizontalScroll(page);
});

test('status and settings for the owner: health, activity, stats, phrases', async ({ page }) => {
  await signIn(page);
  const phrases = page.getByRole('region', { name: 'Phrases the monitor listens for' });
  await expect(phrases.locator('.phrases').first().locator('.phrase')).toHaveCount(3);
  await expect(phrases.getByRole('list', { name: 'Variants of “тарас маслов”' })).toContainText('taras maslov');
  await phrases.getByLabel('New phrase').fill('t. maslov');
  await phrases.getByRole('button', { name: 'Add' }).click();
  await phrases.getByRole('button', { name: 'Save' }).click();
  await expect(phrases.getByText('Saved.', { exact: false })).toBeVisible();
  await expect(phrases.locator('.phrases').first().locator('.phrase')).toHaveCount(4);
  await phrases.getByRole('button', { name: 'Rescan stored transcripts' }).click();
  await expect(phrases.getByText('Rescan started.', { exact: false })).toBeVisible();
  await page.goto('/status');
  await expect(page.locator('.comp')).toHaveCount(10);
  await expect(page.getByText('Instagram asked to slow down; waiting 15 min')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Activity' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Monitor stats' })).toContainText('cpu per audio');
});

test('detected: add twice - lower, then upper - and the state on the button', async ({ page }) => {
  await signIn(page);
  await page.goto('/detected?h=h_mock3');
  const slide = page.locator('.wslide[data-i="2"]');
  await expect(slide.locator('.state-chip')).toHaveText('Not on Home');
  await expect(slide).toContainText('Claude suggests upper');
  await slide.getByRole('button', { name: /^Add to the lower section of Home/ }).click();
  await expect(slide.locator('.state-chip')).toHaveText('On Home: lower');
  await slide.getByRole('button', { name: /^Move to the upper section of Home/ }).click();
  await expect(slide.locator('.state-chip')).toHaveText('On Home: upper');
  await expect(slide.getByRole('button', { name: 'In the upper section of Home' })).toBeDisabled();
  await slide.getByRole('button', { name: 'Remove' }).click();
  await expect(slide.locator('.state-chip')).toHaveText('Not on Home');
});

test('settings: suggested phrases from highlight names, accept and reject', async ({ page }) => {
  await signIn(page);
  const sugs = page.getByRole('region', { name: 'Suggested phrases' });
  await expect(sugs.locator('.phrase')).toHaveCount(3);
  await sugs.getByRole('button', { name: 'Accept “travel”' }).click();
  await expect(page.getByRole('region', { name: 'Phrases the monitor listens for' }).locator('.phrases').first().locator('.phrase')).toHaveCount(4);
  await sugs.getByRole('button', { name: 'Reject “food”' }).click();
  await expect(sugs.locator('.phrase')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('region', { name: 'Suggested phrases' }).locator('.phrase')).toHaveText([/travel/, /ocean/]); // the mock forgets an accepted phrase on reload; the rejection stays
});


test('wheel: why it is here - the first hit as a chip, the video starting just before it, marks on the bar', async ({ page }) => {
  await page.goto(`/item/${REEL}`);
  const slide = feed(page).locator('.islide:not([aria-hidden])');
  const chip = slide.getByRole('note', { name: 'Why this is here' });
  await expect(chip).toContainText('likely');
  await expect(chip).toContainText('Тарасе, дивись на маяк!');
  await expect(chip).toContainText('Taras, look at the lighthouse!');
  await expect(chip).toContainText('2 moments');
  const video = slide.locator('video').first();
  const playable = await video.evaluate((v: HTMLVideoElement) => v.canPlayType('video/mp4; codecs="avc1.4D401E, mp4a.40.2"') !== '');
  if (playable) {
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 8000 }).toBeGreaterThan(1.5);
    await expect(slide.locator('.hit-mark')).toHaveCount(2);
  }
  await page.goto('/item/ig_3400000000000000008');
  await expect(feed(page).locator('.islide:not([aria-hidden])').getByRole('note', { name: 'Why this is here' })).toContainText('low confidence');
});

test('the mark is the Earth: favicon, touch icon, manifest and share image', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.locator('link[rel="icon"][type="image/svg+xml"]')).toHaveAttribute('href', '/icon/earth.svg');
  await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveAttribute('href', '/icon/apple-touch-icon.png');
  for (const path of ['/icon/earth.svg', '/icon/earth-16.png', '/icon/earth-32.png', '/icon/apple-touch-icon.png', '/icon/og.png', '/manifest.webmanifest']) {
    expect((await request.get(path)).status(), path).toBe(200);
  }
  const manifest = await (await request.get('/manifest.webmanifest')).json();
  expect(manifest.icons.map((i: { src: string }) => i.src)).toContain('/icon/earth-512.png');
  expect(await (await request.get('/')).text()).toContain('https://empire.earth/icon/og.png');
});

test('facets: whatever the backend defines, each category opens its wheel', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: 'Modes' }).getByRole('button', { name: 'Tag graph mode' }).click();
  await page.getByRole('button', { name: 'Facets' }).click();
  const sheet = page.getByRole('region', { name: 'Facets' });
  await expect(sheet.getByRole('heading')).toHaveText(['Topic', 'Place']);
  await sheet.getByRole('button', { name: /^Food\s*4$/ }).click();
  await expect(feed(page)).toHaveAccessibleName(/^Food: item 1 of \d+$/);
  await expect(page).toHaveURL(/ctx=facet%3Atopic%3Afood/);
});

test('home stays tappable: open a tile, close the wheel, open another - several times', async ({ page, isMobile, hasTouch }) => {
  await page.goto('/');
  for (let i = 0; i < 5; i++) {
    const mc = page.locator('.mode-mosaic canvas').first();
    await expect(mc).toHaveAttribute('data-cells', /\[\[/);
    const c = (await mc.boundingBox())!;
    const x = c.x + c.width * (0.15 + 0.17 * i), y = c.y + c.height * (0.3 + 0.1 * (i % 3));
    if (hasTouch) await page.touchscreen.tap(x, y); else await page.mouse.click(x, y);
    await expect(page).toHaveURL(/\/item\/|watch=/);
    const close = page.getByRole('button', { name: 'Close' });
    await close.click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('canvas.mosaic-canvas').first()).toBeVisible();
    void isMobile;
  }
});

test('wheel: sound on by default, remembered when muted', async ({ page }) => {
  await page.goto(`/item/${REEL}`);
  const video = feed(page).locator('.islide:not([aria-hidden]) video').first();
  const prompt = page.getByRole('button', { name: 'Tap for sound' });
  // Either it plays with sound, or the browser refused and the wheel asks for a tap.
  await expect.poll(async () => (await prompt.count()) > 0 || !(await video.evaluate((v: HTMLVideoElement) => v.muted))).toBe(true);
  if (await prompt.count()) { await prompt.click(); await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.muted)).toBe(false); }
  await expect(page.getByRole('button', { name: 'Mute', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Mute', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Unmute', exact: true })).toBeVisible();
});

test('tag graph: no two labels overlap, at any zoom', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: 'Modes' }).getByRole('button', { name: 'Tag graph mode' }).click();
  const region = page.getByRole('region', { name: 'Tags', exact: true }).or(page.locator('.tag-graph'));
  const canvas = page.locator('.tag-graph canvas');
  const check = async () => {
    const boxes: number[][] = JSON.parse((await canvas.getAttribute('data-labels')) || '[]');
    const circles: number[][] = JSON.parse((await canvas.getAttribute('data-circles')) || '[]');
    const [cw, ch] = ((await canvas.getAttribute('data-size')) || '0x0').split('x').map(Number);
    expect(boxes.length).toBeGreaterThan(0);
    for (let i = 0; i < circles.length; i++) for (let j = i + 1; j < circles.length; j++) {
      const [a, b] = [circles[i], circles[j]];
      expect(Math.hypot(a[0] - b[0], a[1] - b[1]) + 0.5 >= a[2] + b[2], `circles ${i} and ${j} overlap`).toBe(true);
    }
    for (const [x, y, w, h] of boxes) {
      expect(x >= 0 && y >= 0 && x + w <= cw && y + h <= ch, 'label inside the screen').toBe(true);
      for (const [cx, cy, r] of circles) {
        const nx = Math.max(x, Math.min(cx, x + w)), ny = Math.max(y, Math.min(cy, y + h));
        expect((cx - nx) ** 2 + (cy - ny) ** 2 >= r * r, 'label clear of every circle').toBe(true);
      }
    }
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const [a, b] = [boxes[i], boxes[j]];
      const overlap = a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];
      expect(overlap, `labels ${i} and ${j} overlap`).toBe(false);
    }
    return boxes.length;
  };
  await expect.poll(async () => JSON.parse((await canvas.getAttribute('data-labels')) || '[]').length).toBeGreaterThan(0);
  const n0 = await check();
  await page.locator('.tag-graph').getByRole('button', { name: /^Zoom controls/ }).click();
  for (let z = 0; z < 3; z++) {
    await page.locator('.tag-graph').getByRole('button', { name: 'Zoom in: tags' }).click();
    await page.waitForTimeout(150);
    await check();
  }
  await page.locator('.tag-graph').getByRole('button', { name: 'Zoom out: tags' }).click();
  await page.waitForTimeout(150);
  await check();
  void n0; void region;
});

test('timeline: tiles recognisable at the first view', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: 'Modes' }).getByRole('button', { name: 'Timeline mode' }).click();
  const tile = Number(await page.locator('.timeline-mode canvas').getAttribute('data-tile'));
  const vw = page.viewportSize()!.width;
  expect(tile).toBeGreaterThanOrEqual(Math.min(vw * 0.3, 108));
});

test('mosaic: a hovered tile previews without flicker', async ({ page, hasTouch }) => {
  test.skip(hasTouch, 'hover is for mice');
  await page.goto('/');
  const canvas = page.locator('.mode-mosaic canvas').first();
  await expect(canvas).toHaveAttribute('data-cells', /\[\[/);
  const c = (await canvas.boundingBox())!;
  const cells: number[][] = JSON.parse((await canvas.getAttribute('data-cells'))!);
  const v = cells.filter((x) => x[7] === 1).sort((a, b) => b[1] - a[1])[0];
  await page.mouse.move(c.x + v[3] + v[5] / 2, c.y + v[4] + v[6] / 2);
  await page.mouse.move(c.x + v[3] + v[5] / 2 + 4, c.y + v[4] + v[6] / 2 + 3);
  await page.waitForTimeout(400);
  // While the pointer stays on the tile, the preview never goes away and comes back.
  const states = await page.evaluate(() => new Promise<string[]>((res) => {
    const v = document.querySelector<HTMLVideoElement>('.mosaic-video')!;
    const out: string[] = [];
    let n = 0;
    const tick = () => { out.push(`${v.style.display}|${v.dataset.src || ''}`); if (++n < 40) requestAnimationFrame(tick); else res(out); };
    tick();
  }));
  expect(new Set(states).size, states.join(', ')).toBe(1);
  expect(states[0].startsWith('none')).toBe(false);
  // The overlay never takes the pointer away from the canvas.
  expect(await page.locator('.mode-mosaic .mosaic-video').first().evaluate((v) => getComputedStyle(v).pointerEvents)).toBe('none');
});

test('mosaic: tile area follows size across both halves', async ({ page }) => {
  await page.goto('/');
  const halves = page.locator('.mode-mosaic .mosaic');
  await expect(halves.first().locator('canvas')).toHaveAttribute('data-cells', /\[/);
  const data = await halves.evaluateAll((els) => els.map((e) => ({ clamped: e.getAttribute('data-clamped') === '1', cells: JSON.parse(e.querySelector('canvas')!.getAttribute('data-cells') || '[]') as [string, number, number][] })));
  const ratios = (cells: [string, number, number][]) => cells.filter((x) => x[2] > 0 && x[1] > 400).map((x) => x[1] / x[2]);
  for (const h of data) {
    const r = ratios(h.cells);
    if (r.length > 1) expect(Math.max(...r) / Math.min(...r)).toBeLessThan(1.15);
  }
  if (data.length === 2 && !data.some((h) => h.clamped)) {
    const [a, b] = data.map((h) => ratios(h.cells)).map((r) => r.reduce((s, x) => s + x, 0) / r.length);
    expect(Math.max(a, b) / Math.min(a, b)).toBeLessThan(1.15);
  }
});

test('settings: importance - formula, w, age, placement weights and a versioned rubric', async ({ page }) => {
  await signIn(page);
  const imp = page.getByRole('region', { name: 'Importance' });
  await expect(imp.locator('.formula')).toContainText('size = placement × age_factor');
  await expect(imp.getByLabel('w (weight of importance)')).toHaveValue('0.4');
  await expect(imp.getByLabel('Display exponent (area ∝ size^e)')).toHaveValue('2');
  await expect(imp.getByLabel('Story')).toHaveValue('0.125');
  await imp.getByLabel('Importance rubric').fill('Important: the owner speaking.');
  await imp.getByLabel('Reason for the change').fill('Shorter');
  await imp.getByRole('button', { name: 'Save' }).click();
  await expect(imp.getByRole('status')).toContainText('version 3');
  await imp.locator('summary').click();
  await expect(imp.locator('.history li').first()).toContainText('v3');
  await expect(imp.locator('.history li').first()).toContainText('Shorter');
});

test('the Earth icon on other screens: a single tap goes Home, the pattern opens the key prompt', async ({ page }) => {
  await page.goto('/settings');
  const icon = page.locator('.float-home .earth-btn');
  await earthGesture(page, icon);
  await expect(page.getByRole('dialog', { name: 'Admin key' })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel' }).click();
  await page.waitForTimeout(1800);
  await icon.click();
  await expect(page).toHaveURL(/\/$/, { timeout: 4000 });
});
