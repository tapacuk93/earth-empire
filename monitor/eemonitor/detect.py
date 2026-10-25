"""Detection over a transcript: the name "Taras" (fuzzy, over Latin and Cyrillic) and Ukrainian or
Russian speech where a source does not normally speak it.

Pure functions over the transcript shape `transcribe.transcribe()` returns, so they are tested
without audio. Nothing here says a match is certain: every hit carries the scores it was built
from and notes on why it may be a coincidence.
"""
from __future__ import annotations

import re
import unicodedata

TARGET = "taras"

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "є": "ye", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "u",
}

# Inflections and diminutives of the given name itself (uk, ru, be, pl, cs and Latin spellings).
NAME_FORMS = {
    "taras", "tarasa", "tarasu", "tarasom", "tarase", "tarasovi", "tarasie", "tarasem", "tarasowi",
    "tarasik", "tarasyk", "tarasika", "tarasyka", "tarasiku", "tarasyku", "tarasikom", "tarasykom",
    "tarasko", "taraska", "tarass", "tarasъ", "tarasie",
}
# Words built on the name: surnames (Tarasov, Tarasenko, Tarasiuk...), places (Tarasivka).
DERIVED_RE = re.compile(r"^taras(ov|ova|ovo|ovy|enk|iuk|yuk|uk|evi|evy|ovi|ovy|kin|chuk|ivk|ivsk|in|yn)")
DERIVED_HINT = {"ov": "surname", "enk": "surname", "iuk": "surname", "yuk": "surname", "uk": "surname",
                "evi": "surname", "evy": "surname", "kin": "surname", "chuk": "surname", "ivk": "place name",
                "ivsk": "place name"}
# Common words that sound like "Taras" (by the phonetic key below) and are usually not the name.
LOOKALIKES = {
    "terrace": 0.35, "terraces": 0.3, "terras": 0.4, "terrasse": 0.35, "tarras": 0.6, "taurus": 0.3,
    "torus": 0.15, "tarasque": 0.25, "tarascon": 0.2, "tarascan": 0.2, "tarasca": 0.25, "taraz": 0.35,
    "terasa": 0.3, "terasy": 0.25, "tarazona": 0.15, "tarrasa": 0.3, "terrassa": 0.3, "tiras": 0.35,
    "tirras": 0.3, "terrace's": 0.3, "tara's": 0.45, "tiaras": 0.25, "tiara's": 0.25, "tarot's": 0.1,
}
# A name that follows "Taras" and says which Taras it is - real, but a well-known reference.
KNOWN_FULL_NAMES = {
    "shevchenko": "Taras Shevchenko, the Ukrainian poet (streets, universities and awards carry his name)",
    "bulba": "Taras Bulba, Gogol's novel and its hero",
    "kachka": "Taras Kachka, Ukraine's deputy minister / trade representative",
    "stepanenko": "Taras Stepanenko, the footballer",
    "chornovil": "Taras Chornovil, the politician",
    "kuzio": "Taras Kuzio, the political scientist",
    "vysotskyi": "Taras Vysotskyi, Ukraine's deputy minister",
    "melnychuk": "Taras Melnychuk, Cabinet of Ministers' representative in the Rada",
}
NOUN_CONTEXT = {"the", "a", "an", "on", "roof", "rooftop", "garden", "this", "that", "our", "la", "le", "une",
                "die", "der", "auf", "na", "v", "u", "на", "в", "террасе", "терраса"}

EAST_SLAVIC = ("uk", "ru", "be")
UK_ONLY = set("іїєґ")
RU_ONLY = set("ыэъё")


def translit(word: str) -> str:
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(c for c in w if not unicodedata.combining(c) or c == "̆")
    w = unicodedata.normalize("NFC", w)
    return "".join(_CYR.get(c, c) for c in w)


