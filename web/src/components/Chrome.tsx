import { useEffect, useRef, useState } from 'preact/hooks';
import { useOwner } from '../live';
import { OwnerToken } from '../pages/Settings';
import { Icon } from './icons';

type Theme = 'auto' | 'light' | 'dark';
function readTheme(): Theme { try { return (localStorage.getItem('theme') as Theme) || 'auto'; } catch { return 'auto'; } }

export function ThemeToggle() {
  const [t, setT] = useState<Theme>(readTheme);
  useEffect(() => {
    const el = document.documentElement;
    if (t === 'auto') el.removeAttribute('data-theme'); else el.setAttribute('data-theme', t);
    try { localStorage.setItem('theme', t); } catch { /* private mode */ }
  }, [t]);
  const next: Theme = t === 'auto' ? 'dark' : t === 'dark' ? 'light' : 'auto';
  return (
    <button class="icon-btn theme" onClick={() => setT(next)} aria-label={`Theme: ${t}. Switch to ${next}.`} title={`Theme: ${t}`}>
      <Icon name={t === 'auto' ? 'auto' : t === 'dark' ? 'moon' : 'sun'} />
    </button>
  );
}

/**
 * The owner's hidden way in, on the Earth icon (as in the apps): one tap, a pause of about
 * 0.5-1.5 s, then three quick taps (under 300 ms apart) open the admin key prompt. A plain tap
 * still does what the icon does (go Home), after a short wait in case the pattern is starting.
 * Taps count while the floating controls are faded too: the icon keeps taking taps then, so a tap
 * never falls through to a tile underneath.
 */
export function EarthButton({ class: cls, onSingle, label }: { class?: string; onSingle?: () => void; label: string }) {
  const taps = useRef<number[]>([]);
  const timer = useRef(0);
  const [open, setOpen] = useState(false);
  const owner = useOwner();
  const tap = (e: Event) => {
    e.preventDefault();
    const now = Date.now();
    const t = [...taps.current, now].filter((x) => now - x < 3500).slice(-4);
    taps.current = t;
    clearTimeout(timer.current);
    const ok = t.length === 4 && t[1] - t[0] >= 450 && t[1] - t[0] <= 1600 && t[2] - t[1] < 320 && t[3] - t[2] < 320;
    if (ok) { taps.current = []; if (!owner) setOpen(true); return; }
    // A lone tap acts once it is clear no pattern follows.
    timer.current = window.setTimeout(() => { if (taps.current.length === 1) onSingle?.(); taps.current = []; }, 1700);
  };
  return (
    <>
      <button type="button" class={`earth-btn ${cls || ''}`} onClick={tap} aria-label={label}><span class="logo" aria-hidden="true" /></button>
      {open && <OwnerPrompt onClose={() => setOpen(false)} />}
    </>
  );
}

export function OwnerPrompt({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return (
    <div class="prompt-back" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="prompt" role="dialog" aria-modal="true" aria-label="Admin key" onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
        <h2>Admin key</h2>
        <OwnerToken onChange={(ok) => { if (ok) setTimeout(onClose, 600); }} inputRef={ref} />
        <button class="btn small ghost" onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}

