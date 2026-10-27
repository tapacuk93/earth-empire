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
