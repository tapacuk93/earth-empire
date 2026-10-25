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
 * The owner's hidden way in, as in the apps: on the footer's final dot, one tap, a pause, then three
 * quick taps opens the admin key prompt. The key is checked with GET /v1/admin/me and kept locally.
 */
export function SecretDot() {
  const taps = useRef<number[]>([]);
  const [open, setOpen] = useState(false);
  const owner = useOwner();
  const tap = () => {
    const now = Date.now();
    const t = [...taps.current, now].filter((x) => now - x < 4000).slice(-4);
    taps.current = t;
    if (t.length === 4 && t[1] - t[0] >= 600 && t[2] - t[1] < 450 && t[3] - t[2] < 450) { taps.current = []; setOpen(true); }
  };
  return (
    <>
      <button type="button" class="secret-dot" onClick={tap} aria-label="." tabIndex={-1}>.</button>
      {open && !owner && <OwnerPrompt onClose={() => setOpen(false)} />}
    </>
  );
}

function OwnerPrompt({ onClose }: { onClose: () => void }) {
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