def clean(word: str) -> str:
    """Lowercase Latin form, punctuation stripped except an inner apostrophe."""
    t = translit(word.strip()).replace("\u2019", "'")
    return re.sub(r"[^\w']+", "", t).strip("'")


def phonetic(t: str) -> str:
    """A rough sound key: doubled letters merged, c before e/i/y as s, z as s, vowels by class."""
    t = t.replace("'", "")
    t = re.sub(r"c(?=[eiy])", "s", t)
    t = re.sub(r"(ce|se|ze)$", "s", t)
    t = t.replace("z", "s").replace("c", "k").replace("th", "t").replace("ph", "f")
    t = re.sub(r"[aeiouy]+", "a", t)
    t = re.sub(r"(.)\1+", r"\1", t)
    return t


def lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class Matcher:
    """One phrase, compiled (phrases.variants): its variants by position, for scoring tokens."""

    def __init__(self, compiled: dict):
        self.text = compiled["text"]
        self.exact = {v["norm"]: v for v in compiled["compiled"]}
        self.k = max((len(self.text.split()), 1))
        self.pos: list[dict[str, tuple[float, str]]] = [dict() for _ in range(self.k)]
        self.bases = [clean(w) for w in self.text.split()]
        for v in compiled["compiled"]:
            parts = v["norm"].split()
            if len(parts) != self.k:
                continue
            for p, w in enumerate(parts):
                sc = (0.9 if v["kind"] in ("form", "translit") else 0.6 if v["kind"] == "claude" else 0.55)
                if w not in self.pos[p] or self.pos[p][w][0] < sc:
                    self.pos[p][w] = (sc, v["kind"])
        self.phon = [{phonetic(w) for w, (sc, kind) in self.pos[p].items() if kind == "form"} for p in range(self.k)]
        self.taras = "taras" in self.bases

    def word(self, p: int, token: str) -> tuple[float, str] | None:
        """How much one token sounds like word p of the phrase, and why."""
        t = clean(token)
        if not t or len(t) < 3:
            return None
        bare = t.replace("'", "")
        base = self.bases[p] if p < len(self.bases) else bare
        if self.taras and base == "taras" and t in LOOKALIKES:
            return LOOKALIKES[t], f"'{token.strip()}' is a word that sounds like Taras"
        if bare in self.pos[p]:
            sc, kind = self.pos[p][bare]
            if kind in ("form", "translit"):
                return (0.95 if bare == base else sc), "a form of '" + self.text.split()[p] + "'"
            return sc, f"a common mishearing of '{self.text.split()[p]}' ({token.strip()})"
        if len(base) >= 4 and bare.startswith(base) and len(bare) <= len(base) + 5:
            m = DERIVED_RE.match(bare) if base == "taras" else None
            hint = next((v for k, v in DERIVED_HINT.items() if m and m.group(1).startswith(k)), "a word")
            return 0.5, f"{hint} built on '{base}' ({token.strip()})"
        if len(bare) >= 5 and any(lev(bare, w) == 1 for w, (sc, kind) in self.pos[p].items() if kind == "form"):
            return 0.5, f"one letter from a form of '{self.text.split()[p]}' ({token.strip()})"
        if len(bare) <= len(base) + 3 and phonetic(bare) in self.phon[p]:
            return 0.35, f"sounds similar to '{self.text.split()[p]}' ({token.strip()})"
        return None


def _words(transcript: dict):
    """Every word with its chunk, in order: (chunk index, [text, start, end, prob])."""
    for ci, ch in enumerate(transcript.get("chunks", [])):
        for w in ch.get("words") or []:
            yield ci, w


def _excerpt(words: list, i: int, j: int, span: float = 6.0) -> tuple[str, float, float]:
    t0, t1 = words[i][1][1] - span, words[j][1][2] + span
    sel = [w for _, w in words if w[2] >= t0 and w[1] <= t1]
    text = "".join(w[0] for w in sel).strip()
    return text, sel[0][1] if sel else t0, sel[-1][2] if sel else t1


