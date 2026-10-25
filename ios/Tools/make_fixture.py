#!/usr/bin/env python3
"""Writes the app's development fixture: ios/Fixture/fixture.json plus small gradient media.

The JSON follows CONTRACT.md exactly (Profile, Highlights, Categories, Items with analysis and a
repost), so the app and its tests run on the same shapes the API will serve. Media URLs point at
https://media.empire.earth/<key>; in sample-data mode the app reads <key> from
Fixture/media/<key> in its bundle instead.

Run from anywhere: python3 ios/Tools/make_fixture.py  (needs ffmpeg for the media).
"""
import json
import os
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "Fixture")
MEDIA = "https://media.empire.earth/"
USER = "earthempire"

PALETTE = [
    ("0xff7a18", "0xaf002d"), ("0x00c6ff", "0x0072ff"), ("0x56ab2f", "0xa8e063"),
    ("0xf7971e", "0xffd200"), ("0x8e2de2", "0x4a00e0"), ("0xee0979", "0xff6a00"),
    ("0x1d976c", "0x93f9b9"), ("0x355c7d", "0xc06c84"), ("0xe96443", "0x904e95"),
    ("0x3a1c71", "0xffaf7b"), ("0x00b09b", "0x96c93d"), ("0x141e30", "0x243b55"),
]
_color = [0]


