import { useEffect } from 'preact/hooks';
import { Feed } from '../components/Feed';
import { KindTabs, useCategories } from '../components/Profile';
import { navigate, type Route } from '../router';
import { setMeta } from '../util';
import { withParam } from './Home';
import { NotFound } from './NotFound';

export function CategoryPage({ slug, route }: { slug: string; route: Route }) {
  const cats = useCategories();
  const cat = cats.data?.find((c) => c.slug === slug);
  const kind = route.query.get('kind') || undefined;
  useEffect(() => { if (cat) setMeta(cat.name, cat.description || `Everything in ${cat.name}.`); }, [cat]);
  if (cats.data && !cat) return <NotFound what="category" />;
  return (
    <>
      <header class="page-head">
        <p class="eyebrow"><a href="/">Archive</a> / Category</p>
        <h1>{cat?.name || slug}</h1>
        {cat?.description && <p class="lead">{cat.description}</p>}
        {typeof cat?.count === 'number' && <p class="muted">{cat.count} item{cat.count === 1 ? '' : 's'}</p>}
        {cats.data && (
          <nav class="chips" aria-label="Other categories">
            {cats.data.map((c) => <a key={c.slug} class="chip" href={`/category/${c.slug}`} aria-current={c.slug === slug ? 'page' : undefined}>{c.name}</a>)}
          </nav>
        )}
      </header>
      <div class="filters">
        <KindTabs active={kind} onPick={(k) => navigate(withParam(route, 'kind', k), { replace: true, keepScroll: true })} />
      </div>
      <Feed query={{ category: slug, kind }} emptyText="Nothing in this category yet." />
    </>
  );
}
