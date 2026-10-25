// Where the read API lives. Set VITE_API_BASE at build time, e.g. the backend's AWS hostname
// before DNS moves (VITE_API_BASE=https://xxxx.execute-api.us-east-1.amazonaws.com), or `mock`
// to use the bundled fixture in mock/fixture.json.
const raw = (import.meta.env.VITE_API_BASE as string | undefined) || 'https://api.empire.earth';
export const API_BASE = raw.replace(/\/+$/, '');
export const MOCK = API_BASE === 'mock';
export const SITE_NAME = 'Earth Empire';
