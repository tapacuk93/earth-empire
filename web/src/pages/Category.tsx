import { useEffect } from 'preact/hooks';
import { getAllItems } from '../api';
import { Kpis, MediaStrip } from '../components/Charts';
import { Feed } from '../components/Feed';
import { useCategories, useData } from '../components/Profile';
import { ctxItems, itemHref } from '../context';
import { navigate, type Route } from '../router';
import { people, places } from '../stats';
import { fmtShort, setMeta } from '../util';
import { withParam } from './Home';
import { NotFound } from './NotFound';

export function CategoryPage({ slug, route }: { slug: string; route: Route }) {
  const cats = useCategories();
  const all = useData(getAllItems);
  const cat = cats.data?.find((c) => c.slug === slug);
  useEffect(() => { if (cat) setMeta(cat.name, cat.description || `Everything in ${cat.name}.`); }, [cat]);
  if (cats.data && !cat) return <NotFound what="category" />;
  const ctx = `cat:${slug}`;
  const items = all.data ? ctxItems(ctx, all.data, []) : [];
  const pl = places(items), ppl = people(items);
  return (
    <>
      <header class="hero">
        <p class="eyebrow"><a href="/">Earth Empire</a> / Category</p>
        <h1>{cat?.name || slug}</h1>
        {cat?.description && <p class="lead">{cat.description}</p>}
        {all.data && <Kpis items={[
          { label: 'Videos', value: items.length, hint: items.length ? `${fmtShort(items[items.length - 1].taken_at)} – ${fmtShort(items[0].taken_at)}` : undefined },
          { label: 'Places', value: pl.length }, { label: 'People named', value: ppl.length },
        ]} />}
      </header>
      <section class="ipanel" aria-labelledby="cat-media">
        <header class="ipanel-head"><h2 id="cat-media">Media</h2>{items.length > 0 && <a class="btn small" href={itemHref(items[0].id, ctx)}>Play all</a>}</header>
        <MediaStrip items={items} ctx={ctx} label={`Media in ${cat?.name || slug}`} />
        {cats.data && (
          <nav class="chips" aria-label="Other categories">
            {cats.data.map((c) => <a key={c.slug} class="chip" href={`/category/${c.slug}`} aria-current={c.slug === slug ? 'page' : undefined}>{c.name}</a>)}
          </nav>
        )}
      </section>
      <section class="ipanel" aria-labelledby="cat-all">
        <header class="ipanel-head"><h2 id="cat-all">Everything in {cat?.name || slug}, by date</h2></header>
        <Feed query={{ category: slug }} layout="timeline" ctx={ctx} emptyText="Nothing in this category yet." />
      </section>
    </>
  );
}
