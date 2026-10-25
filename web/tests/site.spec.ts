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

const tiles = (page: Page) => page.locator('.grid:not(.skeleton) .tile a');

test('home: profile, highlights, grid, no sideways scroll', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('earth.empire');
  await expect(page.getByRole('navigation', { name: 'Highlights' }).getByRole('link')).toHaveCount(3);
  await expect.poll(() => tiles(page).count()).toBeGreaterThanOrEqual(24);
  await noHorizontalScroll(page);
  // Every image says what it shows.
  const missingAlt = await page.locator('img:not([alt])').count();
  expect(missingAlt).toBe(0);
  // More items arrive on scroll (tall screens load them at once) or with the button.
  const more = page.getByRole('button', { name: 'Load more' });
  if (await more.isVisible()) await more.click({ timeout: 3000 }).catch(() => undefined);
  await expect(tiles(page)).toHaveCount(28);
  await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('home: kind filter, category filter and search', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'Reels' }).click();
  await expect(page).toHaveURL(/kind=reel/);
  await expect(tiles(page)).toHaveCount(2);
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'Stories' }).click();
  await expect(tiles(page)).toHaveCount(4);
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'All' }).click();
  await page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'Everything, by date' }).click();
  await page.getByRole('group', { name: 'Category' }).getByRole('button', { name: /^Food/ }).click();
  await expect(page).toHaveURL(/category=food/);
  await expect(page.locator('.tl-row')).toHaveCount(4);
  await page.getByRole('group', { name: 'Category' }).getByRole('button', { name: 'All categories' }).click();
  await page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'Tag cloud' }).click();

  const box = page.getByRole('searchbox');
  await box.fill('lighthouse');
  await expect(page).toHaveURL(/q=lighthouse/);
  await expect(tiles(page)).toHaveCount(1);
  await expect(tiles(page).first()).toHaveAttribute('href', `/item/${REEL}`);
  await box.fill('zzzz-nothing');
  await box.press('Enter');
  await expect(page.locator('.empty')).toContainText('Nothing matches');
});

test('search from a deep link and from a hashtag', async ({ page }) => {
  await page.goto('/?q=%23recipe');
  await expect(page.getByRole('searchbox')).toHaveValue('#recipe');
  await expect(tiles(page)).toHaveCount(1);
});

test('item: reel with analysis; the timeline seeks the video', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto(`/item/${REEL}`);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/sunset run/);
  await expect(page.locator('time').first()).toHaveAttribute('datetime', /2026-10-23/);
  await expect(page.getByRole('link', { name: 'Cape Lumen Lighthouse' })).toBeVisible();
  await expect(page.getByText('Golden Hour Drive — The Paper Kites (sample)')).toBeVisible();
  await expect(page.getByRole('link', { name: '@mira.sails' }).first()).toHaveAttribute('href', 'https://www.instagram.com/mira.sails/');
  await expect(page.getByText('named from a mention')).toBeVisible();
  await expect(page.getByRole('heading', { name: /Transcript/ })).toBeVisible();
  await expect(page.getByText('Day 12', { exact: false }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: 'Travel' })).toHaveAttribute('href', '/category/travel');
  const video = page.locator('.viewer video');
  await expect(video).toHaveAttribute('poster', /reel-sunset\.cover\.jpg/);
  await noHorizontalScroll(page);

  const playable = await video.evaluate((v: HTMLVideoElement) => v.canPlayType('video/mp4; codecs="avc1.4D401E, mp4a.40.2"') !== '');
  await page.getByRole('button', { name: /0:03\s*The lighthouse comes into view/ }).click();
  if (playable) {
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 8000 }).toBeGreaterThan(2.9);
  }
  expect(errors).toEqual([]);
});

