import { useEffect } from 'preact/hooks';
import { getAllItems } from '../api';
import { Kpis, MediaStrip } from '../components/Charts';
import { Feed } from '../components/Feed';
import { KindTabs, useCategories, useData } from '../components/Profile';
import { ctxItems, itemHref } from '../context';
import { navigate, type Route } from '../router';
import { kinds, people, places } from '../stats';
import { fmtShort, setMeta } from '../util';
import { withParam } from './Home';
import { NotFound } from './NotFound';

export function CategoryPage({ slug, route }: { slug: string; route: Route }) {
  const cats = useCategories();
  const all = useData(getAllItems);
  const cat = cats.data?.find((c) => c.slug === slug);
  const kind = route.query.get('kind') || undefined;
  useEffect(() => { if (cat) setMeta(cat.name, cat.description || `Everything in ${cat.name}.`); }, [cat]);
  if (cats.data && !cat) return <NotFound what="category" />;
  const ctx = `cat:${slug}`;
  const items = all.data ? ctxItems(ctx, all.data, []) : [];
  const k = kinds(items);
  const pl = places(items), ppl = people(items);
  return (
    <>
      <header class="hero">
        <p class="eyebrow"><a href="/">Earth Empire</a> / Category</p>
        <h1>{cat?.name || slug}</h1>
        {cat?.description && <p class="lead">{cat.description}</p>}
        {all.data && <Kpis items={[
          { label: 'Items', value: items.length, hint: items.length ? `${fmtShort(items[items.length - 1].taken_at)} – ${fmtShort(items[0].taken_at)}` : undefined },
          { label: 'Reels', value: k.reel || 0 }, { label: 'Stories', value: k.story || 0 }, { label: 'Places', value: pl.length }, { label: 'People named', value: ppl.length },
        ]} />}
      </header>
      <section class="ipanel" aria-labelledby="cat-media">
        <header class="ipanel-head"><h2 id="cat-media">Media</h2>{items.length > 0 && <a class="btn small" href={itemHref(items[0].id, ctx)}>Open the feed</a>}</header>
        <MediaStrip items={items} ctx={ctx} label={`Media in ${cat?.name || slug}`} />
        {cats.data && (
          <nav class="chips" aria-label="Other categories">
            {cats.data.map((c) => <a key={c.slug} class="chip" href={`/category/${c.slug}`} aria-current={c.slug === slug ? 'page' : undefined}>{c.name}</a>)}
          </nav>
        )}
      </section>
      <section class="ipanel" aria-labelledby="cat-all">
        <header class="ipanel-head"><h2 id="cat-all">Everything in {cat?.name || slug}, by date</h2></header>
        <div class="filters"><KindTabs active={kind} onPick={(v) => navigate(withParam(route, 'kind', v), { replace: true, keepScroll: true })} /></div>
        <Feed query={{ category: slug, kind }} layout="timeline" ctx={ctx} emptyText="Nothing in this category yet." />
      </section>
    </>
  );
}
