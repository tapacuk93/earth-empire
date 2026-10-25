import { useEffect } from 'preact/hooks';
import { setMeta } from '../util';

export function NotFound({ what = 'page' }: { what?: string }) {
  useEffect(() => { setMeta('Not found', undefined, undefined, true); }, []);
  return (
    <section class="notfound">
      <h1>Not found</h1>
      <p>This {what} is not in the archive{what === 'page' ? '' : ', or it was removed'}.</p>
      <p><a class="btn" href="/">Back to the archive</a></p>
    </section>
  );
}
