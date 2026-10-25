import type { ComponentChildren } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { Icon } from './icons';

export interface FeedVideo { id: string; url: string; cover?: string; label: string; overlay?: ComponentChildren }

/**
 * Fullscreen vertical video mode: one video per screen, swipe or scroll up and down (native
 * scroll snapping), arrow keys or j/k, m to unmute, Esc to close. The video on screen plays.
 */
export function VideoFeed({ videos, start, title, onClose, onIndex }: {
  videos: FeedVideo[]; start?: string; title: string; onClose: () => void; onIndex?: (id: string) => void;
}) {
  const list = useRef<HTMLDivElement>(null);
  const [muted, setMuted] = useState(true);
  const [cur, setCur] = useState(() => Math.max(0, videos.findIndex((v) => v.id === start)));
  const vids = useRef<(HTMLVideoElement | null)[]>([]);

  useEffect(() => {
    const el = list.current;
    if (!el) return;
    el.scrollTop = cur * el.clientHeight;
    el.focus({ preventScroll: true });
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  useEffect(() => {
    vids.current.forEach((v, i) => {
      if (!v) return;
      if (i === cur) { v.muted = muted; v.play().catch(() => undefined); } else if (!v.paused) v.pause();
    });
    const v = videos[cur];
    if (v) onIndex?.(v.id);
  }, [cur, muted]);

  const go = (i: number) => {
    const el = list.current;
    if (!el) return;
    const c = Math.max(0, Math.min(videos.length - 1, i));
    el.scrollTo({ top: c * el.clientHeight, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };
  const onScroll = () => {
    const el = list.current;
    if (!el || !el.clientHeight) return;
    const i = Math.round(el.scrollTop / el.clientHeight);
    if (i !== cur) setCur(i);
  };

  return (
    <div class="vfeed" role="dialog" aria-modal="true" aria-label={title}
      onKeyDown={(e) => {
        if (e.key === 'Escape') { e.preventDefault(); onClose(); }
        else if (e.key === 'ArrowDown' || e.key === 'j') { e.preventDefault(); go(cur + 1); }
        else if (e.key === 'ArrowUp' || e.key === 'k') { e.preventDefault(); go(cur - 1); }
        else if (e.key === 'm') setMuted(!muted);
      }}>
      <div class="vfeed-top">
        <h2 class="vfeed-title">{title} <span class="muted">{cur + 1}/{videos.length}</span></h2>
        <button class="icon-btn" onClick={() => setMuted(!muted)} aria-label={muted ? 'Unmute' : 'Mute'} aria-pressed={!muted}><Icon name={muted ? 'mute' : 'sound'} /></button>
        <button class="icon-btn" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
      </div>
      <div class="vfeed-list" ref={list} onScroll={onScroll} tabIndex={0} aria-label={`${title}: use the arrow keys to move between videos`}>
        {videos.map((v, i) => (
          <section class="vfeed-slide" key={v.id} aria-label={`${i + 1} of ${videos.length}: ${v.label}`} aria-hidden={i !== cur ? 'true' : undefined}>
            <video ref={(el) => { vids.current[i] = el; }} src={Math.abs(i - cur) <= 1 ? v.url : undefined} poster={v.cover}
              playsinline loop muted={muted} preload={i === cur ? 'auto' : 'metadata'} aria-label={v.label}
              onClick={(e) => { const t = e.currentTarget as HTMLVideoElement; if (t.paused) t.play().catch(() => undefined); else t.pause(); }} />
            {v.overlay && <div class="vfeed-info">{v.overlay}</div>}
          </section>
        ))}
      </div>
      <div class="vfeed-nav">
        <button class="icon-btn" onClick={() => go(cur - 1)} disabled={cur === 0} aria-label="Previous video"><Icon name="left" class="up" /></button>
        <button class="icon-btn" onClick={() => go(cur + 1)} disabled={cur === videos.length - 1} aria-label="Next video"><Icon name="right" class="down" /></button>
      </div>
    </div>
  );
}