test('item: carousel moves with buttons, dots and keys', async ({ page }) => {
  await page.goto(`/item/${CAROUSEL}`);
  const viewer = page.getByRole('region', { name: /Carousel media/ });
  await expect(viewer).toBeVisible();
  await expect(viewer.locator('.counter')).toHaveText('1/3');
  await viewer.getByRole('button', { name: 'Next slide' }).click();
  await expect(viewer.locator('.counter')).toHaveText('2/3');
  await viewer.getByRole('button', { name: 'Show slide 3 of 3' }).click();
  await expect(viewer.locator('.counter')).toHaveText('3/3');
  await expect(viewer.getByRole('button', { name: 'Next slide' })).toBeDisabled();
  await viewer.locator('.track').focus();
  await page.keyboard.press('ArrowLeft');
  await expect(viewer.locator('.counter')).toHaveText('2/3');
  // A swipe is a native scroll of the track.
  await viewer.locator('.track').evaluate((t) => { t.scrollTo({ left: 0 }); });
  await expect(viewer.locator('.counter')).toHaveText('1/3');
  await expect(page.getByRole('link', { name: '@leo.maps' }).first()).toBeVisible();
});

test('item: a story repost shows the original credited and linked', async ({ page }) => {
  await page.goto(`/item/${STORY_REPOST}`);
  const shared = page.locator('.pane.sharing');
  const original = page.locator('.pane.original');
  await expect(shared).toBeVisible();
  await expect(original).toBeVisible();
  await expect(original.locator('figcaption')).toContainText('Reel by @oceanlab');
  await expect(original.getByRole('link', { name: '@oceanlab' })).toHaveAttribute('href', 'https://www.instagram.com/oceanlab/');
  await expect(original.getByRole('link', { name: /View on Instagram/ })).toHaveAttribute('href', 'https://www.instagram.com/reel/DMockOrig1/');
  // Side by side when there is room, stacked when not.
  const a = await shared.boundingBox(), b = await original.boundingBox();
  const vw = page.viewportSize()!.width;
  if (vw >= 720) expect(Math.abs(a!.y - b!.y)).toBeLessThan(5);
  else expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1);
  await expect(page.locator('.details a[href^="/highlight/hl_9003"]')).toHaveText('Ocean');
  await noHorizontalScroll(page);
});

test('item: a post repost of a carousel', async ({ page }) => {
  await page.goto(`/item/${POST_REPOST}`);
  await expect(page.locator('.pane.original figcaption')).toContainText('Post by @mountainclub');
  await expect(page.locator('.pane.original .counter')).toHaveText('1/2');
});

test('highlight: story viewer with progress bars, taps, keys and close', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: 'Highlights' }).getByRole('link', { name: 'Travel' }).click();
  const viewer = page.getByRole('region', { name: 'Highlight: Travel' });
  await expect(viewer).toBeVisible();
  await expect(viewer.getByRole('heading', { name: 'Travel' })).toBeVisible();
  await expect(viewer.locator('.bar')).toHaveCount(2);
  await expect(viewer.getByRole('status')).toContainText('Story 1 of 2');
  await expect(page).toHaveURL(/item=ig_3400000000000000003/);
  // The progress bar moves.
  await expect.poll(() => viewer.locator('.bar').first().locator('.bar-fill').evaluate((e) => getComputedStyle(e).transform), { timeout: 4000 }).not.toBe('matrix(0, 0, 0, 1, 0, 0)');
  // Pause, so the image timer cannot move on by itself while we tap.
  await page.keyboard.press(' ');
  await expect(viewer.getByRole('button', { name: 'Play' })).toBeVisible();
  // Tap the right side for the next story.
  const stage = viewer.locator('.story-stage');
  const box = (await stage.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.8, box.y + box.height * 0.5);
  await expect(viewer.getByRole('status')).toContainText('Story 2 of 2');
  await page.keyboard.press('ArrowLeft');
  await expect(viewer.getByRole('status')).toContainText('Story 1 of 2');
  await page.keyboard.press(' ');
  await expect(viewer.getByRole('button', { name: 'Pause' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/$/);
  await expect(tiles(page).first()).toBeVisible();
});

