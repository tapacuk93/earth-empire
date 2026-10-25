// Serves dist/ the way CloudFront is set up to (see README): /a/b → /a/b/index.html, and a miss
// returns 404.html with status 404 (the app still boots from it and renders the route).
// Supports Range requests, which Safari needs for video. Usage: node scripts/serve.mjs [port]
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const DIST = fileURLToPath(new URL('../dist/', import.meta.url));
const PORT = Number(process.argv[2] || process.env.PORT || 4173);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml',
  '.jpg': 'image/jpeg', '.png': 'image/png', '.mp4': 'video/mp4', '.xml': 'application/xml', '.txt': 'text/plain' };

// The same rewrite as the CloudFront viewer-request function.
export function rewrite(uri) {
  if (uri.endsWith('/')) return uri + 'index.html';
  if (!extname(uri.split('/').pop())) return uri + '/index.html';
  return uri;
}

const isFile = (p) => existsSync(p) && statSync(p).isFile();

createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  let rel = normalize(decodeURIComponent(rewrite(url.pathname)));
  let file = join(DIST, rel);
  let status = 200;
  if (!file.startsWith(DIST) || !isFile(file)) { file = join(DIST, '404.html'); status = 404; }
  const size = statSync(file).size;
  const type = TYPES[extname(file)] || 'application/octet-stream';
  const range = req.headers.range && /bytes=(\d*)-(\d*)/.exec(req.headers.range);
  if (range && status === 200) {
    const start = range[1] ? Number(range[1]) : size - Number(range[2]);
    const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
    res.writeHead(206, { 'Content-Type': type, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Accept-Ranges': 'bytes', 'Content-Length': end - start + 1 });
    createReadStream(file, { start, end }).pipe(res);
    return;
  }
  res.writeHead(status, { 'Content-Type': type, 'Content-Length': size, 'Accept-Ranges': 'bytes' });
  if (req.method === 'HEAD') return res.end();
  createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`serving dist on http://localhost:${PORT}`));
