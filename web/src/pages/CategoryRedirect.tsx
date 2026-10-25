import { useEffect } from 'preact/hooks';
import { getAllItems } from '../api';
import { itemHref, setFacets } from '../context';
import { getFacets } from '../homeData';
import { navigate } from '../router';

/** Old /category/<slug> links: the AI facet category of the same name, else Home. */
export function CategoryRedirect({ slug }: { slug: string }) {
  useEffect(() => {
    let live = true;
    Promise.all([getFacets(), getAllItems()]).then(([facets, items]) => {
      if (!live) return;
      const want = slug.toLowerCase();
      for (const f of facets || []) {
        const c = f.categories.find((x) => x.id.toLowerCase() === want || x.name.toLowerCase() === want);
        const ids = new Set(c?.item_ids || []);
        const first = items.find((it) => ids.has(it.id));
        if (c && first) { setFacets(facets!); navigate(itemHref(first.id, `facet:${f.id}:${c.id}`), { replace: true }); return; }
      }
      navigate('/', { replace: true });
    }, () => live && navigate('/', { replace: true }));
    return () => { live = false; };
  }, [slug]);
  return <p class="muted" role="status">Opening…</p>;
}
