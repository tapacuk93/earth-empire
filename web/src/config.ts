// Where the read API lives. Set VITE_API_BASE at build time, e.g. the backend's AWS hostname
// before DNS moves (VITE_API_BASE=https://xxxx.execute-api.us-east-1.amazonaws.com), or `mock`
// to use the bundled fixture in mock/fixture.json.
const raw = (import.meta.env.VITE_API_BASE as string | undefined) || 'https://api.empire.earth';
export const API_BASE = raw.replace(/\/+$/, '');
export const MOCK = API_BASE === 'mock';
export const SITE_NAME = 'Earth Empire';

// The apps. Store links are placeholders until the listings exist; set them at build time.
export const ANDROID_PACKAGE = 'com.oeaio.earthempire';
export const APP_SCHEME = 'earthempire';
/** Numeric App Store id; with it, Safari shows its own Smart App Banner (apple-itunes-app). */
export const IOS_APP_ID = (import.meta.env.VITE_IOS_APP_ID as string | undefined) || '';
export const APP_STORE_URL = (import.meta.env.VITE_APP_STORE_URL as string | undefined)
  || (IOS_APP_ID ? `https://apps.apple.com/app/id${IOS_APP_ID}` : '');
export const PLAY_STORE_URL = (import.meta.env.VITE_PLAY_STORE_URL as string | undefined)
  || `https://play.google.com/store/apps/details?id=${ANDROID_PACKAGE}`;
