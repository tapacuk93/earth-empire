import { useEffect, useState } from 'preact/hooks';
import { MonitorCard, MonitorMeta } from '../components/MonitorCard';
import { VideoFeed } from '../components/VideoFeed';
import { adminToken } from '../live';
import { getMonitorVideos, LOW_CONFIDENCE, publishVideo, type MonitorVideo } from '../monitor';
import { navigate, type Route } from '../router';
import { setMeta } from '../util';
import { withParam } from './Home';

export function MonitorPage({ route }: { route: Route }) {
  const [videos, setVideos] = useState<MonitorVideo[]>();
  const [err, setErr] = useState<string>();
  const [msg, setMsg] = useState('');
  const owner = !!adminToken();
  const watch = route.query.get('watch') || undefined;
  useEffect(() => { setMeta('Monitor', 'Videos from official accounts that mention the watched phrases, by confidence.'); }, []);
  useEffect(() => { getMonitorVideos().then((p) => setVideos(p.videos), (e) => setErr(e.message)); }, []);

  const publish = async (v: MonitorVideo) => {
    setMsg(`Publishing “${v.title}”…`);
    try { await publishVideo(v.id); setVideos((vs) => vs?.map((x) => (x.id === v.id ? { ...x, published: true } : x))); setMsg(`Published “${v.title}”.`); }
    catch (e) { setMsg(`Could not publish: ${(e as Error).message}`); }
  };
  const open = (id?: string) => navigate(withParam(route, 'watch', id), { replace: !!watch || !id, keepScroll: true });

  return (
    <>
      <header class="page-head">
        <h1>Monitor</h1>
        <p class="lead">Videos from official accounts that mention the phrases the monitor listens for, most certain first.
          Hits under {Math.round(LOW_CONFIDENCE * 100)}% are marked low confidence.</p>
        {videos && videos.length > 0 && <button class="btn" onClick={() => open(videos[0].id)}>Watch fullscreen</button>}
      </header>
      <p class="sr-only" role="status">{msg}</p>
      {msg && <p class="muted small" aria-hidden="true">{msg}</p>}
      {err ? <p class="error" role="alert">{/404/.test(err) ? 'The monitor is not live yet.' : `Could not load the monitor: ${err}`}</p>
        : !videos ? <p class="muted">Loading…</p>
        : !videos.length ? <p class="empty">Nothing found yet.</p>
        : (
          <ul class="mon-list" role="list">
            {videos.map((v) => (
              <MonitorCard key={v.id} v={v} onWatch={() => open(v.id)}>
                <p class="row">
                  {v.published ? <span class="kind-pill k-story">Published</span>
                    : owner && <button class="btn small" onClick={() => publish(v)}>Add to the site</button>}
                  {v.item && <a href={`/item/${encodeURIComponent(v.item)}`}>Details</a>}
                </p>
              </MonitorCard>
            ))}
          </ul>
        )}
      {watch && videos && videos.length > 0 && (
        <VideoFeed title="Monitor" start={watch} onClose={() => open(undefined)}
          onIndex={(id) => { if (id !== route.query.get('watch')) history.replaceState(history.state, '', withParam(route, 'watch', id)); }}
          videos={videos.map((v) => ({ id: v.id, url: v.url, cover: v.cover, label: v.title, overlay: <MonitorMeta v={v} /> }))} />
      )}
    </>
  );
}
