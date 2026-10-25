"""Speech to text on the box's CPU with faster-whisper (MIT; OpenAI Whisper weights, MIT), with the
language identified per chunk, not once per video.

The audio is decoded by ffmpeg to 16 kHz mono, split by Silero VAD (bundled with faster-whisper,
MIT) into chunks of at most `max_chunk` seconds that end in a pause, and each chunk is transcribed
on its own with language detection: so an English briefing with a Russian answer in the middle
shows both languages, with Whisper's probabilities for each, and word timestamps for matching.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

SR = 16000
_model = None
_model_name = None
_lock = threading.Lock()


def decode(path: str):
    import numpy as np
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "s16le", "-"], capture_output=True, timeout=3600)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg could not decode: " + p.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768.0


def model(name: str = "small"):
    global _model, _model_name
    with _lock:
        if _model is None or _model_name != name:
            from faster_whisper import WhisperModel
            root = os.environ.get("EE_WHISPER_MODELS", "/var/lib/earth-empire/monitor/models")
            _model = WhisperModel(name, device="cpu", compute_type="int8",
                                  cpu_threads=int(os.environ.get("EE_WHISPER_THREADS", "2")), download_root=root)
            _model_name = name
        return _model


def chunks_of(audio, max_chunk: float = 20.0) -> list[tuple[int, int, float]]:
    """(start sample, end sample, seconds of speech) for each chunk of speech."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    regions = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400, speech_pad_ms=200))
    out: list[list] = []
    lim = int(max_chunk * SR)
    for r in regions:
        s, e = r["start"], r["end"]
        while e - s > lim:   # a long stretch without a pause
            out.append([s, s + lim, lim / SR])
            s += lim
        if out and e - out[-1][0] <= lim and s - out[-1][1] < 2 * SR:
            out[-1][1] = e
            out[-1][2] += (e - s) / SR
        else:
            out.append([s, e, (e - s) / SR])
    return [tuple(x) for x in out]


def transcribe(path: str, model_name: str = "small", beam_size: int = 1, max_chunk: float = 20.0) -> dict:
    t0 = time.process_time()
    w0 = time.time()
    audio = decode(path)
    m = model(model_name)
    result = {"model": f"faster-whisper {model_name} int8", "duration": round(len(audio) / SR, 2), "chunks": []}
    speech = 0.0
    for s, e, sp in chunks_of(audio, max_chunk):
        seg_audio = audio[s:e]
        segs, info = m.transcribe(seg_audio, language=None, beam_size=beam_size, word_timestamps=True,
                                  vad_filter=False, condition_on_previous_text=False)
        segs = list(segs)
        off = s / SR
        words, texts, lp, nsp = [], [], [], []
        for sg in segs:
            texts.append(sg.text.strip())
            lp.append(sg.avg_logprob)
            nsp.append(sg.no_speech_prob)
            for w in sg.words or []:
                words.append([w.word, round(off + w.start, 2), round(off + w.end, 2), round(w.probability, 3)])
        probs = {k: round(v, 4) for k, v in (info.all_language_probs or [])[:6]}
        speech += sp
        result["chunks"].append({
            "start": round(off, 2), "end": round(e / SR, 2), "speech_s": round(sp, 2),
            "lang": info.language, "lang_prob": round(info.language_probability, 3), "probs": probs,
            "text": " ".join(texts), "words": words,
            "avg_logprob": round(sum(lp) / len(lp), 3) if lp else None,
            "no_speech_prob": round(max(nsp), 3) if nsp else None,
        })
    result["speech_s"] = round(speech, 2)
    result["cpu_s"] = round(time.process_time() - t0, 1)
    result["wall_s"] = round(time.time() - w0, 1)
    return result


def languages(tr: dict) -> dict[str, float]:
    """Seconds of speech per language."""
    out: dict[str, float] = {}
    for ch in tr.get("chunks", []):
        if ch.get("words"):
            out[ch["lang"]] = round(out.get(ch["lang"], 0) + (ch.get("speech_s") or 0), 1)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
