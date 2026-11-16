import { useEffect, useRef } from 'preact/hooks';
import { drawEarth } from '../earth';

/** The Earth now, facing the viewer's place (see earth.ts). Still: it appears once drawn and never moves. */
export function LiveEarth({ size = 640 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const px = Math.min(size, c.parentElement?.clientWidth || size);
    drawEarth(c, px).then(() => c.classList.add('drawn')).catch(() => { /* the maps did not load: nothing */ });
  }, [size]);
  return (
    <span class="live-earth">
      <canvas ref={ref} aria-hidden="true" />
    </span>
  );
}

/**
 * Space behind the Earth: a black sky with stars, whatever the theme. Most stars are faint and
 * tiny, a few bright, some slightly blue or warm - as the sky looks. While it is shown the
 * browser's bars are black too (theme-color), so the page does not frame space in white.
 */
export function Space() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    const w = window.innerWidth, h = window.innerHeight;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const g = c.getContext('2d');
    if (g) {
      g.scale(dpr, dpr);
      g.fillStyle = '#000';
      g.fillRect(0, 0, w, h);
      const n = Math.round((w * h) / 2600);
      for (let i = 0; i < n; i++) {
        const m = Math.random() ** 3;                 // brightness: mostly faint, a few bright
        const r = 0.25 + m * 1.1;
        const tint = Math.random();
        const [cr, cg, cb] = tint < 0.15 ? [190, 210, 255] : tint > 0.9 ? [255, 228, 200] : [255, 255, 255];
        g.fillStyle = `rgba(${cr},${cg},${cb},${(0.25 + m * 0.75).toFixed(3)})`;
        g.beginPath();
        g.arc(Math.random() * w, Math.random() * h, r, 0, Math.PI * 2);
        g.fill();
      }
    }
    const metas = [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')];
    const was = metas.map((m) => m.content);
    metas.forEach((m) => { m.content = '#000000'; });
    return () => metas.forEach((m, i) => { m.content = was[i]; });
  }, []);
  return <canvas class="space" ref={ref} aria-hidden="true" />;
}
