import { cpSync, createReadStream, existsSync, statSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { defineConfig, loadEnv, type Plugin } from 'vite';

const MOCK_DIR = resolve(import.meta.dirname, 'mock');
const TYPES: Record<string, string> = { '.json': 'application/json', '.jpg': 'image/jpeg', '.mp4': 'video/mp4' };

// Serves mock/ at /mock in dev, and copies it into dist only for a mock build.
function mockData(isMock: boolean): Plugin {
  return {
    name: 'ee-mock',
    configureServer(server) {
      server.middlewares.use('/mock', (req, res, next) => {
        const file = join(MOCK_DIR, decodeURIComponent((req.url || '').split('?')[0]));
        if (!file.startsWith(MOCK_DIR) || !existsSync(file) || !statSync(file).isFile()) return next();
        res.setHeader('Content-Type', TYPES[extname(file)] || 'application/octet-stream');
        createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      if (isMock) cpSync(MOCK_DIR, resolve(import.meta.dirname, 'dist/mock'), { recursive: true });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const isMock = (env.VITE_API_BASE || '') === 'mock';
  return {
    plugins: [mockData(isMock)],
    build: { target: ['es2020', 'safari14', 'firefox90', 'chrome90'], cssTarget: ['safari14', 'chrome90', 'firefox90'], assetsInlineLimit: 4096 },
  };
});