def next_colors():
    c = PALETTE[_color[0] % len(PALETTE)]
    _color[0] += 1
    return c


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def image(key, w, h, colors, seed):
    path = os.path.join(OUT, "media", key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c0, c1 = colors
    ffmpeg("-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0={c0}:c1={c1}:seed={seed}",
           "-frames:v", "1", "-q:v", "6", path)


def video(key, w, h, colors, seed, seconds):
    path = os.path.join(OUT, "media", key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c0, c1 = colors
    ffmpeg("-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0={c0}:c1={c1}:seed={seed}:speed=0.05:d={seconds}:r=24",
           "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "38", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "32k", "-shortest", "-movflags", "+faststart", path)


def media_list(item_id, specs):
    """specs: [("image"|"video", w, h, seconds|None)]"""
    out = []
    for n, (kind, w, h, secs) in enumerate(specs):
        colors = next_colors()
        seed = zlib.crc32((item_id + str(n)).encode()) % 100000
        thumb_key = f"items/{item_id}/{n}.thumb.jpg"
        if kind == "image":
            key = f"items/{item_id}/{n}.jpg"
            image(key, w // 2, h // 2, colors, seed)
        else:
            key = f"items/{item_id}/{n}.mp4"
            video(key, (w // 2) // 2 * 2, (h // 2) // 2 * 2, colors, seed, secs)
        image(thumb_key, 360, int(360 * h / w), colors, seed)
        out.append({"type": kind, "url": MEDIA + key, "thumbnail": MEDIA + thumb_key,
                    "width": w, "height": h, "duration": secs})
    return out


def analysis(what, *, people=(), events=(), when=None, where=None, objects=(), animals=(), brands=(),
             on_screen_text=(), speech=None, music=None, mood="", context="", keywords=(), language="en"):
    return {
        "people": list(people), "what": what, "events": list(events),
        "when": when or {"date": None, "time_of_day": None, "season": None, "occasion": None, "basis": "taken_at"},
        "where": where or {"place": None, "kind": None, "country": None, "basis": None},
        "objects": list(objects), "animals": list(animals), "brands": list(brands),
        "on_screen_text": list(on_screen_text), "speech": speech, "music": music,
        "mood": mood, "language": language, "context": context, "keywords": list(keywords),
        "model": "claude-opus-5-5", "analyzed_at": "2026-10-20T09:00:00Z",
    }


def item(pk, kind, taken_at, caption, media, *, shortcode=None, categories=(), summary=None, an=None,
         location=None, music=None, highlights=(), repost_of=None, tagged=(), stickers=(), counts=None,
         alt_text=None):
    words = (caption or "").split()
    path = {"post": "p", "carousel": "p", "reel": "reel"}.get(kind)
    return {
        "id": f"ig_{pk}", "kind": kind, "shortcode": shortcode,
        "source_url": f"https://www.instagram.com/{path}/{shortcode}/" if shortcode and path else None,
        "taken_at": taken_at, "caption": caption,
        "hashtags": [w[1:].strip(".,!") for w in words if w.startswith("#")],
        "mentions": [w[1:].strip(".,!") for w in words if w.startswith("@")],
        "tagged_users": list(tagged), "location": location, "music": music, "alt_text": alt_text,
        "stickers": list(stickers), "counts": counts or {}, "media": media,
        "highlights": list(highlights), "repost_of": repost_of,
        "categories": list(categories), "summary": summary, "analysis": an,
        "extra": {}, "collected_at": "2026-10-20T08:00:00Z", "updated_at": "2026-10-20T09:00:00Z",
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    LISBON = {"name": "Lisbon, Portugal", "id": "106339232736050", "lat": 38.7223, "lng": -9.1393}
    ERICEIRA = {"name": "Ericeira", "id": "213475620", "lat": 38.9627, "lng": -9.4157}
    KYIV = {"name": "Kyiv, Ukraine", "id": "111227078906045", "lat": 50.4501, "lng": 30.5234}
    HL_TRAVEL = {"id": "hl_17900000000000001", "title": "Travel"}
    HL_FOOD = {"id": "hl_17900000000000002", "title": "Food"}
    HL_SURF = {"id": "hl_17900000000000003", "title": "Surf"}

    items = []

    surf_media = media_list("ig_3400000000000000012", [("video", 1080, 1920, 8.0)])
    items.append(item(
        "3400000000000000012", "reel", "2026-10-18T07:42:00Z",
        "First light at Ribeira d'Ilhas with @marta.waves. Cold water, warm hearts #surf #ericeira",
        surf_media, shortcode="DQs1rFa", location=ERICEIRA,
        music={"title": "Sunrise Drive", "artist": "Coastline"},
        categories=["surf", "travel", "friends"],
        summary="A dawn surf session at Ribeira d'Ilhas with Marta, from paddle-out to the last wave.",
        tagged=[{"username": "marta.waves", "x": None, "y": None}],
        counts={"likes": 812, "comments": 34, "plays": 15400},
        an=analysis(
            "Two surfers paddle out at sunrise, catch a few waves on a small clean swell and walk back up the beach laughing.",
            people=[
                {"who": "@earthempire", "description": "the account owner, in a black wetsuit", "basis": "caption",
                 "role": "surfer, filming", "appears": [{"media": 0, "from": 0.0, "to": 3.0}]},
                {"who": "@marta.waves", "description": "surfer with a yellow longboard", "basis": "tag",
                 "role": "surfer", "appears": [{"media": 0, "from": 2.0, "to": 8.0}]},
                {"who": None, "description": "a lifeguard on the tower in a red jacket", "basis": "description only",
                 "role": "bystander", "appears": [{"media": 0, "from": 6.5, "to": 7.5}]},
            ],
            events=[
                {"media": 0, "at": 0.0, "text": "Sunrise over the bay, boards under arm"},
                {"media": 0, "at": 2.4, "text": "Paddle-out through the whitewater"},
                {"media": 0, "at": 4.8, "text": "Marta takes the first wave of the set"},
                {"media": 0, "at": 6.9, "text": "Walking back up the beach"},
            ],
            when={"date": "2026-10-18", "time_of_day": "dawn", "season": "autumn", "occasion": None,
                  "basis": "taken_at and low sun"},
            where={"place": "Ribeira d'Ilhas, Ericeira", "kind": "beach", "country": "Portugal",
                   "basis": "location"},
            objects=["surfboard", "longboard", "wetsuit", "lifeguard tower"],
            on_screen_text=["Ribeira d'Ilhas"],
            speech={"language": "en", "transcript": "Okay, it's freezing. [laughs] Marta, go, go, go! That was the one. Best wave of the week."},
            music="Sunrise Drive by Coastline", mood="joyful, energetic",
            context="Part of a recurring series of dawn sessions in Ericeira; Marta appears in several earlier surf posts.",
            keywords=["surf", "sunrise", "Ericeira", "World Surfing Reserve"])))

    repost_media = media_list("ig_3400000000000000011", [("image", 1080, 1920, None)])
    original_media = media_list("ig_3400000000000000011_orig", [("video", 1080, 1920, 6.0)])
    for m in original_media:  # the original is re-hosted beside the item that shares it
        m["url"] = m["url"].replace("ig_3400000000000000011_orig/0", "ig_3400000000000000011/orig.0")
        m["thumbnail"] = m["thumbnail"].replace("ig_3400000000000000011_orig/0", "ig_3400000000000000011/orig.0")
    os.makedirs(os.path.join(OUT, "media/items/ig_3400000000000000011"), exist_ok=True)
    for ext in ("mp4", "thumb.jpg"):
        os.replace(os.path.join(OUT, f"media/items/ig_3400000000000000011_orig/0.{ext}"),
                   os.path.join(OUT, f"media/items/ig_3400000000000000011/orig.0.{ext}"))
    os.rmdir(os.path.join(OUT, "media/items/ig_3400000000000000011_orig"))
    items.append(item(
        "3400000000000000011", "story", "2026-10-17T19:05:00Z", None, repost_media,
        categories=["surf", "reposts"], highlights=[HL_SURF],
        summary="A shared reel by @nazare.daily of a big-wave set at Nazaré.",
        stickers=[{"type": "mention", "text": "@nazare.daily", "extra": {}}],
        repost_of={
            "author": "nazare.daily", "author_name": "Nazaré Daily", "shortcode": "DQq9xYz",
            "source_url": "https://www.instagram.com/reel/DQq9xYz/", "taken_at": "2026-10-17T15:30:00Z",
            "caption": "The North Canyon woke up today. 20 m faces at Praia do Norte #nazare #bigwave",
            "media": original_media,
        },
        an=analysis(
            "The owner shares a reel of tow-in surfers riding huge waves at Praia do Norte, Nazaré.",
            people=[{"who": None, "description": "a tow-in surfer on a jet-ski rope", "basis": "description only",
                     "role": "surfer", "appears": [{"media": 0, "from": 0.0, "to": 6.0}]}],
            where={"place": "Praia do Norte, Nazaré", "kind": "beach", "country": "Portugal", "basis": "caption"},
            objects=["jet ski", "surfboard", "lighthouse"], on_screen_text=["Nazaré Daily"],
            mood="awe", context="Shared from @nazare.daily; the owner follows big-wave season every autumn.",
            keywords=["Nazaré", "big wave", "repost"])))

    items.append(item(
        "3400000000000000010", "carousel", "2026-10-12T13:20:00Z",
        "Three days of pastéis, azulejos and hills in Lisbon. Swipe for the best one #lisbon #food",
        media_list("ig_3400000000000000010", [("image", 1080, 1350, None), ("image", 1080, 1350, None),
                                              ("video", 1080, 1350, 5.0), ("image", 1080, 1080, None)]),
        shortcode="DQb7kLm", location=LISBON, categories=["travel", "food", "city"],
        summary="A Lisbon weekend in four frames: tiles, a tram, a pastry counter and the view from a miradouro.",
        counts={"likes": 1290, "comments": 51},
        alt_text="Blue and white azulejo tiles on a building in Alfama",
        an=analysis(
            "A carousel from a weekend in Lisbon: a tiled façade, a yellow tram climbing a hill, a short clip of pastéis de nata coming out of the oven, and the city at sunset.",
            people=[{"who": None, "description": "a baker in a white cap", "basis": "description only",
                     "role": "baker", "appears": [{"media": 2, "from": 0.0, "to": 5.0}]}],
            events=[{"media": 2, "at": 1.0, "text": "Tray of pastéis de nata comes out of the oven"},
                    {"media": 2, "at": 3.5, "text": "Cinnamon dusted over the tarts"}],
            when={"date": "2026-10-10 to 2026-10-12", "time_of_day": "afternoon", "season": "autumn",
                  "occasion": "weekend trip", "basis": "caption"},
            where={"place": "Alfama and Belém, Lisbon", "kind": "city", "country": "Portugal",
                   "basis": "location, landmark"},
            objects=["azulejo tiles", "tram 28", "pastéis de nata", "oven"], brands=["Pastéis de Belém"],
            on_screen_text=["Pastéis de Belém", "28 Prazeres"], mood="warm, relaxed",
            context="Third trip to Lisbon in the archive; follows the Ericeira surf series.",
            keywords=["Lisbon", "azulejos", "tram 28", "pastel de nata"])))

    items.append(item(
        "3400000000000000009", "story", "2026-10-11T10:15:00Z", None,
        media_list("ig_3400000000000000009", [("image", 1080, 1920, None)]),
        categories=["food", "travel"], highlights=[HL_FOOD, HL_TRAVEL],
        summary="Breakfast at a Lisbon café: a bica and two pastéis de nata.",
        stickers=[{"type": "location", "text": "Lisbon, Portugal", "extra": {}},
                  {"type": "poll", "text": "Cinnamon on top?", "extra": {"options": ["Yes", "Always"]}}],
        location=LISBON,
        an=analysis("A close-up of a café table with an espresso and two custard tarts, with a poll asking about cinnamon.",
                    where={"place": "a café in Lisbon", "kind": "café", "country": "Portugal", "basis": "location sticker"},
                    objects=["espresso", "pastéis de nata", "marble table"],
                    on_screen_text=["Cinnamon on top?"], mood="cosy",
                    keywords=["breakfast", "bica", "pastel de nata"])))

    items.append(item(
        "3400000000000000008", "story", "2026-10-11T18:40:00Z", None,
        media_list("ig_3400000000000000008", [("video", 1080, 1920, 5.0)]),
        categories=["travel", "city"], highlights=[HL_TRAVEL], location=LISBON,
        summary="Tram 28 rattling up a hill in Alfama at golden hour.",
        an=analysis("A yellow tram climbs a narrow street in Alfama as the sun sets.",
                    events=[{"media": 0, "at": 1.5, "text": "Tram rounds the corner"}],
                    where={"place": "Alfama, Lisbon", "kind": "city", "country": "Portugal", "basis": "landmark"},
                    objects=["tram"], mood="nostalgic", keywords=["tram 28", "golden hour"])))

    items.append(item(
        "3400000000000000007", "post", "2026-09-28T16:00:00Z",
        "Home for the weekend. The chestnuts are out on Khreshchatyk again #kyiv #autumn",
        media_list("ig_3400000000000000007", [("image", 1080, 1350, None)]),
        shortcode="DPz3aQw", location=KYIV, categories=["city", "family"],
        summary="An autumn afternoon in Kyiv, chestnut trees turning on Khreshchatyk.",
        counts={"likes": 2034, "comments": 88},
        an=analysis("A wide street lined with chestnut trees in autumn colours, people walking on a closed-off avenue.",
                    when={"date": "2026-09-28", "time_of_day": "afternoon", "season": "autumn",
                          "occasion": "weekend at home", "basis": "caption and foliage"},
                    where={"place": "Khreshchatyk, Kyiv", "kind": "city", "country": "Ukraine", "basis": "caption, location"},
                    objects=["chestnut trees", "street lamps"], mood="calm, homesick",
                    context="The owner visits Kyiv most autumns; earlier posts show the same street.",
                    keywords=["Kyiv", "Khreshchatyk", "chestnuts"])))

    items.append(item(
        "3400000000000000006", "reel", "2026-09-14T12:00:00Z",
        "How we make varenyky at my grandmother's, step by step (and why she never measures anything)",
        media_list("ig_3400000000000000006", [("video", 1080, 1920, 7.0)]),
        shortcode="DPl2bNv", categories=["food", "family"],
        summary="Grandmother shows how she makes varenyky by hand, from dough to boiling.",
        counts={"likes": 5630, "comments": 240, "plays": 88200},
        an=analysis(
            "An older woman rolls dough, cuts circles with a glass, fills them with potato and folds varenyky, then drops them into boiling water.",
            people=[{"who": "Grandmother Halyna", "description": "older woman in a floral apron",
                     "basis": "caption", "role": "cook",
                     "appears": [{"media": 0, "from": 0.0, "to": 7.0}]}],
            events=[{"media": 0, "at": 0.5, "text": "Rolling out the dough"},
                    {"media": 0, "at": 2.5, "text": "Cutting circles with a glass"},
                    {"media": 0, "at": 4.0, "text": "Filling and pinching the edges"},
                    {"media": 0, "at": 6.0, "text": "Into the boiling water"}],
            when={"date": None, "time_of_day": "midday", "season": None, "occasion": "family lunch", "basis": "light"},
            where={"place": "grandmother's kitchen", "kind": "home", "country": "Ukraine", "basis": "speech"},
            objects=["rolling pin", "glass", "flour", "pot"],
            speech={"language": "uk", "transcript": "Не міряю нічого, все на око. Тісто має бути як вушко. [She never measures anything; the dough should feel like an earlobe.]"},
            mood="warm, homely", language="uk",
            context="Named in the caption of an earlier post as the owner's grandmother Halyna.",
            keywords=["varenyky", "recipe", "Ukrainian food", "grandmother"])))

    items.append(item(
        "3400000000000000005", "post", "2026-08-30T08:10:00Z",
        "Reel of the summer, by the one and only @alex.films. Watch till the end",
        media_list("ig_3400000000000000005", [("image", 1080, 1350, None)]),
        shortcode="DPa1cOp", categories=["reposts", "travel"],
        summary="A post sharing @alex.films' summer road-trip reel.",
        repost_of={
            "author": "alex.films", "author_name": "Alex Moreno", "shortcode": "DOx8pQr",
            "source_url": "https://www.instagram.com/reel/DOx8pQr/", "taken_at": "2026-08-29T20:00:00Z",
            "caption": "Ten countries, one van, zero plans. Summer 2026.",
            "media": [{"type": "image", "url": MEDIA + "items/ig_3400000000000000005/0.jpg",
                       "thumbnail": MEDIA + "items/ig_3400000000000000005/0.thumb.jpg",
                       "width": 1080, "height": 1350, "duration": None}],
        },
        an=analysis("A shared reel from Alex Moreno's van trip across Europe.",
                    people=[{"who": "@alex.films", "description": "filmmaker behind the van trip", "basis": "mention",
                             "role": "author of the original", "appears": []}],
                    mood="adventurous", context="Repost; the original is by @alex.films.",
                    keywords=["road trip", "van life", "repost"])))

    for n, (date, cap, cats, summ, hl) in enumerate([
        ("2026-08-12T09:00:00Z", "Morning run along the Tagus #running", ["sport", "city"], "A sunrise run along the river in Lisbon.", None),
        ("2026-07-30T18:30:00Z", "Garden harvest: more tomatoes than we can eat #garden", ["family", "food"], "A basket of tomatoes from the family garden.", None),
        ("2026-07-02T11:00:00Z", "Packing light this time #travel", ["travel"], "A flat-lay of a small backpack's contents before a trip.", HL_TRAVEL),
        ("2026-06-15T20:45:00Z", "Longest day, longest swim #summer", ["sport", "travel"], "Swimming at sunset on the longest day of the year.", None),
        ("2026-05-20T14:00:00Z", "New board day #surf", ["surf"], "Unwrapping a new surfboard.", HL_SURF),
        ("2026-04-02T10:00:00Z", "Spring in the city #kyiv", ["city"], "Magnolias in bloom by the botanical garden.", None),
    ]):
        pk = f"33000000000000000{n:02d}"
        items.append(item(
            pk, "post", date, cap,
            media_list(f"ig_{pk}", [("image", 1080, 1080, None)]),
            shortcode=f"DO{n}aaa{n}", categories=cats, summary=summ, highlights=[hl] if hl else [],
            counts={"likes": 300 + 37 * n, "comments": 5 + n},
            an=analysis(summ, mood="bright", keywords=cats)))

    items.sort(key=lambda i: i["taken_at"], reverse=True)

    def ids_in(hl):
        return [i["id"] for i in sorted(items, key=lambda i: i["taken_at"]) if any(h["id"] == hl["id"] for h in i["highlights"])]

    highlights = []
    for hl, seed in ((HL_TRAVEL, 11), (HL_FOOD, 12), (HL_SURF, 13)):
        key = f"highlights/{hl['id']}/cover.jpg"
        image(key, 320, 320, next_colors(), seed)
        highlights.append({"id": hl["id"], "title": hl["title"], "cover": MEDIA + key,
                           "item_ids": ids_in(hl), "updated_at": "2026-10-18T00:00:00Z"})

    names = {"travel": ("Travel", "Trips, places and the road between them."),
             "food": ("Food", "Cooking, cafés and family recipes."),
             "surf": ("Surf", "Sessions, boards and big-wave season."),
             "city": ("City", "Streets of Lisbon and Kyiv."),
             "family": ("Family", "Home, grandparents and the garden."),
             "friends": ("Friends", "People the owner spends time with."),
             "sport": ("Sport", "Running, swimming and training."),
             "reposts": ("Reposts", "Reels and posts shared from other accounts, credited to their authors.")}
    categories = [{"slug": s, "name": n, "description": d,
                   "count": sum(1 for i in items if s in i["categories"])} for s, (n, d) in names.items()]
    categories.sort(key=lambda c: -c["count"])

    image("profile/avatar.jpg", 320, 320, ("0x0f2027", "0x2c5364"), 7)
    profile = {"username": USER, "full_name": "Earth Empire", "bio": "Surf, food, family and cities.\nThe whole archive, analyzed: empire.earth",
               "avatar": MEDIA + "profile/avatar.jpg", "links": ["https://empire.earth"],
               "counts": {"posts": len([i for i in items if i["kind"] != "story"]), "followers": 4821, "following": 512},
               "updated_at": "2026-10-20T08:00:00Z"}

    with open(os.path.join(OUT, "fixture.json"), "w") as f:
        json.dump({"profile": profile, "highlights": highlights, "categories": categories, "items": items},
                  f, ensure_ascii=False, indent=1)
    print(f"{len(items)} items, {len(highlights)} highlights, {len(categories)} categories -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
