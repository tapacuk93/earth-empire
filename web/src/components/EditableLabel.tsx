import { useEffect, useRef, useState } from 'preact/hooks';
import { setHeard, useOwner } from '../live';
import type { Item } from '../types';

/**
 * A gold label. For the owner (token checked) it is editable in place: a click or Enter edits it,
 * leaving the field (a click outside, Enter or Tab) saves it as the item's label, Escape cancels.
 * Emptied, the label goes back to what the backend works out.
 */
export function EditableLabel({ item, text, class: cls, title }: { item?: Item; text: string; class: string; title?: string }) {
  const owner = useOwner();
  const [shown, setShown] = useState(text);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!editing) setShown(text); }, [text]);
  useEffect(() => { if (editing) { field.current?.focus(); field.current?.select(); } }, [editing]);
  const editable = !!owner && !!item;
  if (!editable) return <span class={cls} title={title}>{shown}</span>;

  const save = async () => {
    const v = (field.current?.value || '').replace(/\s+/g, ' ').trim();
    setEditing(false);
    if (v === shown) return;
    setBusy(true); setErr('');
    try { await setHeard(item!, v); setShown(v || text); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const stop = (e: Event) => { e.preventDefault(); e.stopPropagation(); };
  return editing
    ? <input ref={field} class={`${cls} label-edit`} defaultValue={shown} aria-label="Label (what is heard)" maxLength={80}
        onClick={stop} onPointerDown={(e) => e.stopPropagation()} onBlur={save}
        onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Enter') field.current?.blur(); else if (e.key === 'Escape') { if (field.current) field.current.value = shown; field.current?.blur(); } }} />
    : <button type="button" class={`${cls} label-btn ${busy ? 'busy' : ''}`} title={err || 'Edit the label'} aria-label={`Label: ${shown}. Edit it.`}
        onClick={(e) => { stop(e); setEditing(true); }} onPointerDown={(e) => e.stopPropagation()}>{shown}{err && <span class="label-err" aria-hidden="true"> !</span>}</button>;
}
