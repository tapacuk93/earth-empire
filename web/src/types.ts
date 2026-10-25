// The shapes CONTRACT.md defines. Fields the site does not read are still typed loosely so
// nothing breaks when the backend adds more.
export type Kind = 'post' | 'carousel' | 'reel' | 'story';

export interface Media {
  type: 'image' | 'video';
  url: string;
  thumbnail?: string | null;
  /** The best frame of a video, chosen by the backend; preferred over `thumbnail` as the cover. */
  cover?: string | null;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
}

export interface Location { name: string; id?: string; lat?: number | null; lng?: number | null }
export interface Sticker { type: string; text?: string | null; extra?: Record<string, unknown> }
export interface TaggedUser { username: string; x?: number; y?: number }

export interface Repost {
  author: string;
  author_name?: string | null;
  shortcode?: string | null;
  source_url?: string | null;
  taken_at?: string | null;
  caption?: string | null;
  media: Media[];
}

export interface Appearance { media?: number; from?: number; to?: number }
export interface Person { who?: string | null; description?: string; basis?: string; role?: string; appears?: Appearance[] }
export interface Event { media?: number; at: number; text: string }

export interface Analysis {
  people?: Person[];
  what?: string;
  events?: Event[];
  when?: { date?: string; time_of_day?: string; season?: string; occasion?: string; basis?: string } | null;
  where?: { place?: string; kind?: string; country?: string; basis?: string } | null;
  objects?: string[];
  animals?: string[];
  brands?: string[];
  on_screen_text?: string[];
  speech?: { language?: string; transcript?: string } | null;
  music?: string | null;
  mood?: string;
  language?: string;
  context?: string;
  keywords?: string[];
  model?: string;
  analyzed_at?: string;
}

export interface Item {
  id: string;
  kind: Kind;
  shortcode?: string | null;
  source_url?: string | null;
  taken_at: string;
  caption?: string | null;
  hashtags?: string[];
  mentions?: string[];
  tagged_users?: TaggedUser[];
  location?: Location | null;
  music?: { title?: string; artist?: string } | null;
  alt_text?: string | null;
  stickers?: Sticker[];
  counts?: { likes?: number; comments?: number; views?: number; plays?: number };
  media: Media[];
  highlights?: { id: string; title: string }[];
  repost_of?: Repost | null;
  categories?: string[];
  summary?: string | null;
  /** A few publishable sentences: who, what, when, where, context (covers a repost's original too). */
  description?: string | null;
  analysis?: Analysis | null;
  published_at?: string | null;
  importance?: number | null;
  /** Why the item is public (CONTRACT.md): the monitor's matched moments. */
  detection?: { matched?: boolean; hits?: DetectionHit[]; model?: string; scanned_at?: string } | null;
}

export interface DetectionHit { kind: 'name' | 'language'; phrase?: string | null; lang?: string | null; media?: number; at?: number; confidence?: number; excerpt?: string; translation?: string | null }

export interface Highlight { id: string; title: string; cover?: string | null; item_ids: string[]; updated_at?: string }
export interface Category { slug: string; name: string; description?: string | null; count?: number }
export interface Profile {
  username: string;
  full_name?: string | null;
  bio?: string | null;
  avatar?: string | null;
  links?: string[];
  counts?: { posts?: number; followers?: number; following?: number };
}

export interface ItemQuery { kind?: string; category?: string; highlight?: string; tag?: string; q?: string; before?: string; limit?: number }

export type TagKind = 'category' | 'keyword' | 'place' | 'country' | 'object' | 'animal' | 'brand' | 'hashtag' | 'person' | 'mood' | 'occasion';
/** One tag of the cloud, as GET /v1/tags returns it. `tag` is lowercase; `GET /v1/items?tag=` takes it. */
export interface Tag { tag: string; kind: TagKind | string; count: number }
export interface ItemPage { items: Item[]; next: string | null }
