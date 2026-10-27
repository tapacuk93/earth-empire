// The Earth as it is now: NASA's day and night maps (public/earth/), drawn as a globe facing the
// viewer's place, lit by the Sun for the current time (city lights on the night side). Still: drawn
// once, no motion. The place is guessed in the browser from its time zone, never sent anywhere.

const ZONES: Record<string, [number, number]> = {
  'Europe/Kyiv': [50.45, 30.52], 'Europe/Kiev': [50.45, 30.52], 'Europe/Moscow': [55.75, 37.62], 'Europe/Minsk': [53.9, 27.56],
  'Europe/Warsaw': [52.23, 21.01], 'Europe/Berlin': [52.52, 13.4], 'Europe/Paris': [48.86, 2.35], 'Europe/London': [51.51, -0.13],
  'Europe/Madrid': [40.42, -3.7], 'Europe/Rome': [41.9, 12.5], 'Europe/Vienna': [48.21, 16.37], 'Europe/Prague': [50.08, 14.44],
  'Europe/Budapest': [47.5, 19.04], 'Europe/Bucharest': [44.43, 26.1], 'Europe/Sofia': [42.7, 23.32], 'Europe/Athens': [37.98, 23.73],
  'Europe/Istanbul': [41.01, 28.98], 'Europe/Helsinki': [60.17, 24.94], 'Europe/Stockholm': [59.33, 18.07], 'Europe/Oslo': [59.91, 10.75],
  'Europe/Copenhagen': [55.68, 12.57], 'Europe/Amsterdam': [52.37, 4.9], 'Europe/Brussels': [50.85, 4.35], 'Europe/Zurich': [47.38, 8.54],
  'Europe/Lisbon': [38.72, -9.14], 'Europe/Dublin': [53.35, -6.26], 'Europe/Riga': [56.95, 24.11], 'Europe/Vilnius': [54.69, 25.28],
  'Europe/Tallinn': [59.44, 24.75], 'Europe/Chisinau': [47.01, 28.86], 'Europe/Belgrade': [44.79, 20.45], 'Europe/Zagreb': [45.81, 15.98],
  'Asia/Tbilisi': [41.72, 44.79], 'Asia/Yerevan': [40.18, 44.51], 'Asia/Baku': [40.41, 49.87], 'Asia/Almaty': [43.24, 76.89],
  'Asia/Tashkent': [41.3, 69.24], 'Asia/Dubai': [25.2, 55.27], 'Asia/Jerusalem': [31.77, 35.21], 'Asia/Tehran': [35.69, 51.39],
  'Asia/Kolkata': [28.61, 77.21], 'Asia/Shanghai': [39.9, 116.4], 'Asia/Hong_Kong': [22.32, 114.17], 'Asia/Tokyo': [35.68, 139.69],
  'Asia/Seoul': [37.57, 126.98], 'Asia/Singapore': [1.35, 103.82], 'Asia/Bangkok': [13.76, 100.5], 'Asia/Jakarta': [-6.2, 106.85],
  'Asia/Manila': [14.6, 120.98], 'Asia/Karachi': [24.86, 67.0], 'Asia/Riyadh': [24.71, 46.68], 'Africa/Cairo': [30.04, 31.24],
  'Africa/Lagos': [6.52, 3.38], 'Africa/Johannesburg': [-26.2, 28.05], 'Africa/Nairobi': [-1.29, 36.82], 'Africa/Casablanca': [33.57, -7.59],
  'America/New_York': [40.71, -74.01], 'America/Chicago': [41.88, -87.63], 'America/Denver': [39.74, -104.99], 'America/Los_Angeles': [34.05, -118.24],
  'America/Toronto': [43.65, -79.38], 'America/Vancouver': [49.28, -123.12], 'America/Mexico_City': [19.43, -99.13], 'America/Sao_Paulo': [-23.55, -46.63],
  'America/Argentina/Buenos_Aires': [-34.6, -58.38], 'America/Bogota': [4.71, -74.07], 'America/Lima': [-12.05, -77.04], 'America/Santiago': [-33.45, -70.67],
  'Australia/Sydney': [-33.87, 151.21], 'Australia/Melbourne': [-37.81, 144.96], 'Australia/Perth': [-31.95, 115.86], 'Pacific/Auckland': [-36.85, 174.76],
};
const REGION_LAT: Record<string, number> = { Europe: 50, Asia: 30, Africa: 5, America: 25, Australia: -30, Pacific: -15, Atlantic: 30, Indian: -10 };

