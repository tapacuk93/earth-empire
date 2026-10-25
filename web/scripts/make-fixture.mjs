// Writes mock/fixture.json: an invented archive in the shape CONTRACT.md defines, over the
// synthetic media from make-mock-media.sh. Every person, account and place here is made up.
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const M = '/mock/media/';
const img = (name, w, h) => ({ type: 'image', url: `${M}${name}.jpg`, thumbnail: `${M}${name}.thumb.jpg`, width: w, height: h, duration: null });
// Every video but one has the backend's chosen best frame as `cover`; story-market shows the fallback to `thumbnail`.
const vid = (name, w, h, d) => ({ type: 'video', url: `${M}${name}.mp4`, thumbnail: `${M}${name}.thumb.jpg`, ...(name === 'story-market' ? {} : { cover: `${M}${name}.cover.jpg` }), width: w, height: h, duration: d });
const at = (d) => new Date(Date.UTC(2026, 9, 24) - d * 36e5).toISOString().replace('.000', '');
const stamp = { collected_at: '2026-10-25T09:00:00Z', updated_at: '2026-10-25T09:00:00Z' };
const analysis = (a) => ({
  people: [], events: [], objects: [], animals: [], brands: [], on_screen_text: [], speech: null, music: null,
  keywords: [], model: 'claude-opus-5-5', analyzed_at: '2026-10-25T09:10:00Z', ...a,
});
const base = (o) => ({
  shortcode: null, source_url: null, caption: null, hashtags: [], mentions: [], tagged_users: [], location: null,
  music: null, alt_text: null, stickers: [], counts: {}, highlights: [], repost_of: null, categories: [], summary: null,
  analysis: null, extra: {}, ...stamp, published_at: '2026-10-25T09:10:00Z', ...o,
});

