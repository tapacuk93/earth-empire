"""Downloading media from Instagram's CDN, thumbnails, and re-hosting through the backend.

Best quality: the largest progressive MP4; if the DASH manifest offers a taller video stream,
that stream and the best audio stream are fetched and muxed with ffmpeg (no re-encode).
"""

from __future__ import annotations

import io
import logging
import random
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

import httpx
from PIL import Image

log = logging.getLogger("ee.media")

THUMB_MAX = 640


class Downloader:
    def __init__(self, user_agent: str, gap: tuple[float, float] = (0.8, 2.5)):
        self.http = httpx.Client(timeout=300, follow_redirects=True, headers={
            "User-Agent": user_agent, "Referer": "https://www.instagram.com/", "Accept": "*/*"})
        self.gap = gap
        self._last = 0.0

    def get(self, url: str) -> bytes:
        wait = random.uniform(*self.gap) - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(4):
            try:
                r = self.http.get(url)
                self._last = time.monotonic()
                if r.status_code == 200:
                    return r.content
                if r.status_code in (403, 404, 410):
                    raise MediaGone(f"{r.status_code} for media (URL expired or removed)")
                log.warning("media download -> %d (attempt %d)", r.status_code, attempt + 1)
            except httpx.HTTPError as e:
                log.warning("media download failed: %s (attempt %d)", e, attempt + 1)
            time.sleep(10 * (attempt + 1))
        raise MediaGone("media download failed after retries")


class MediaGone(RuntimeError):
    pass


def to_jpeg(data: bytes, max_side: int | None = None, quality: int = 92) -> bytes:
    im = Image.open(io.BytesIO(data))
    if im.format == "JPEG" and max_side is None:
        return data
    im = im.convert("RGB")
    if max_side and max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def thumb(data: bytes) -> bytes:
    return to_jpeg(data, THUMB_MAX, 82)


def image_size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def video_frame(video: bytes) -> bytes | None:
    """A JPEG frame from a video, for a poster when Instagram gave none."""
    if not shutil.which("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d, "v.mp4"), Path(d, "f.jpg")
        src.write_bytes(video)
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.5", "-i", str(src),
                            "-frames:v", "1", str(dst)], capture_output=True)
        return dst.read_bytes() if r.returncode == 0 and dst.exists() else None


def dash_best(manifest: str) -> tuple[dict | None, dict | None]:
    """(best video representation, best audio representation) from an MPD, each {url, width, height, bandwidth}."""
    try:
        root = ET.fromstring(manifest)
    except ET.ParseError:
        return None, None
    ns = {"m": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    q = (lambda t: f"m:{t}") if ns else (lambda t: t)
    best_v = best_a = None
    for aset in root.iter(root.tag.replace("MPD", "AdaptationSet")):
        ctype = (aset.get("contentType") or aset.get("mimeType") or "")
        for rep in aset.findall(q("Representation"), ns):
            mime = rep.get("mimeType") or aset.get("mimeType") or ctype
            base = rep.find(q("BaseURL"), ns)
            if base is None or not (base.text or "").strip():
                continue
            r = {"url": base.text.strip(), "width": int(rep.get("width") or 0),
                 "height": int(rep.get("height") or 0), "bandwidth": int(rep.get("bandwidth") or 0)}
            if "video" in mime or "video" in ctype:
                if best_v is None or (r["width"] * r["height"], r["bandwidth"]) > (best_v["width"] * best_v["height"], best_v["bandwidth"]):
                    best_v = r
            elif "audio" in mime or "audio" in ctype:
                if best_a is None or r["bandwidth"] > best_a["bandwidth"]:
                    best_a = r
    return best_v, best_a


def fetch_video(dl: Downloader, src: dict, entry: dict) -> bytes:
    """Best-quality MP4 for one media entry; updates width/height if DASH was better."""
    prog = src.get("video")
    dash = src.get("dash")
    if dash and shutil.which("ffmpeg"):
        v, a = dash_best(dash)
        if v and v["height"] > (entry.get("height") or 0) and v["width"] > (entry.get("width") or 0):
            try:
                vdata = dl.get(urljoin(prog or "https://scontent.cdninstagram.com/", v["url"]))
                adata = dl.get(urljoin(prog or "https://scontent.cdninstagram.com/", a["url"])) if a else None
                merged = mux(vdata, adata)
                if merged:
                    entry["width"], entry["height"] = v["width"], v["height"]
                    return merged
            except MediaGone as e:
                log.info("DASH fetch failed (%s); using the progressive MP4", e)
    if not prog:
        raise MediaGone("no video source")
    return dl.get(prog)


def mux(video: bytes, audio: bytes | None) -> bytes | None:
    with tempfile.TemporaryDirectory() as d:
        vp, ap, out = Path(d, "v.mp4"), Path(d, "a.mp4"), Path(d, "o.mp4")
        vp.write_bytes(video)
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(vp)]
        if audio:
            ap.write_bytes(audio)
            cmd += ["-i", str(ap), "-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c", "copy", "-movflags", "+faststart", str(out)]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            log.warning("ffmpeg mux failed: %s", r.stderr.decode()[:300])
            return None
        return out.read_bytes()
