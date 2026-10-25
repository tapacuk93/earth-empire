import { expect, test, type Page } from '@playwright/test';

// Against the mock build (npm run build:mock), served the way CloudFront serves it.
const REEL = 'ig_3400000000000000001';
const CAROUSEL = 'ig_3400000000000000002';
const STORY_REPOST = 'ig_3400000000000000004';
const POST_REPOST = 'ig_3400000000000000007';

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

const rows = (page: Page) => page.locator('.feed .tl-row');
const feed = (page: Page) => page.getByRole('dialog', { name: /item \d+ of \d+/ });

test('home: infographics, not a profile; no sideways scroll; every image described', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Earth Empire, in data');
  await expect(page.locator('.hero .kpi').first()).toContainText('28');
  for (const name of ['About the owner', 'Everything else', 'Timeline', 'Places', 'Themes', 'Everything, by date']) {
    await expect(page.getByRole('region', { name, exact: true })).toBeVisible();
  }
  // No profile header, follower counts, highlight bubbles or square grid.
  await expect(page.getByText(/\d+\s+followers/)).toHaveCount(0);
  await expect(page.locator('.hl-row, .grid .tile, .profile')).toHaveCount(0);
  await expect(page.getByRole('list', { name: 'Months' }).or(page.locator('.band li'))).not.toHaveCount(0);
  await noHorizontalScroll(page);
  expect(await page.locator('img:not([alt])').count()).toBe(0);
  expect(errors).toEqual([]);
});

test('home: sections as panels with counts, people, places, moments and media', async ({ page }) => {
  await page.goto('/');
  const ded = page.getByRole('region', { name: 'About the owner' });
  const com = page.getByRole('region', { name: 'Everything else' });
  expect((await ded.boundingBox())!.y).toBeLessThan((await com.boundingBox())!.y);
  await expect(ded.locator('.kpi').first()).toContainText('2');
  await expect(ded.getByRole('link', { name: /^Travel/ })).toHaveAttribute('href', '/highlight/hl_9001');
  await expect(ded.getByRole('link', { name: /Dunas Altas/ }).first()).toBeVisible();
  await expect(ded.getByRole('list', { name: 'Media: About the owner' }).locator('li')).toHaveCount(2);
  await expect(ded.getByRole('button', { name: /Fullscreen: City council/ })).toBeVisible();
  await expect(com.getByRole('button', { name: /Fullscreen: Regional news/ })).toBeVisible();
  await expect(com.getByRole('link', { name: /^Food/ })).toBeVisible();
});