const items = [
  base({
    id: 'ig_3400000000000000001', kind: 'reel', shortcode: 'DMockReel1', source_url: 'https://www.instagram.com/reel/DMockReel1/',
    taken_at: at(2), caption: 'Last light on the west coast with @mira.sails 🌅 #sunset #run #coast',
    hashtags: ['sunset', 'run', 'coast'], mentions: ['mira.sails'],
    location: { name: 'Cape Lumen Lighthouse', id: '7700001', lat: 38.71, lng: -9.49 },
    music: { title: 'Golden Hour Drive', artist: 'The Paper Kites (sample)' },
    counts: { likes: 1284, comments: 41, plays: 20311 },
    media: [vid('reel-sunset', 540, 960, 9)],
    categories: ['travel', 'nature', 'friends'], summary: 'A sunset run along the cliffs to the lighthouse with Mira.',
    analysis: analysis({
      people: [
        { who: '@mira.sails', description: 'woman in a red windbreaker running ahead', basis: 'mention', role: 'running partner', appears: [{ media: 0, from: 0, to: 6.5 }] },
        { who: null, description: 'the account owner, filming and speaking off camera', basis: 'speech', role: 'narrator', appears: [{ media: 0, from: 0, to: 9 }] },
      ],
      what: 'Two people run along a cliff path at sunset toward a lighthouse. The camera turns to the sea as the sun touches the horizon, and the runner ahead waves at the end.',
      events: [
        { media: 0, at: 0.5, text: 'Start of the run on the cliff path' },
        { media: 0, at: 3.2, text: 'The lighthouse comes into view' },
        { media: 0, at: 5.8, text: 'Camera pans to the sun on the horizon' },
        { media: 0, at: 8.1, text: 'Mira turns and waves' },
      ],
      when: { date: '2026-10-23', time_of_day: 'sunset', season: 'autumn', occasion: 'evening run', basis: 'light and caption' },
      where: { place: 'Cape Lumen Lighthouse', kind: 'coast', country: 'Portugal', basis: 'location' },
      objects: ['lighthouse', 'cliff path', 'windbreaker'], on_screen_text: ['Day 12'],
      speech: { language: 'English', transcript: 'Okay, last kilometre. Look at that light. Mira, slow down! … We made it before the sun went down.' },
      music: 'Golden Hour Drive - The Paper Kites (sample)', mood: 'joyful, golden', language: 'English',
      context: 'Part of a running series: the on-screen "Day 12" counts days of a coastal trip that earlier posts started.',
      keywords: ['sunset', 'running', 'lighthouse', 'coast', 'autumn'],
    }),
  }),
  base({
    id: 'ig_3400000000000000002', kind: 'carousel', shortcode: 'DMockCaro1', source_url: 'https://www.instagram.com/p/DMockCaro1/',
    taken_at: at(20), caption: 'Three days, one city, too many stairs. Thanks @leo.maps for the tour #citywalk #architecture',
    hashtags: ['citywalk', 'architecture'], mentions: ['leo.maps'],
    tagged_users: [{ username: 'leo.maps', x: 0.42, y: 0.55 }],
    location: { name: 'Alfama, Lisbon', id: '7700002', lat: 38.711, lng: -9.13 },
    counts: { likes: 932, comments: 18 },
    alt_text: 'Photo 1: a blue evening street; photo 2: a pink tiled wall; photo 3: rooftops at night.',
    media: [img('city-1', 720, 900), img('city-2', 720, 900), img('city-3', 720, 900)],
    categories: ['travel', 'city'], summary: 'A three-photo walk through the old town with Leo as guide.',
    analysis: analysis({
      people: [{ who: '@leo.maps', description: 'man in a grey cap pointing at a doorway', basis: 'tag', role: 'tour guide', appears: [{ media: 0 }] }],
      what: 'A carousel of a city walk: a steep blue street at dusk, a wall of pink tiles, and rooftops after dark.',
      when: { date: '2026-10-23', time_of_day: 'evening', season: 'autumn', occasion: 'trip', basis: 'caption' },
      where: { place: 'Alfama, Lisbon', kind: 'city', country: 'Portugal', basis: 'location' },
      objects: ['tiles', 'tram rails', 'rooftops'], on_screen_text: ['Rua do Mock 12'],
      mood: 'curious, relaxed', language: 'English',
      context: 'Second stop of the same coastal trip as the sunset reel.', keywords: ['lisbon', 'tiles', 'stairs'],
    }),
  }),
  base({
    id: 'ig_3400000000000000003', kind: 'story', taken_at: at(26),
    media: [img('story-dune', 720, 1280)],
    stickers: [{ type: 'location', text: 'Dunas Altas', extra: {} }, { type: 'poll', text: 'Sandboard or walk?', extra: { options: ['Sandboard', 'Walk'] } }],
    highlights: [{ id: 'hl_9001', title: 'Travel' }],
    categories: ['travel', 'nature'], summary: 'A story from the dunes asking followers to vote: sandboard or walk.',
    analysis: analysis({
      what: 'A wide shot of orange dunes under a yellow sky with a poll sticker.',
      when: { time_of_day: 'midday', season: 'autumn', basis: 'light' },
      where: { place: 'Dunas Altas', kind: 'desert', country: 'Portugal', basis: 'location sticker' },
      on_screen_text: ['Sandboard or walk?'], mood: 'playful', language: 'English',
      context: 'Poll story; the next story in the Travel highlight shows the answer.', keywords: ['dunes', 'poll'],
    }),
  }),
  base({
    id: 'ig_3400000000000000004', kind: 'story', taken_at: at(30),
    media: [vid('story-share', 540, 960, 6)],
    stickers: [{ type: 'mention', text: '@oceanlab', extra: {} }],
    highlights: [{ id: 'hl_9003', title: 'Ocean' }],
    repost_of: {
      author: 'oceanlab', author_name: 'Ocean Lab (sample)', shortcode: 'DMockOrig1', source_url: 'https://www.instagram.com/reel/DMockOrig1/',
      taken_at: at(50), caption: 'Bioluminescent plankton lighting up the bay last night. Sound on. #ocean #science',
      media: [vid('ocean-reel', 540, 960, 8)],
    },
    categories: ['ocean', 'nature'], summary: 'A story sharing Ocean Lab\'s reel of glowing plankton in a bay.',
    analysis: analysis({
      people: [{ who: '@oceanlab', description: 'the original reel\'s author, a marine science account', basis: 'mention', role: 'original author' }],
      what: 'The owner shares a reel by @oceanlab of plankton glowing blue in a dark bay, with a mention sticker.',
      events: [{ media: 0, at: 1, text: 'Shared reel appears in the story frame' }, { media: 0, at: 4, text: 'Mention sticker pops in' }],
      on_screen_text: ['@oceanlab', 'so cool'], mood: 'amazed', language: 'English',
      context: 'A share, not the owner\'s own footage; credited to @oceanlab.', keywords: ['plankton', 'bioluminescence', 'share'],
    }),
  }),
  base({
    id: 'ig_3400000000000000005', kind: 'post', shortcode: 'DMockPost1', source_url: 'https://www.instagram.com/p/DMockPost1/',
    taken_at: at(48), caption: 'Sunday bowl: roasted squash, chili oil, too much coriander. Recipe in the reel. #food #homecooking',
    hashtags: ['food', 'homecooking'], counts: { likes: 640, comments: 22 },
    media: [img('food-bowl', 720, 720)],
    categories: ['food'], summary: 'A bowl of roasted squash with chili oil, cooked at home.',
    analysis: analysis({
      what: 'Top-down photo of a bowl of roasted squash, rice and herbs on a wooden table.',
      when: { date: '2026-10-22', time_of_day: 'lunch', occasion: 'Sunday lunch', basis: 'caption' },
      where: { place: 'home kitchen', kind: 'home', basis: 'caption' },
      objects: ['bowl', 'squash', 'chili oil', 'coriander', 'wooden table'], mood: 'cosy', language: 'English',
      context: 'Pairs with the cooking reel that shows the recipe.', keywords: ['squash', 'recipe', 'lunch'],
    }),
  }),
  base({
    id: 'ig_3400000000000000006', kind: 'story', taken_at: at(55),
    media: [vid('story-market', 540, 960, 6)],
    stickers: [{ type: 'location', text: 'Mercado Central', extra: {} }, { type: 'music', text: 'Feira - Sample Band', extra: {} }],
    highlights: [{ id: 'hl_9001', title: 'Travel' }, { id: 'hl_9002', title: 'Food' }],
    music: { title: 'Feira', artist: 'Sample Band' },
    categories: ['food', 'travel'], summary: 'A walk through a covered market past fruit stalls.',
    analysis: analysis({
      people: [{ who: null, description: 'a stall keeper in a green apron', basis: 'description only', role: 'vendor', appears: [{ media: 0, from: 2, to: 4 }] }],
      what: 'The camera walks between fruit stalls in a covered market.',
      events: [{ media: 0, at: 0.5, text: 'Entering the market hall' }, { media: 0, at: 2.4, text: 'Stall with stacked oranges' }, { media: 0, at: 4.6, text: 'Pan up to the iron roof' }],
      where: { place: 'Mercado Central', kind: 'market', country: 'Portugal', basis: 'location sticker' },
      objects: ['oranges', 'iron roof', 'crates'], music: 'Feira - Sample Band', mood: 'busy, bright', language: 'none',
      context: 'In both the Travel and Food highlights.', keywords: ['market', 'fruit'],
    }),
  }),
  base({
    id: 'ig_3400000000000000007', kind: 'post', shortcode: 'DMockPost2', source_url: 'https://www.instagram.com/p/DMockPost2/',
    taken_at: at(80), caption: 'This is the climb we\'re doing next month. Who\'s in? 🏔 (via @mountainclub)',
    mentions: ['mountainclub'], counts: { likes: 410, comments: 35 },
    media: [img('mountain-post', 720, 900)],
    repost_of: {
      author: 'mountainclub', author_name: 'Mountain Club (sample)', shortcode: 'DMockOrig2', source_url: 'https://www.instagram.com/p/DMockOrig2/',
      taken_at: at(120), caption: 'The north ridge in two frames. Route notes in our bio.', media: [img('mountain-orig-1', 720, 900), img('mountain-orig-2', 720, 900)],
    },
    categories: ['nature', 'friends'], summary: 'A repost of Mountain Club\'s north-ridge photos, inviting friends to the climb.',
    analysis: analysis({
      what: 'A repost of a two-photo post about a mountain ridge route, with the owner\'s invitation in the caption.',
      where: { place: 'north ridge (unnamed)', kind: 'mountain', basis: 'caption' },
      mood: 'excited', language: 'English', context: 'Plans for a climb next month.', keywords: ['climb', 'ridge', 'plans'],
    }),
  }),
  base({
    id: 'ig_3400000000000000008', kind: 'reel', shortcode: 'DMockReel2', source_url: 'https://www.instagram.com/reel/DMockReel2/',
    taken_at: at(96), caption: 'The squash bowl, start to finish in 10 seconds #recipe #food',
    hashtags: ['recipe', 'food'], counts: { likes: 2210, comments: 87, plays: 51200 },
    music: { title: 'Kitchen Beat', artist: 'Sample Producer' },
    media: [vid('reel-cooking', 540, 960, 10)],
    categories: ['food'], summary: 'A fast recipe reel for roasted squash with chili oil.',
    analysis: analysis({
      people: [{ who: null, description: 'hands of the cook, a ring on the left hand', basis: 'description only', role: 'cook', appears: [{ media: 0, from: 0, to: 10 }] }],
      what: 'A sped-up recipe: squash is cut, roasted, plated on rice and finished with chili oil.',
      events: [
        { media: 0, at: 0, text: 'Cutting the squash' }, { media: 0, at: 2.5, text: 'Into the oven, 220 °C' },
        { media: 0, at: 5, text: 'Rice into the bowl' }, { media: 0, at: 7.5, text: 'Chili oil and coriander' }, { media: 0, at: 9.5, text: 'Final bowl' },
      ],
      on_screen_text: ['220 °C · 35 min', 'chili oil!'],
      speech: { language: 'English', transcript: 'Squash, olive oil, salt. Two-twenty for thirty-five minutes. Rice, squash, chili oil, way too much coriander. Done.' },
      music: 'Kitchen Beat - Sample Producer', mood: 'upbeat', language: 'English',
      context: 'The recipe for the Sunday bowl post.', keywords: ['recipe', 'squash', 'chili oil'],
    }),
  }),
  base({
    id: 'ig_3400000000000000009', kind: 'carousel', shortcode: 'DMockCaro2', source_url: 'https://www.instagram.com/p/DMockCaro2/',
    taken_at: at(140), caption: 'Studio day: a photo and a tiny film #studio #music',
    hashtags: ['studio', 'music'], counts: { likes: 377 },
    media: [img('mix-1', 720, 900), vid('mix-2', 544, 680, 5)],
    categories: ['music'], summary: 'A photo and a short clip from a day in a music studio.',
    analysis: analysis({
      what: 'A purple-lit studio photo followed by a five-second clip of the mixing desk.',
      events: [{ media: 1, at: 1, text: 'Fader moves up' }, { media: 1, at: 3.5, text: 'Light changes to blue' }],
      where: { place: 'recording studio', kind: 'studio', basis: 'caption' },
      objects: ['mixing desk', 'microphone'], mood: 'focused', language: 'English',
      context: 'Mixed media carousel: image then video.', keywords: ['studio', 'mixing'],
    }),
  }),
  base({
    id: 'ig_3400000000000000010', kind: 'story', taken_at: at(150),
    media: [img('story-coffee', 720, 1280)],
    stickers: [{ type: 'question', text: 'Best coffee in town?', extra: {} }],
    highlights: [{ id: 'hl_9002', title: 'Food' }],
    categories: ['food', 'city'], summary: 'Morning coffee and a question sticker asking for recommendations.',
    analysis: analysis({
      what: 'A cup of coffee on a café counter with a question sticker.', on_screen_text: ['Best coffee in town?'],
      when: { time_of_day: 'morning', basis: 'light' }, mood: 'calm', language: 'English', context: '', keywords: ['coffee'],
    }),
  }),
];