/** The viewer's place from the browser's time zone: its city, else the zone's offset and region. */
export function viewerPlace(now = new Date()): [number, number] {
  let tz = '';
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { /* no Intl */ }
  if (ZONES[tz]) return ZONES[tz];
  const lon = Math.max(-180, Math.min(180, -now.getTimezoneOffset() / 4));
  return [REGION_LAT[tz.split('/')[0]] ?? 30, lon];
}

/** Where the Sun is overhead now: [latitude, longitude] in degrees. */
export function subsolar(now = new Date()): [number, number] {
  const day = (Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) - Date.UTC(now.getUTCFullYear(), 0, 0)) / 864e5;
  const g = (2 * Math.PI / 365) * (day - 1 + (now.getUTCHours() - 12) / 24);
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g) + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const eot = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));   // minutes
  const utcMin = now.getUTCHours() * 60 + now.getUTCMinutes() + now.getUTCSeconds() / 60;
  let lon = -(utcMin + eot - 720) / 4;
  lon = ((lon + 540) % 360) - 180;
  return [decl * 180 / Math.PI, lon];
}

function pixels(img: HTMLImageElement): ImageData {
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const x = c.getContext('2d')!;
  x.drawImage(img, 0, 0);
  return x.getImageData(0, 0, c.width, c.height);
}

function load(src: string): Promise<HTMLImageElement> {
  return new Promise((ok, fail) => { const i = new Image(); i.decoding = 'async'; i.onload = () => ok(i); i.onerror = fail; i.src = src; });
}

let maps: Promise<[ImageData, ImageData]> | null = null;
const getMaps = () => (maps ??= Promise.all([load('/earth/day.webp'), load('/earth/night.webp')]).then(([d, n]) => [pixels(d), pixels(n)] as [ImageData, ImageData]));

/** Draw the globe into `canvas` (square, `size` CSS pixels), facing `place`, lit for `now`. */
export async function drawEarth(canvas: HTMLCanvasElement, size: number, now = new Date(), place = viewerPlace(now)): Promise<void> {
  const [day, night] = await getMaps();
  const n = Math.round(size * Math.min(2, window.devicePixelRatio || 1));
  canvas.width = canvas.height = n;
  const ctx = canvas.getContext('2d')!;
  const out = ctx.createImageData(n, n);
  const rad = Math.PI / 180;
  const [la0, lo0] = [place[0] * rad, place[1] * rad];
  const [sla, slo] = subsolar(now).map((v) => v * rad);
  const sin0 = Math.sin(la0), cos0 = Math.cos(la0), ssin = Math.sin(sla), scos = Math.cos(sla);
  const W = day.width, H = day.height, r = n / 2;
  for (let py = 0; py < n; py++) {
    const y = (r - py - 0.5) / r;
    for (let px = 0; px < n; px++) {
      const x = (px + 0.5 - r) / r;
      const rho2 = x * x + y * y;
      if (rho2 > 1) continue;
      const rho = Math.sqrt(rho2), cz = Math.sqrt(1 - rho2);   // sin c = rho, cos c = cz
      const lat = Math.asin(cz * sin0 + y * cos0);
      const lon = lo0 + Math.atan2(x, cz * cos0 - y * sin0);
      const u = ((lon / (2 * Math.PI) + 0.5) % 1 + 1) % 1;
      const v = 0.5 - lat / Math.PI;
      const ti = (Math.min(H - 1, Math.floor(v * H)) * W + Math.floor(u * W)) * 4;
      const sun = Math.sin(lat) * ssin + Math.cos(lat) * scos * Math.cos(lon - slo);
      const lit = Math.min(1, Math.max(0, (sun + 0.08) / 0.16));   // a soft terminator
      const shade = 0.35 + 0.65 * Math.sqrt(Math.max(0, sun));
      const limb = 0.75 + 0.25 * cz;
      const edge = Math.min(1, (1 - rho) * r);                         // antialiased rim
      const o = (py * n + px) * 4;
      for (let k = 0; k < 3; k++) {
        const d = day.data[ti + k] * shade, nl = night.data[ti + k] * (k === 2 ? 0.55 : 0.8) + day.data[ti + k] * 0.03;
        out.data[o + k] = Math.min(255, (lit * d + (1 - lit) * nl) * limb);
      }
      out.data[o + 3] = 255 * edge;
    }
  }
  ctx.putImageData(out, 0, 0);
}
