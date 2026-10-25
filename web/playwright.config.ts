import { defineConfig, devices } from '@playwright/test';

// Every browser engine at every target size. EE_BROWSERS=chromium,webkit limits the engines.
const VIEWPORTS = [
  { name: 'phone-360', width: 360, height: 740, touch: true },
  { name: 'phone-390', width: 390, height: 844, touch: true },
  { name: 'tablet-768', width: 768, height: 1024, touch: true },
  { name: 'desktop-1280', width: 1280, height: 800, touch: false },
  { name: 'wide-1920', width: 1920, height: 1080, touch: false },
];
const BROWSERS = (process.env.EE_BROWSERS || 'chromium,firefox,webkit').split(',');
const DEVICE = { chromium: devices['Desktop Chrome'], firefox: devices['Desktop Firefox'], webkit: devices['Desktop Safari'] } as const;
const PORT = Number(process.env.PORT || 4174);

export default defineConfig({
  testDir: 'tests',
  fullyParallel: true,
  workers: Number(process.env.WORKERS || 3),
  retries: 1,
  reporter: [['list']],
  timeout: 30_000,
  use: { baseURL: process.env.BASE_URL || `http://localhost:${PORT}`, trace: 'retain-on-failure' },
  webServer: process.env.BASE_URL ? undefined : {
    command: `npm run build:mock && node scripts/serve.mjs ${PORT}`,
    url: `http://localhost:${PORT}/`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: BROWSERS.flatMap((b) => VIEWPORTS.map((v) => ({
    name: `${b}-${v.name}`,
    use: {
      ...DEVICE[b as keyof typeof DEVICE],
      browserName: b as 'chromium' | 'firefox' | 'webkit',
      viewport: { width: v.width, height: v.height },
      hasTouch: v.touch,
      isMobile: b === 'chromium' && v.width < 700 ? true : undefined,
    },
  }))),
});
