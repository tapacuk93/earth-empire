import { useState } from 'preact/hooks';
import { getTags } from '../api';
import type { Tag } from '../types';
import { useCategories, useData } from './Profile';

type Group = 'all' | 'people' | 'places' | 'things' | 'keywords' | 'category' | 'hashtag';
const GROUPS: [Group, string, string[]][] = [
  ['all', 'All', []], ['people', 'People', ['person']], ['places', 'Places', ['place', 'country']],
  ['things', 'Things', ['object', 'animal', 'brand']], ['keywords', 'Keywords', ['keyword', 'mood', 'occasion']],
  ['category', 'Categories', ['category']], ['hashtag', 'Hashtags', ['hashtag']],
];
const KIND_NAME: Record<string, string> = { person: 'person', place: 'place', country: 'country', object: 'thing', animal: 'animal', brand: 'brand',
  keyword: 'keyword', mood: 'mood', occasion: 'occasion', category: 'category', hashtag: 'hashtag' };
const FIRST = 48;
const MAX_LEN = 32;
const kindClass = (k: string) => (GROUPS.find(([, , ks]) => ks.includes(k))?.[0] || 'keywords');

/** A tag cloud from the analysis; each tag sized by how many items carry it. A click filters the items. */
export function TagCloud({ active, onPick }: { active?: string; onPick: (tag: string | undefined) => void }) {
  const tags = useData(getTags);
  const cats = useCategories();
  const [group, setGroup] = useState<Group>('all');
  const [all, setAll] = useState(false);

  if (tags.error) return <p class="error" role="alert">Could not load tags: {tags.error.message}</p>;
  if (!tags.data) return <div class="cloud skeleton-cloud" aria-hidden="true" />;
  if (!tags.data.length) return <p class="muted cloud-empty">Tags appear here once items have been described.</p>;

  const label = (t: Tag) => t.kind === 'category' ? cats.data?.find((c) => c.slug === t.tag)?.name || t.tag
    : t.kind === 'hashtag' ? '#' + t.tag.replace(/^#/, '') : t.tag;
  const kinds = GROUPS.find(([g]) => g === group)![2];
  // One word per tag: the same tag under two kinds shows once (the filter matches any kind anyway),
  // and long phrases stay out of the cloud.
  const seen = new Set<string>();
  const list = tags.data.filter((t) => {
    if (group !== 'all' && !kinds.includes(t.kind)) return false;
    if (t.tag.length > MAX_LEN || seen.has(t.tag)) return false;
    seen.add(t.tag);
    return true;
  });
  const shown = all ? list.slice() : list.slice(0, FIRST);
  const act = active?.toLowerCase();
  if (act && !shown.some((t) => t.tag === act)) {
    const a = tags.data.find((t) => t.tag === act);
    if (a) shown.unshift(a);
  }
  const counts = shown.map((t) => t.count);
  const lo = Math.log(Math.max(1, Math.min(...counts))), hi = Math.log(Math.max(1, ...counts));
  const size = (t: Tag) => 0.85 + 1.25 * (hi > lo ? (Math.log(t.count) - lo) / (hi - lo) : 0.3);
  // Alphabetical, like a classic cloud, so size carries the weight and not position.
  const sorted = shown.sort((a, b) => label(a).localeCompare(label(b), 'en', { sensitivity: 'base' }));
  const activeTag = act ? tags.data.find((t) => t.tag === act) : undefined;

  return (
    <section class="cloud-wrap" aria-labelledby="cloud-h">
      <div class="cloud-head">
        <h2 id="cloud-h">Tags</h2>
        <div class="cloud-kinds" role="group" aria-label="Tag type">
          {GROUPS.filter(([g, , ks]) => g === 'all' || tags.data!.some((t) => ks.includes(t.kind))).map(([g, name]) => (
            <button key={g} class="kind small" aria-pressed={group === g} onClick={() => { setGroup(g); setAll(false); }}>{name}</button>
          ))}
        </div>
      </div>
      <ul class="cloud" role="list">
        {sorted.map((t) => (
          <li key={`${t.kind}:${t.tag}`}>
            <button class={`ctag t-${kindClass(t.kind)}`} style={{ fontSize: `${size(t).toFixed(2)}rem` }} aria-pressed={act === t.tag}
              aria-label={`${label(t)}, ${KIND_NAME[t.kind] || t.kind}, ${t.count} item${t.count === 1 ? '' : 's'}`}
              title={`${KIND_NAME[t.kind] || t.kind} · ${t.count}`} onClick={() => onPick(act === t.tag ? undefined : t.tag)}>
              {label(t)}
            </button>
          </li>
        ))}
      </ul>
      {list.length > FIRST && (
        <button class="btn small ghost" onClick={() => setAll(!all)} aria-expanded={all}>{all ? 'Fewer tags' : `All ${list.length} tags`}</button>
      )}
      {act && (
        <p class="cloud-active" role="status">
          Items tagged <b>{activeTag ? label(activeTag) : active}</b>{' '}
          <button class="btn small" onClick={() => onPick(undefined)}>Clear</button>
        </p>
      )}
    </section>
  );
}
