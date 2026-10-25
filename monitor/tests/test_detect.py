"""Detection over hand-made transcripts (no audio). Run: python -m pytest monitor/tests"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eemonitor import detect  # noqa: E402


def tr(words, lang="en", probs=None, start=0.0, step=0.4, **chunk):
    ws, t = [], start
    for w in words.split():
        p = 0.95
        if "|" in w:
            w, p = w.split("|")[0], float(w.split("|")[1])
        ws.append([" " + w, t, t + step - 0.05, p])
        t += step
    ch = {"start": start, "end": t, "speech_s": t - start, "lang": lang, "probs": probs or {lang: 0.95},
          "text": " ".join(x[0].strip() for x in ws), "words": ws, "avg_logprob": -0.3, "no_speech_prob": 0.05}
    ch.update(chunk)
    return ch


def test_cyrillic_and_latin_forms():
    t = {"chunks": [tr("Я передал привет Тарасу и Тарасу Шевченко", "ru"),
                    tr("We met Taras yesterday", start=10)]}
    hits = detect.find_name(t)
    assert [h["matched"] for h in hits] == ["Тарасу", "Тарасу", "Taras"]
    assert all(h["confidence"] >= 0.6 for h in hits)
    assert any("Shevchenko" in n for n in hits[1]["notes"])
    assert "heard in en speech" in hits[2]["notes"]
    assert hits[2]["start"] == 10.8


def test_terrace_is_weak():
    hits = detect.find_name({"chunks": [tr("lunch on the terrace with the minister")]})
    assert len(hits) == 1 and hits[0]["matched"] == "terrace"
    assert detect.label(hits[0]["confidence"]) == "low confidence"
    assert any("common noun" in n for n in hits[0]["notes"])


def test_fuzzy_and_split_and_surname():
    hits = detect.find_name({"chunks": [tr("mister Tarus said"), tr("Tara s came", start=5),
                                        tr("Minister Tarasov spoke", start=9)]})
    m = {h["matched"]: h for h in hits}
    assert "Tarus" in m and "Tara s" in m and "Tarasov" in m
    assert m["Tarus"]["confidence"] < m["Tarasov"]["confidence"] + 0.3


def test_unrelated_words_do_not_match():
    hits = detect.find_name({"chunks": [tr("the tariff on Texas trade has risen; tears tars tiaras")]})
    assert [h["matched"] for h in hits] == ["tiaras"] and hits[0]["confidence"] < 0.2


def test_low_asr_probability_lowers_confidence():
    a = detect.find_name({"chunks": [tr("hello Taras|0.95")]})[0]["confidence"]
    b = detect.find_name({"chunks": [tr("hello Taras|0.2")]})[0]["confidence"]
    assert b < a


def test_language_mismatch():
    chunks = [tr("Good morning everyone and welcome to the briefing", "en", start=0),
              tr("Добрый день уважаемые коллеги мы собрались здесь сегодня", "ru",
                 {"ru": 0.9, "uk": 0.05, "en": 0.02}, start=5),
              tr("Спасибо большое за внимание", "ru", {"ru": 0.85, "uk": 0.1}, start=9.5)]
    hits = detect.find_language({"chunks": chunks}, ["en"])
    assert len(hits) == 1
    h = hits[0]
    assert h["language"] == "ru" and h["start"] == 5 and h["confidence"] > 0.6
    assert detect.find_language({"chunks": chunks}, ["en", "ru"]) == []


def test_language_too_short_or_latin():
    short = [tr("Спасибо", "ru", {"ru": 0.9}, start=0)]
    assert detect.find_language({"chunks": short}, ["en"]) == []
    latin = [tr("thank you very much colleagues for all the work done here today in this room", "ru", {"ru": 0.8, "uk": 0.1})]
    h = detect.find_language({"chunks": latin}, ["en"])
    assert h and h[0]["confidence"] < 0.5


def test_ukrainian_vs_russian_letters():
    uk = [tr("Добрий день шановні колеги ми зібралися тут сьогодні і це важливо", "uk", {"uk": 0.6, "ru": 0.35})]
    h = detect.find_language({"chunks": uk}, ["ru"])
    assert h and h[0]["language"] == "uk"
    assert any("confuses" in n for n in h[0]["notes"])
    assert any("Ukrainian-only" in n for n in h[0]["notes"])


def test_translit():
    assert detect.clean("Тараса,") == "tarasa"
    assert detect.clean("Tarás") == "taras"
    assert detect.phonetic("terrace") == "taras"


def phr():
    from eemonitor.phrases import variants, DEFAULT_PHRASES
    return [variants(p) for p in DEFAULT_PHRASES]


def test_phrase_variants():
    from eemonitor.phrases import variants
    v = variants("тарас маслов")["variants"]
    for f in ("тарас маслов", "тараса маслова", "тарасу маслову", "тарасом масловим", "тарасом масловым"):
        assert f in v, f
    m = variants("маслов")["variants"]
    for f in ("маслов", "маслова", "маслову", "масловим", "масловым", "маслові", "маслове", "маслових", "масловых",
              "Maslov", "Maslow", "Masloff", "Maslova"):
        assert f in m, f
    t = variants("тарас")["variants"]
    for f in ("тарас", "тараса", "тарасу", "тарасом", "тарасі", "тарасе", "Taras", "Tarasa"):
        assert f in t, f


def test_full_phrase_beats_single_words():
    hits = detect.find_name({"chunks": [tr("Мы говорили с Тарасом Масловым вчера", "ru"),
                                        tr("Professor Maslow said", start=8), tr("и Маслова тоже", "ru", start=12)]},
                            phrases=phr())
    assert [(h["phrase"], h["matched"]) for h in hits] == [
        ("тарас маслов", "Тарасом Масловым"), ("маслов", "Maslow"), ("маслов", "Маслова")]
    assert any("Abraham Maslow" in n for n in hits[1]["notes"])


def test_mishearing_is_low_but_kept():
    hits = detect.find_name({"chunks": [tr("a man called Toras|0.4 came")]}, phrases=phr())
    assert hits and hits[0]["confidence"] < 0.4 and detect.label(hits[0]["confidence"]) == "low confidence"