def find_name(transcript: dict, min_confidence: float = 0.03, phrases: list[dict] | None = None) -> list[dict]:
    """Candidate mentions of each phrase, scored. A multi-word match takes the words it covers."""
    if phrases is None:
        from .phrases import variants
        phrases = [variants("тарас")]
    matchers = sorted((Matcher(p) for p in phrases), key=lambda m: -m.k)
    words = list(_words(transcript))
    chunks = transcript.get("chunks", [])
    taken: set[int] = set()
    hits: list[dict] = []
    for mt in matchers:
        i = 0
        while i + mt.k <= len(words):
            if any(x in taken for x in range(i, i + mt.k)):
                i += 1
                continue
            span_end = i + mt.k - 1
            scores = [mt.word(p, words[i + p][1][0]) for p in range(mt.k)]
            found = None
            if all(scores):
                found = (sum(s[0] for s in scores) / mt.k, "; ".join(dict.fromkeys(s[1] for s in scores)))
            elif mt.k == 1 and i + 1 < len(words) and i + 1 not in taken:   # "Tara s": two tokens that join
                joined = (clean(words[i][1][0]) + clean(words[i + 1][1][0])).replace("'", "")
                if joined in mt.pos[0] and mt.pos[0][joined][1] in ("form", "translit"):
                    found, span_end = (0.4, f"two words that join into '{mt.text}' "
                                            f"('{words[i][1][0].strip()}{words[i + 1][1][0]}')"), i + 1
            if not found:
                i += 1
                continue
            sound, why = found
            ci, w = words[i]
            probs = [words[k][1][3] for k in range(i, span_end + 1)]
            asr = sum(probs) / len(probs)
            notes = [why]
            exact = all(s and s[0] >= 0.9 for s in scores) if all(scores) else False
            name_p = 0.85 if exact else 0.6
            raw = w[0].strip()
            prev_t = clean(words[i - 1][1][0]) if i > 0 else ""
            next_t = clean(words[span_end + 1][1][0]) if span_end + 1 < len(words) else ""
            if mt.taras and clean(raw) in LOOKALIKES:
                name_p = 0.35
                if prev_t in NOUN_CONTEXT:
                    name_p = 0.15
                    notes.append(f"used as a common noun ('{words[i - 1][1][0].strip()} {raw}')")
            if clean(raw) == "tara's":
                notes.append("may be the possessive of the name Tara")
            if clean(raw) in ("maslow", "maslows", "maslow's"):
                notes.append("Maslow is also an English surname (e.g. Abraham Maslow, 'Maslow's hierarchy')")
            if mt.taras and mt.k == 1 and next_t in KNOWN_FULL_NAMES:
                notes.append("refers to " + KNOWN_FULL_NAMES[next_t])
            lang = chunks[ci].get("lang") if ci < len(chunks) else None
            if lang and lang not in EAST_SLAVIC and exact:
                notes.append(f"heard in {lang} speech")
            conf = sound * (0.55 + 0.45 * asr) * name_p
            if conf >= min_confidence:
                text, ex0, ex1 = _excerpt(words, i, span_end)
                hits.append({
                    "kind": "name", "phrase": mt.text,
                    "matched": " ".join(words[k][1][0].strip() for k in range(i, span_end + 1)),
                    "start": round(w[1], 2), "end": round(words[span_end][1][2], 2),
                    "language": lang, "excerpt": text, "excerpt_start": round(ex0, 2), "excerpt_end": round(ex1, 2),
                    "scores": {"sound": round(sound, 3), "asr": round(asr, 3), "name": round(name_p, 3)},
                    "confidence": round(conf, 3), "notes": notes,
                })
                taken.update(range(i, span_end + 1))
                i = span_end + 1
            else:
                i += 1
    hits.sort(key=lambda h: h["start"])
    return hits


