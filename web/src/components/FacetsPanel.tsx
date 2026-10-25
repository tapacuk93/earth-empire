import { useState } from 'preact/hooks';
import type { Facet } from '../homeData';

/** Every facet the backend defines, with its categories; any number of each. A category opens its wheel. */
export function FacetsPanel({ facets, onOpen }: { facets: Facet[]; onOpen: (facet: Facet, category: Facet['categories'][number]) => void }) {
  const [open, setOpen] = useState(false);
  if (!facets.length) return null;
  return (
    <div class={`facets fui ${open ? 'open' : ''}`}>
      <button class="btn small facets-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Close' : 'Facets'}</button>
      {open && (
        <div class="facets-sheet" role="region" aria-label="Facets">
          {facets.map((f) => (
            <section key={f.id} aria-labelledby={`f-${f.id}`}>
              <h3 id={`f-${f.id}`}>{f.name}</h3>
              <ul class="chips-list">
                {f.categories.map((c) => (
                  <li key={c.id}><button class="chip" onClick={() => onOpen(f, c)} title={c.description || ''}>{c.name}<span class="chip-count">{c.count}</span></button></li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