test('highlight: images advance on their own, then the next highlight', async ({ page }) => {
  await page.goto('/highlight/hl_9002?item=ig_3400000000000000010');
  await expect(page.getByRole('status')).toContainText('Story 2 of 2');
  await page.waitForTimeout(5600);
  await expect(page).toHaveURL(/\/highlight\/hl_9003/);
});

test('category page', async ({ page }) => {
  await page.goto('/category/food');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Food');
  await expect(tiles(page)).toHaveCount(4);
  await page.getByRole('group', { name: 'Kind' }).getByRole('button', { name: 'Reels' }).click();
  await expect(tiles(page)).toHaveCount(1);
  await noHorizontalScroll(page);
});

test('navigation: open an item from the grid and come back', async ({ page }) => {
  await page.goto('/');
  await tiles(page).nth(1).click();
  await expect(page).toHaveURL(new RegExp(`/item/${CAROUSEL}`));
  await expect(page.getByRole('heading', { level: 1 })).toBeFocused();
  await page.getByRole('link', { name: 'Archive' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect.poll(() => tiles(page).count()).toBeGreaterThanOrEqual(24);
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
  const d = await page.locator('.tile img').first().evaluate((e) => getComputedStyle(e).transitionDuration);
  expect(parseFloat(d)).toBeLessThan(0.01);
});

test('tag cloud: sized by count, a click filters the items', async ({ page }) => {
  await page.goto('/');
  const cloud = page.getByRole('region', { name: 'Tags' });
  await expect(cloud).toBeVisible();
  const nature = cloud.getByRole('button', { name: /^Nature, category, 10 items$/ });
  const mira = cloud.getByRole('button', { name: /^@mira\.sails, person, 1 item$/ });
  await expect(nature).toBeVisible();
  const big = await nature.evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
  const small = await mira.evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
  expect(big).toBeGreaterThan(small);
  await mira.click();
  await expect(page).toHaveURL(/tag=%40mira\.sails/);
  await expect(tiles(page)).toHaveCount(1);
  await expect(tiles(page).first()).toHaveAttribute('href', `/item/${REEL}`);
  await cloud.getByRole('group', { name: 'Tag type' }).getByRole('button', { name: 'Keywords' }).click();
  await cloud.getByRole('button', { name: /^squash, keyword/ }).click();
  await expect(tiles(page)).toHaveCount(2);
  await page.getByRole('button', { name: 'Clear' }).click();
  await expect(tiles(page)).toHaveCount(24);
  await noHorizontalScroll(page);
});

test('view toggle: everything by date, remembered across visits', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'Everything, by date' }).click();
  await expect(page.getByRole('region', { name: 'Tags' })).toHaveCount(0);
  await expect(page.locator('.tl-month').first().getByRole('heading')).toHaveText('October 2026');
  const dates = await page.locator('.tl-row time').evaluateAll((ts) => ts.map((t) => t.getAttribute('datetime')!));
  expect(dates.length).toBeGreaterThan(10);
  expect([...dates].sort().reverse()).toEqual(dates);
  await page.reload();
  await expect(page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'Everything, by date' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.tl-row').first()).toBeVisible();
  await page.getByRole('group', { name: 'View' }).getByRole('button', { name: 'Tag cloud' }).click();
  await page.reload();
  await expect(page.getByRole('region', { name: 'Tags' })).toBeVisible();
});

test('video covers: the chosen frame, else the thumbnail', async ({ page }) => {
  await page.goto(`/item/${REEL}`);
  await expect(page.locator('.viewer video')).toHaveAttribute('poster', /reel-sunset\.cover\.jpg/);
  await page.goto('/item/ig_3400000000000000006');
  await expect(page.locator('.viewer video')).toHaveAttribute('poster', /story-market\.thumb\.jpg/);
  await page.goto('/?kind=reel');
  await expect(tiles(page).first().locator('img')).toHaveAttribute('src', /\.cover\.jpg/);
});