def _script_evidence(text: str, target: str) -> tuple[float, str | None]:
    letters = set(text.lower())
    uk, ru = bool(letters & UK_ONLY), bool(letters & RU_ONLY)
    cyr = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    if cyr < lat:
        return 0.5, "the transcript of this part is mostly Latin letters"
    if target == "uk" and ru and not uk:
        return 0.6, "the transcript has Russian-only letters (ы, э, ъ, ё) and no Ukrainian ones"
    if target == "ru" and uk and not ru:
        return 0.6, "the transcript has Ukrainian-only letters (і, ї, є, ґ) and no Russian ones"
    if target == "uk" and uk:
        return 1.0, "the transcript has Ukrainian-only letters"
    if target == "ru" and ru:
        return 1.0, "the transcript has Russian-only letters"
    return 0.9, None


def find_language(transcript: dict, expected: list[str], min_seconds: float = 3.0,
                  min_prob: float = 0.35, max_gap: float = 3.0) -> list[dict]:
    """Runs of Ukrainian or Russian speech in a source whose expected languages exclude them."""
    expected = [e.lower() for e in expected or []]
    out = []
    for target in ("uk", "ru"):
        if target in expected:
            continue
        runs, cur = [], None
        for ch in transcript.get("chunks", []):
            probs = ch.get("probs") or {}
            p = probs.get(target, 0.0)
            east = sum(probs.get(l, 0.0) for l in EAST_SLAVIC)
            words = ch.get("words") or []
            ok = (ch.get("lang") in EAST_SLAVIC and p >= min_prob and east >= 0.45 and len(words) >= 2
                  and (ch.get("no_speech_prob") or 0) < 0.6 and (ch.get("avg_logprob") or 0) > -1.2)
            if ok and cur and ch["start"] - cur["end"] <= max_gap:
                cur["end"] = ch["end"]
                cur["chunks"].append(ch)
            elif ok:
                cur = {"start": ch["start"], "end": ch["end"], "chunks": [ch]}
                runs.append(cur)
            else:
                cur = None
        for r in runs:
            speech = sum(c.get("speech_s") or (c["end"] - c["start"]) for c in r["chunks"])
            if speech < min_seconds:
                continue
            wsum = sum((c.get("speech_s") or (c["end"] - c["start"])) * c["probs"].get(target, 0) for c in r["chunks"])
            p = wsum / speech
            text = " ".join(c.get("text", "").strip() for c in r["chunks"]).strip()
            script, why = _script_evidence(text, target)
            dur_factor = min(1.0, 0.7 + 0.3 * (speech - min_seconds) / max(1.0, 8.0 - min_seconds))
            conf = min(0.97, p * script * dur_factor)
            other = "ru" if target == "uk" else "uk"
            p_other = sum((c.get("speech_s") or 0) * c["probs"].get(other, 0) for c in r["chunks"]) / speech
            notes = [f"{speech:.0f} s of speech identified as {target} (p={p:.2f}; {other} p={p_other:.2f}); "
                     f"this source normally speaks {', '.join(expected) or 'unknown'}"]
            if why:
                notes.append(why)
            if p_other > 0.15:
                notes.append("Whisper often confuses Ukrainian and Russian")
            notes.append("may be a quoted clip, an interview, an interpreter's channel or a song")
            out.append({
                "kind": "language", "matched": target, "language": target,
                "start": round(r["start"], 2), "end": round(r["end"], 2),
                "excerpt": text[:600], "excerpt_start": round(r["start"], 2), "excerpt_end": round(r["end"], 2),
                "scores": {"language": round(p, 3), "script": script, "duration": round(dur_factor, 3),
                           "speech_s": round(speech, 1)},
                "confidence": round(conf, 3), "notes": notes,
            })
    return out


def label(conf: float) -> str:
    """Never "certain": likely, possible, or low confidence (kept so a person can judge)."""
    return "likely" if conf >= 0.7 else "possible" if conf >= 0.4 else "low confidence"
