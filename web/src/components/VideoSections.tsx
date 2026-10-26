import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { fmtShort } from '../util';
import { sizeOf, type Size, type VSection, type VTile, rankOf } from '../videoSections';
import { claimPlayback } from './zoom';
import { EditableLabel } from './EditableLabel';

const GAP = 6;
const CELLS: Record<Size, number> = { xl: 4, wide: 2, m: 1 };

/**
 * Columns for a section grid `w` px wide on an `h` px screen: about 160-260 px each (two thirds of
 * that for the lower levels), never fewer than two. Rows are 4:5 but never over 36% of the screen
 * height, so a large tile (two rows) always fits on screen with its section's title.
 */
function grid(w: number, h: number, compact: boolean) {
  const min = Math.max(160, Math.min(260, w / 7)) * (compact ? 0.68 : 1);
  const cols = Math.max(2, Math.floor((w + GAP) / (min + GAP)));
  const col = (w - GAP * (cols - 1)) / cols;
  return { cols, row: Math.round(Math.min(col * 1.25, Math.max(140, h * (compact ? 0.26 : 0.36)))) };
}

function Tile({ t, size, href, playing, onPlay }: { t: VTile; size: Size; href: string; playing: boolean; onPlay: (id: string | null, delay?: number) => void }) {
  return (
    <li class={`vt vt-${size}`} data-id={t.id} data-level={t.level} data-rank={rankOf(t)}>
      <a href={href} aria-label={[t.audio?.text, t.date && fmtShort(t.date), t.text].filter(Boolean).join(', ')} onFocus={() => onPlay(t.id)} onBlur={() => onPlay(null)}
        onPointerEnter={(e) => e.pointerType === 'mouse' && onPlay(t.id, 150)} onPointerLeave={() => onPlay(null)}>
        {t.cover ? <img src={t.cover} alt="" loading="lazy" decoding="async" /> : <span class="vt-blank" />}
        {playing && t.video && (
          <video src={t.video} poster={t.cover} muted loop playsInline autoPlay aria-hidden="true" tabIndex={-1}
            ref={(v) => { if (v) { claimPlayback(v); v.play().catch(() => undefined); } }}
            onPlaying={(e) => (e.currentTarget as HTMLVideoElement).classList.add('on')} />
        )}
        <span class="vt-cap">
          {t.date && <time dateTime={t.date}>{fmtShort(t.date)}</time>}
        </span>
      </a>
      {/* Outside the link: for the owner the label is editable in place */}
      {t.item
        ? <EditableLabel item={t.item} text={t.audio?.kind === 'heard' ? t.audio.text : ''} class="vt-audio vt-audio-heard" title="What is heard" />
        : t.audio?.text && <span class="vt-audio vt-audio-heard">{t.audio.text}</span>}
    </li>
  );
}

/**
 * The main screen: sections of videos with a title and a subtitle. Each grid fits the screen width
 * (see grid), and the most important videos of the top levels take two by two or two by one cells.
 * Long sections show their first rows with "Show all".
 */
export function VideoSections({ sections, hrefFor }: { sections: VSection[]; hrefFor: (t: VTile) => string }) {
  const root = useRef<HTMLDivElement>(null);
  const [[w, h], setSize] = useState([0, 0]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [playing, setPlaying] = useState<string | null>(null);
  const timer = useRef(0);
  const onPlay = (id: string | null, delay = 0) => {
    clearTimeout(timer.current);
    if (id && delay) timer.current = window.setTimeout(() => setPlaying(id), delay); else setPlaying(id);
  };
  useLayoutEffect(() => {
    const el = root.current!;
    const measure = () => setSize([el.clientWidth, window.innerHeight]);
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <div class="vsections" ref={root}>
      {w > 0 && sections.map((s, si) => {
        const { cols, row } = grid(w, h, s.compact);
        const sized = s.tiles.map((t, i) => [t, sizeOf(t, i, s.tiles.length, cols, si === 0)] as const);
        // Each section shows its first rows (the first four, the others two, three on a phone) until opened.
        const budget = open.has(s.id) ? Infinity : cols * (si === 0 ? 4 : cols <= 2 ? 3 : 2);
        let used = 0;
        const shown = sized.filter(([, z]) => (used += CELLS[z]) <= budget);
        return (
          <section key={s.id} class={`vsection vs-l${s.level}`} aria-labelledby={`vs-${s.id}`}>
            <header class="vs-head">
              <h2 id={`vs-${s.id}`}>{s.title}</h2>
              <p class="vs-sub">{s.subtitle}</p>
            </header>
            <ul class="vs-grid" style={{ '--cols': cols, '--row': `${row}px`, '--gap': `${GAP}px` }} aria-label={`${s.title}: ${s.tiles.length} videos`}>
              {shown.map(([t, z]) => <Tile key={t.id} t={t} size={z} href={hrefFor(t)} playing={playing === t.id} onPlay={onPlay} />)}
            </ul>
            {shown.length < s.tiles.length && (
              <button class="btn ghost vs-more" onClick={() => setOpen(new Set([...open, s.id]))}>Show all {s.tiles.length}</button>
            )}
          </section>
        );
      })}
    </div>
  );
}
