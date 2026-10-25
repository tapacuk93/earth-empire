import type { Ref } from 'preact';
import { useEffect, useImperativeHandle, useRef, useState } from 'preact/hooks';
import type { Media } from '../types';
import { posterOf, prefersReducedMotion } from '../util';
import { Icon } from './icons';

export interface MediaHandle { show(i: number): void; seek(i: number, t: number): void }

interface Props { media: Media[]; alt: (i: number, m: Media) => string; label: string; eager?: boolean; handle?: Ref<MediaHandle> }

/** A swipeable carousel (native scroll snapping) of images and videos, with buttons, dots and arrow keys. */
export function MediaViewer({ media, alt, label, eager, handle }: Props) {
  const track = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const videos = useRef<(HTMLVideoElement | null)[]>([]);
  const [idx, setIdx] = useState(0);
  const n = media.length;

  const show = (i: number) => {
    const t = track.current;
    if (!t) return;
    const c = Math.max(0, Math.min(n - 1, i));
    t.scrollTo({ left: c * t.clientWidth, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
    setIdx(c);
  };

  useImperativeHandle(handle || null, () => ({
    show,
    seek(i: number, at: number) {
      show(i);
      const r = root.current?.getBoundingClientRect();
      if (r && (r.bottom < 60 || r.top > innerHeight - 60)) root.current!.scrollIntoView({ block: 'center', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
      const v = videos.current[i];
      if (v) {
        const go = () => { v.currentTime = at; v.play().catch(() => undefined); };
        if (v.readyState >= 1) go(); else { v.addEventListener('loadedmetadata', go, { once: true }); v.load(); }
        v.focus({ preventScroll: true });
      }
    },
  }), [n]);

  useEffect(() => {
    videos.current.forEach((v, i) => { if (v && i !== idx && !v.paused) v.pause(); });
  }, [idx]);

  // Keep the shown slide in place when the viewer is resized.
  useEffect(() => {
    const t = track.current;
    if (!t || !('ResizeObserver' in window)) return;
    const ro = new ResizeObserver(() => { t.scrollLeft = idxRef.current * t.clientWidth; });
    ro.observe(t);
    return () => ro.disconnect();
  }, []);
  const idxRef = useRef(0);
  idxRef.current = idx;

  const onScroll = () => {
    const t = track.current;
    if (!t || !t.clientWidth) return;
    const i = Math.round(Math.abs(t.scrollLeft) / t.clientWidth);
    if (i !== idx) setIdx(i);
  };

  const first = media[0];
  const w = first?.width || 4, h = first?.height || 5;
  const ar = Math.min(Math.max(w / h, 9 / 16), 1.91);

  return (
    <div class="viewer" ref={root} style={{ '--ar': String(ar) }} role={n > 1 ? 'region' : undefined}
      aria-roledescription={n > 1 ? 'carousel' : undefined} aria-label={n > 1 ? label : undefined}>
      <div class="track" ref={track} onScroll={onScroll} tabIndex={n > 1 ? 0 : -1}
        aria-label={n > 1 ? `${label}: use the arrow keys to move between ${n} slides` : undefined}
        onKeyDown={(e) => {
          if ((e.target as HTMLElement).tagName === 'VIDEO') return;
          if (e.key === 'ArrowRight') { e.preventDefault(); show(idx + 1); }
          if (e.key === 'ArrowLeft') { e.preventDefault(); show(idx - 1); }
        }}>
        {media.map((m, i) => (
          <div class="slide" key={i} role={n > 1 ? 'group' : undefined} aria-roledescription={n > 1 ? 'slide' : undefined}
            aria-label={n > 1 ? `${i + 1} of ${n}` : undefined} aria-hidden={n > 1 && i !== idx ? 'true' : undefined}>
            {m.type === 'video' ? (
              <video ref={(el) => { videos.current[i] = el; }} src={m.url} poster={posterOf(m)} controls playsinline
                preload={i === 0 ? 'metadata' : 'none'} aria-label={alt(i, m)} tabIndex={n > 1 && i !== idx ? -1 : 0}
                width={m.width || undefined} height={m.height || undefined} />
            ) : (
              <img src={m.url} alt={alt(i, m)} width={m.width || undefined} height={m.height || undefined}
                loading={i === 0 && eager ? 'eager' : 'lazy'} decoding="async" draggable={false} />
            )}
          </div>
        ))}
      </div>
      {n > 1 && (
        <>
          <button class="nav prev" onClick={() => show(idx - 1)} disabled={idx === 0} aria-label="Previous slide"><Icon name="left" /></button>
          <button class="nav next" onClick={() => show(idx + 1)} disabled={idx === n - 1} aria-label="Next slide"><Icon name="right" /></button>
          <div class="dots">
            {media.map((_, i) => (
              <button key={i} class="dot" aria-label={`Show slide ${i + 1} of ${n}`} aria-current={i === idx ? 'true' : undefined} onClick={() => show(i)} />
            ))}
          </div>
          <span class="counter" aria-hidden="true">{idx + 1}/{n}</span>
        </>
      )}
    </div>
  );
}