const fillerCats = [['nature'], ['city'], ['friends', 'city'], ['travel'], ['music'], ['nature', 'ocean']];
for (let i = 1; i <= 18; i++) {
  const cats = fillerCats[i % fillerCats.length];
  items.push(base({
    id: `ig_34000000000000001${String(i).padStart(2, '0')}`, kind: 'post', shortcode: `DMockF${i}`,
    source_url: `https://www.instagram.com/p/DMockF${i}/`, taken_at: at(160 + i * 30),
    caption: `Archive frame ${i} #${cats[0]}`, hashtags: [cats[0]], counts: { likes: 100 + i * 7 },
    media: [img(`filler-${i}`, 720, 720)], categories: cats, summary: `An abstract colour study, number ${i}.`,
    analysis: analysis({ what: `An abstract gradient image, number ${i} in an older series.`, mood: 'calm', language: 'English', context: 'Older series of colour studies.', keywords: ['gradient', 'colour'] }),
  }));
}

const highlights = [
  { id: 'hl_9001', title: 'Travel', cover: `${M}hl-travel.jpg`, item_ids: ['ig_3400000000000000003', 'ig_3400000000000000006'], updated_at: stamp.updated_at },
  { id: 'hl_9002', title: 'Food', cover: `${M}hl-food.jpg`, item_ids: ['ig_3400000000000000006', 'ig_3400000000000000010'], updated_at: stamp.updated_at },
  { id: 'hl_9003', title: 'Ocean', cover: `${M}hl-ocean.jpg`, item_ids: ['ig_3400000000000000004'], updated_at: stamp.updated_at },
];

