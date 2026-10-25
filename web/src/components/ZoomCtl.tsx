import { useState as useCtlState } from 'preact/hooks';

/** The zoom buttons, folded into one small floating control until needed. */
export function ZoomCtl({ title, zoom, onIn, onOut, onFit }: { title: string; zoom: number; onIn: () => void; onOut: () => void; onFit: () => void }) {
  const [open, setOpen] = useCtlState(false);
  return (
    <div class={`zoom-ctl fui ${open ? 'open' : ''}`}>
      {open && <>
        <span class="zoom-level" role="status">{zoom.toFixed(1)}×</span>
        <button class="icon-btn" onClick={onIn} aria-label={`Zoom in: ${title}`}>+</button>
        <button class="icon-btn" onClick={onOut} aria-label={`Zoom out: ${title}`}>−</button>
        <button class="icon-btn" onClick={onFit} aria-label={`Show all: ${title}`}>⤢</button>
      </>}
      <button class="icon-btn zoom-toggle" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`Zoom controls: ${title}`}>{open ? '×' : '⊕'}</button>
    </div>
  );
}