test('home: timeline, map and themes pick a context and show its items', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /^Sep 2026: \d+ items?$/ }).click();
  await expect(page).toHaveURL(/m=2026-09/);
  const sel = page.getByRole('region', { name: 'Timeline' }).locator('.selection');
  await expect(sel).toContainText('Sep 2026');
  await expect(sel.locator('.strip li')).not.toHaveCount(0);
  await page.getByRole('region', { name: 'Places' }).getByRole('button', { name: /^Cape Lumen Lighthouse.*: 1$/ }).click();
  await expect(page.getByRole('region', { name: 'Places' }).locator('.selection')).toContainText('1 item');
  const theme = page.getByRole('region', { name: 'Themes' });
  const big = theme.getByRole('button', { name: /^calm, mood, 19 items$/ });
  const small = theme.getByRole('button', { name: /^@mira\.sails, person, 1 item$/ });
  const area = async (l: typeof big) => { const b = (await l.boundingBox())!; return b.width * b.height; };
  expect(await area(big)).toBeGreaterThan(await area(small));
  await small.click();
  await expect(page).toHaveURL(/t=%40mira\.sails/);
  await theme.locator('.selection').getByRole('link', { name: 'Open the feed' }).click();
  await expect(feed(page)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/item/${REEL}\\?ctx=tag%3A%40mira\\.sails`));
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/t=%40mira\.sails/);
  await expect(theme.locator('.selection')).toBeVisible();
});

test('home: search and kind filter the list of everything', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'Reels' }).click();
  await expect(rows(page)).toHaveCount(2);
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'Stories' }).click();
  await expect(rows(page)).toHaveCount(4);
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'All' }).click();
  const box = page.getByRole('searchbox');
  await box.fill('lighthouse');
  await expect(page).toHaveURL(/q=lighthouse/);
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toHaveAttribute('href', `/item/${REEL}?ctx=q%3Alighthouse`);
  await box.fill('zzzz-nothing');
  await box.press('Enter');
  await expect(page.locator('.empty')).toContainText('Nothing matches');
});

test('search from a deep link and from a hashtag', async ({ page }) => {
  await page.goto('/?q=%23recipe');
  await expect(page.getByRole('searchbox')).toHaveValue('#recipe');
  await expect(rows(page)).toHaveCount(1);
});

test('feed: one item per screen, arrows move through the context, the URL follows, close returns', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('region', { name: 'Everything, by date' }).scrollIntoViewIfNeeded();
  const y = await page.evaluate(() => scrollY);
  await rows(page).nth(1).click();
  const f = feed(page);
  await expect(f).toBeVisible();
  await expect(f).toHaveAccessibleName('Everything: item 2 of 28');
  await expect(page).toHaveURL(new RegExp(`/item/${CAROUSEL}$`));
  await page.keyboard.press('ArrowDown');
  await expect(f).toHaveAccessibleName('Everything: item 3 of 28');
  await expect(page).toHaveURL(/\/item\/ig_3400000000000000003$/);
  await expect(page).toHaveTitle(/dunes/);
  await page.keyboard.press('ArrowUp');
  await expect(f).toHaveAccessibleName('Everything: item 2 of 28');
  await page.getByRole('button', { name: 'Close' }).click();
  await expect(f).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(y - 200);
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
  expect(await video.evaluate((v: HTMLVideoElement) => v.muted)).toBe(true);
  await slide.getByRole('button', { name: 'More' }).click();
  const sheet = slide.getByRole('region', { name: 'What’s in it' });
  await expect(sheet.getByText('named from a mention')).toBeVisible();
  await expect(sheet.getByRole('heading', { name: /Transcript/ })).toBeVisible();
  await expect(slide.getByRole('link', { name: 'Cape Lumen Lighthouse' })).toBeVisible();
  const playable = await video.evaluate((v: HTMLVideoElement) => v.canPlayType('video/mp4; codecs="avc1.4D401E, mp4a.40.2"') !== '');
  await sheet.getByRole('button', { name: /0:03\s*The lighthouse comes into view/ }).click();
  if (playable) await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 8000 }).toBeGreaterThan(2.9);
  await page.getByRole('button', { name: 'Unmute', exact: true }).click();
  expect(await video.evaluate((v: HTMLVideoElement) => v.muted)).toBe(false);
  await noHorizontalScroll(page);
});

test('feed: carousels swipe sideways; reposts credit the original', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`/item/${CAROUSEL}`);
  const slide = feed(page).locator('.islide[data-i="1"]');
  await expect(slide.locator('.idots span')).toHaveCount(3);
  await slide.locator('.imedia').evaluate((el) => el.scrollTo({ left: el.clientWidth * 2 }));
  await expect(slide.locator('.idots span').nth(2)).toHaveClass('on');
  await page.goto(`/item/${STORY_REPOST}`);
  const r = feed(page).locator('.islide[data-i="3"]');
  await expect(r.locator('.imeta')).toContainText('Reel by @oceanlab');
  await expect(r.getByRole('link', { name: '@oceanlab' })).toHaveAttribute('href', 'https://www.instagram.com/reel/DMockOrig1/');
  await page.goto(`/item/${POST_REPOST}`);
  await expect(feed(page).locator('.islide[data-i="6"] .imeta')).toContainText('Post by @mountainclub');
});

test('feed: a highlight context from a section panel opens the story viewer', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('region', { name: 'About the owner' }).getByRole('link', { name: /^Travel/ }).click();
  await expect(page.getByRole('region', { name: 'Highlight: Travel' })).toBeVisible();
});

test('highlight: story viewer with progress bars, taps, keys and close', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('region', { name: 'About the owner' }).getByRole('link', { name: /^Travel/ }).click();
  const viewer = page.getByRole('region', { name: 'Highlight: Travel' });
  await expect(viewer).toBeVisible();
  await expect(viewer.locator('.bar')).toHaveCount(2);
  await expect(viewer.getByRole('status')).toContainText('Story 1 of 2');
  await expect.poll(() => viewer.locator('.bar').first().locator('.bar-fill').evaluate((e) => getComputedStyle(e).transform), { timeout: 4000 }).not.toBe('matrix(0, 0, 0, 1, 0, 0)');
  await page.keyboard.press(' ');
  await expect(viewer.getByRole('button', { name: 'Play' })).toBeVisible();
  const box = (await viewer.locator('.story-stage').boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.8, box.y + box.height * 0.5);
  await expect(viewer.getByRole('status')).toContainText('Story 2 of 2');
  await page.keyboard.press('ArrowLeft');
  await expect(viewer.getByRole('status')).toContainText('Story 1 of 2');
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/$/);
});

test('highlight: images advance on their own, then the next highlight', async ({ page }) => {
  await page.goto('/highlight/hl_9002?item=ig_3400000000000000010');
  await expect(page.getByRole('status')).toContainText('Story 2 of 2');
  await page.waitForTimeout(5600);
  await expect(page).toHaveURL(/\/highlight\/hl_9003/);
});

test('category page as a panel', async ({ page }) => {
  await page.goto('/category/food');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Food');
  await expect(page.locator('.hero .kpi').first()).toContainText('4');
  await expect(rows(page)).toHaveCount(4);
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'Reels' }).click();
  await expect(rows(page)).toHaveCount(1);
  await noHorizontalScroll(page);
});

test('share tags are in the HTML of every main route', async ({ request }) => {
  for (const path of ['/', `/item/${REEL}`, '/highlight/hl_9001', '/category/travel']) {
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

test('keyboard: skip link and visible focus', async ({ page, browserName }) => {
  await page.goto('/');
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to content' });
  if (browserName !== 'webkit') await expect(skip).toBeFocused(); // Safari skips links on Tab by default
  await page.getByRole('searchbox').focus();
  const outline = await page.locator('.search').evaluate((e) => getComputedStyle(e).boxShadow);
  expect(outline).not.toBe('none');
});

test('reduced motion is respected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const d = await page.locator('.cell').first().evaluate((e) => getComputedStyle(e).transitionDuration);
  expect(parseFloat(d)).toBeLessThan(0.01);
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
  test('opens the same page in the app, falls back to the store, and can be dismissed for good', async ({ page }) => {
    await page.goto('/item/ig_3400000000000000001');
    const banner = page.getByRole('complementary', { name: 'Open in the app' });
    await expect(banner).toBeVisible();
    const href = await banner.getByRole('link', { name: 'Open' }).getAttribute('href');
    expect(href).toMatch(/^intent:\/\/[^/]+\/item\/ig_3400000000000000001#Intent;scheme=https;package=com\.oeaio\.earthempire;S\.browser_fallback_url=https%3A%2F%2Fplay\.google\.com/);
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
    await page.goto('/category/food');
    const open = page.getByRole('complementary', { name: 'Open in the app' }).getByRole('link', { name: 'Open' });
    await expect(open).toHaveAttribute('href', 'earthempire://category/food');
  });
});

async function signIn(page: Page) {
  await page.goto('/settings');
  await page.locator('#admin-token').fill('owner');
  await page.getByRole('button', { name: 'Check and keep' }).click();
  await expect(page.getByText('Signed in as the owner on this device.')).toBeVisible();
}

test('visitors see only Home; the owner link signs in', async ({ page, request }) => {
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
  // A wrong token is refused.
  await page.goto('/');
  await page.getByRole('link', { name: 'Owner sign-in' }).click();
  await page.locator('#admin-token').fill('nope');
  await page.getByRole('button', { name: 'Check and keep' }).click();
  await expect(page.getByText('That token was not accepted.')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(0);
});

test('owner: four sections in the header, sign out hides them', async ({ page }) => {
  await signIn(page);
  const nav = page.getByRole('navigation', { name: 'Sections' });
  await expect(nav.getByRole('link')).toHaveText(['Home', 'Detected', 'Status', 'Settings']);
  await nav.getByRole('link', { name: 'Detected' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Detected' })).toBeVisible();
  await nav.getByRole('link', { name: 'Status' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Status' })).toBeVisible();
  await noHorizontalScroll(page);
  await nav.getByRole('link', { name: 'Settings' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(0);
});

test('detected: by confidence, labels, publish to Home, fetch more, fullscreen', async ({ page }) => {
  await signIn(page);
  await page.goto('/detected');
  const cards = page.locator('.mon-card');
  await expect(cards).toHaveCount(4);
  await expect(cards.first()).toContainText('likely · 94%');
  await expect(cards.nth(3)).toContainText('low confidence · 32%');
  await expect(cards.nth(3)).toContainText('Russian speech');
  await page.getByRole('group', { name: 'Kind of hit' }).getByRole('button', { name: 'Language' }).click();
  await expect(cards).toHaveCount(1);
  await page.getByRole('group', { name: 'Kind of hit' }).getByRole('button', { name: 'All' }).click();
  await expect(cards).toHaveCount(4);
  await cards.nth(2).getByRole('button', { name: /Publish to Home/ }).click();
  await expect(cards.nth(2)).toContainText('On Home');
  await page.getByLabel('Scan more videos').fill('12');
  await page.getByRole('button', { name: 'Fetch 12 more' }).click();
  await expect(page.getByText(/Queued 7 videos to scan; 5 more to discover/)).toBeVisible();
  await page.getByRole('button', { name: 'Fullscreen', exact: true }).click();
  const dlg = page.getByRole('dialog', { name: 'Detected' });
  await expect(dlg).toContainText('1/4');
  await dlg.locator('.vfeed-list').focus();
  await page.keyboard.press('ArrowDown');
  await expect(dlg).toContainText('2/4');
  await page.keyboard.press('Escape');
  await expect(dlg).toHaveCount(0);
  await noHorizontalScroll(page);
});

test('home: published hits play in the fullscreen mode', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Fullscreen: City council/ }).click();
  const dlg = page.getByRole('dialog', { name: 'Detected and published' });
  await expect(dlg).toBeVisible();
  await expect(dlg.locator('.vfeed-slide')).toHaveCount(2);
  await expect(dlg).toContainText('Тарас Маслов');
  await page.getByRole('button', { name: 'Close' }).click();
  await expect(dlg).toHaveCount(0);
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

test('detected: the suggested section and reason; + publishes into the chosen section', async ({ page }) => {
  await signIn(page);
  await page.goto('/detected');
  const card = page.locator('.mon-card').nth(2);
  await expect(card).toContainText('Suggested section: About the owner');
  await expect(card).toContainText('cooking segment like the owner');
  const pick = card.getByLabel('Section for this hit');
  await expect(pick).toHaveValue('dedicated');
  await pick.selectOption('common');
  await card.getByRole('button', { name: /Publish to Home in Everything else/ }).click();
  await expect(card).toContainText('On Home · Everything else');
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