const catNames = { travel: 'Travel', food: 'Food', nature: 'Nature', city: 'City', friends: 'Friends', ocean: 'Ocean', music: 'Music' };
const catDesc = {
  travel: 'Trips, roads and places away from home.', food: 'Cooking, markets and what is on the plate.', nature: 'Coasts, dunes, mountains and the sky.',
  city: 'Streets, buildings and city life.', friends: 'Time with the people around.', ocean: 'The sea and what lives in it.', music: 'Studios, songs and sound.',
};
const categories = Object.keys(catNames)
  .map((slug) => ({ slug, name: catNames[slug], description: catDesc[slug], count: items.filter((x) => x.categories.includes(slug)).length }))
  .sort((a, b) => b.count - a.count);

const profile = {
  username: 'earth.empire', full_name: 'Earth Empire', bio: 'Sample archive for development.\nEverything here is mock data.',
  avatar: `${M}avatar.jpg`, links: ['https://empire.earth'], counts: { posts: items.filter((x) => x.kind !== 'story').length, followers: 12840, following: 311 },
  updated_at: stamp.updated_at,
};

for (const it of items) {
  if (it.description !== undefined) continue;
  const a = it.analysis || {};
  it.description = [a.what, a.where?.place && `It was ${a.when?.time_of_day ? a.when.time_of_day + ' at ' : 'at '}${a.where.place}${a.where.country ? ', ' + a.where.country : ''}.`, it.repost_of && `The original is by @${it.repost_of.author}.`, a.context].filter(Boolean).join(' ') || null;
}
items.sort((a, b) => b.taken_at.localeCompare(a.taken_at));
const out = fileURLToPath(new URL('../mock/fixture.json', import.meta.url));
writeFileSync(out, JSON.stringify({ profile, highlights, categories, items }, null, 1) + '\n');
console.log(`wrote ${out}: ${items.length} items`);
