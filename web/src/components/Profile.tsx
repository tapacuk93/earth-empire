import { useEffect, useState } from 'preact/hooks';
import { getCategories, getHighlights, getProfile } from '../api';
import type { Category, Highlight, Profile } from '../types';
import { fmtCount, igProfile } from '../util';

export function useData<T>(fn: () => Promise<T>, deps: unknown[] = []): { data?: T; error?: Error; loading: boolean } {
  const [s, set] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true });
  useEffect(() => {
    let live = true;
    set((p) => ({ ...p, loading: true, error: undefined }));
    fn().then((data) => live && set({ data, loading: false }), (error) => live && set({ error, loading: false }));
    return () => { live = false; };
  }, deps);
  return s;
}

export const useProfile = () => useData(getProfile);
export const useHighlights = () => useData(getHighlights);
export const useCategories = () => useData(getCategories);

export function ProfileHeader({ profile }: { profile?: Profile }) {
  if (!profile) return <header class="profile skeleton-profile" aria-hidden="true"><span class="avatar" /><span class="line" /></header>;
  const c = profile.counts || {};
  return (
    <header class="profile">
      {profile.avatar ? <img class="avatar" src={profile.avatar} alt={`Profile photo of @${profile.username}`} width={160} height={160} />
        : <span class="avatar" aria-hidden="true" />}
      <div class="profile-text">
        <h1 class="profile-name">
          <span class="username">{profile.username}</span>
          {profile.full_name && <span class="fullname">{profile.full_name}</span>}
        </h1>
        <ul class="counts" role="list">
          {c.posts !== undefined && <li><b>{fmtCount(c.posts)}</b> posts</li>}
          {c.followers !== undefined && <li><b>{fmtCount(c.followers)}</b> followers</li>}
          {c.following !== undefined && <li><b>{fmtCount(c.following)}</b> following</li>}
        </ul>
        {profile.bio && <p class="bio">{profile.bio}</p>}
        <p class="links">
          {(profile.links || []).map((l) => <a key={l} href={l} rel="external noopener">{l.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}</a>)}
          <a href={igProfile(profile.username)} rel="external noopener">@{profile.username} on Instagram</a>
        </p>
      </div>
    </header>
  );
}

export function HighlightsRow({ highlights }: { highlights?: Highlight[] }) {
  if (!highlights) return <div class="hl-row" aria-hidden="true">{[0, 1, 2, 3].map((i) => <span key={i} class="hl"><span class="hl-cover" /></span>)}</div>;
  if (!highlights.length) return null;
  return (
    <nav class="hl-row" aria-label="Highlights">
      <ul role="list">
        {highlights.map((h) => (
          <li key={h.id}>
            <a class="hl" href={`/highlight/${encodeURIComponent(h.id)}`}>
              <span class="hl-ring">{h.cover ? <img class="hl-cover" src={h.cover} alt="" width={80} height={80} loading="lazy" /> : <span class="hl-cover" />}</span>
              <span class="hl-title">{h.title}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function CategoryChips({ categories, active, onPick }: { categories?: Category[]; active?: string; onPick: (slug: string | undefined) => void }) {
  if (!categories?.length) return null;
  return (
    <div class="chips" role="group" aria-label="Category">
      <button class="chip" aria-pressed={!active} onClick={() => onPick(undefined)}>All categories</button>
      {categories.map((c) => (
        <button key={c.slug} class="chip" aria-pressed={active === c.slug} onClick={() => onPick(active === c.slug ? undefined : c.slug)}>
          {c.name}{typeof c.count === 'number' && <span class="chip-count">{c.count}</span>}
        </button>
      ))}
    </div>
  );
}
