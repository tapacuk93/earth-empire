"""What a post on X or Facebook says: the description, the original caption, the date, the
highlight names, the categories as hashtags and, for a repost, the credit. Plus which media goes
up (a repost carries the original's media)."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

X_LIMIT = 280
X_URL_LEN = 23
URL_RE = re.compile(r"https?://\S+")


@dataclass
class Post:
    item_id: str
    header: str            # date, highlights
    description: str
    caption: str
    credit: str            # "Reel by @author https://..." or ""
    hashtags: str
    media: list[dict] = field(default_factory=list)   # [{"type", "url", "duration"}]

    def full_text(self) -> str:
        parts = [self.header, self.credit, self.description,
                 f"Original caption:\n{self.caption}" if self.caption else "", self.hashtags]
        return "\n\n".join(p for p in parts if p)


def _date(iso: str) -> str:
    try:
        d = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        return f"{d.day} {d:%B %Y}"
    except ValueError:
        return iso[:10]


def hashtag(slug: str) -> str:
    return "#" + "".join(w.capitalize() if i else w for i, w in enumerate(slug.split("-")))


def build(item: dict) -> Post:
    """`item` as the API renders it (URLs absolute)."""
    kind_word = {"reel": "Reel", "story": "Story", "carousel": "Post", "post": "Post"}.get(item.get("kind"), "Post")
    header = f"{kind_word} from {_date(item['taken_at'])}"
    hls = [h.get("title") for h in item.get("highlights") or [] if isinstance(h, dict) and h.get("title")]
    if hls:
        header += " · Highlights: " + ", ".join(dict.fromkeys(hls))
    rep = item.get("repost_of") or None
    credit = ""
    media = item.get("media") or []
    if rep:
        src_kind = "Reel" if "/reel/" in (rep.get("source_url") or "") or any(
            m.get("type") == "video" for m in rep.get("media") or []) else "Post"
        credit = f"{src_kind} by @{rep.get('author') or 'unknown'}"
        if rep.get("author_name"):
            credit += f" ({rep['author_name']})"
        if rep.get("source_url"):
            credit += " " + rep["source_url"]
        if rep.get("media"):
            media = rep["media"]   # the original's video goes up, credited
    tags = " ".join(hashtag(s) for s in item.get("categories") or [])
    return Post(item_id=item["id"], header=header, description=(item.get("description") or "").strip(),
                caption=(item.get("caption") or "").strip(), credit=credit, hashtags=tags,
                media=[{"type": m.get("type"), "url": m.get("url"), "duration": m.get("duration")}
                       for m in media if m.get("url")])


# ------------------------------------------------------------------ X
def _cp_weight(ch: str) -> int:
    o = ord(ch)
    if o <= 4351 or 8192 <= o <= 8205 or 8208 <= o <= 8223 or 8242 <= o <= 8247:
        return 1
    return 2


def x_len(text: str) -> int:
    """X's weighted length: most Latin/Cyrillic 1, CJK and emoji 2, every URL 23."""
    text = unicodedata.normalize("NFC", text)
    n = 0
    pos = 0
    for m in URL_RE.finditer(text):
        n += sum(_cp_weight(c) for c in text[pos:m.start()]) + X_URL_LEN
        pos = m.end()
    return n + sum(_cp_weight(c) for c in text[pos:])


def _split_words(text: str, limit: int) -> list[str]:
    words = []
    for w in text.split():
        while x_len(w) > limit - 1:          # a word longer than a tweet
            cut = limit - 1
            while x_len(w[:cut]) > limit - 1:
                cut -= 1
            words.append(w[:cut])
            w = w[cut:]
        words.append(w)
    out, cur = [], ""
    for w in words:
        cand = f"{cur} {w}" if cur else w
        if x_len(cand) <= limit - 1:       # room for the "…"
            cur = cand
        else:
            out.append(cur + "…")
            cur = w
    if cur:
        out.append(cur)
    return out


def _split(text: str, limit: int) -> list[str]:
    """Split text into pieces of at most `limit`, at sentence, then word boundaries."""
    out, cur = [], ""
    for tok in re.split(r"(?<=[.!?…])\s+|\n+", text):
        tok = tok.strip()
        if not tok:
            continue
        cand = f"{cur} {tok}" if cur else tok
        if x_len(cand) <= limit:
            cur = cand
            continue
        if cur:
            out.append(cur)
        if x_len(tok) <= limit:
            cur = tok
        else:
            pieces = _split_words(tok, limit)
            out += pieces[:-1]
            cur = pieces[-1]
    if cur:
        out.append(cur)
    return out


def _units(text: str) -> list[str]:
    return [u.strip() for u in re.split(r"(?<=[.!?…])\s+", text) if u.strip()]


def x_thread(post: Post, limit: int = X_LIMIT) -> list[dict]:
    """[{"text", "media": [indexes into post.media]}]. Sentences are packed as tightly as the
    limit allows (every tweet costs money); paragraphs keep a blank line between them."""
    paragraphs = [[post.header + ("\n" + post.credit if post.credit else "")], _units(post.description),
                  _units("“" + post.caption + "”") if post.caption else [], [post.hashtags] if post.hashtags else []]
    budget = limit - 8   # room for " (nn/nn)"
    tweets: list[str] = []
    cur = ""
    for para in paragraphs:
        for k, unit in enumerate(para):
            sep = "" if not cur else (" " if k else "\n\n")
            if x_len(cur + sep + unit) <= budget:
                cur = cur + sep + unit
                continue
            if cur:
                tweets.append(cur)
            pieces = [unit] if x_len(unit) <= budget else _split_words(unit, budget)
            tweets += pieces[:-1]
            cur = pieces[-1]
    if cur:
        tweets.append(cur)
    if len(tweets) > 1:
        tweets = [f"{t} ({i + 1}/{len(tweets)})" for i, t in enumerate(tweets)]
    # Media: a video goes alone, images four at a time.
    groups, imgs = [], []
    for i, m in enumerate(post.media):
        if m["type"] == "video":
            if imgs:
                groups.append(imgs)
                imgs = []
            groups.append([i])
        else:
            imgs.append(i)
            if len(imgs) == 4:
                groups.append(imgs)
                imgs = []
    if imgs:
        groups.append(imgs)
    thread = [{"text": t, "media": []} for t in tweets] or [{"text": "", "media": []}]
    for gi, g in enumerate(groups):
        if gi < len(thread):
            thread[gi]["media"] = g
        else:
            thread.append({"text": "", "media": g})
    return thread


def facebook_text(post: Post) -> str:
    return post.full_text()
