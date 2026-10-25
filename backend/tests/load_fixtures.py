"""Load the fixture items through the real ingest API, the way the collector does:
media-url -> presigned PUT to S3 -> PUT items/highlights/profile -> POST a run.

  EE_API_URL=https://<api host> EE_SECRET_INGEST_TOKEN=... python tests/load_fixtures.py
On the box: ee-fixtures (wraps this with the box's env and the ingest secret).
Media come from public sample files; a "#t=a,b" suffix trims a clip with ffmpeg.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).parent
API = os.environ.get("EE_API_URL", "http://127.0.0.1:8000").rstrip("/")


def token():
    t = os.environ.get("EE_SECRET_INGEST_TOKEN")
    if t:
        return t
    import boto3
    return boto3.client("secretsmanager", region_name="us-east-1").get_secret_value(
        SecretId="earth-empire/ingest-token")["SecretString"]


def fetch(url: str, dest: Path):
    url, _, frag = url.partition("#t=")
    raw = dest.with_suffix(".src")
    with httpx.stream("GET", url, timeout=300, follow_redirects=True,
                      headers={"User-Agent": "earth-empire-fixtures/1.0 (test loader)"}) as r:
        r.raise_for_status()
        with open(raw, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    if dest.suffix == ".mp4":
        a, b = (frag.split(",") + ["", ""])[:2] if frag else ("0", "30")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", a or "0", "-i", str(raw), "-t", str(float(b) - float(a or 0)),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-movflags", "+faststart", str(dest)], check=True)
    else:
        raw.rename(dest)


def main():
    fx = json.loads((HERE / "fixtures" / "items.json").read_text())
    h = {"Authorization": f"Bearer {token()}"}
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    work = Path(tempfile.mkdtemp())
    uploaded = 0
    with httpx.Client(timeout=120) as cl:
        for rel, src in fx["sources"].items():
            key = f"items/{rel}"
            ctype = "video/mp4" if rel.endswith(".mp4") else "image/jpeg"
            r = cl.post(f"{API}/v1/ingest/media-url", headers=h, json={"key": key, "content_type": ctype})
            r.raise_for_status()
            info = r.json()
            if info.get("exists"):
                print("exists ", key)
                continue
            local = work / (rel.replace("/", "_"))
            fetch(src, local)
            put = cl.put(info["upload_url"], content=local.read_bytes(), headers=info["headers"], timeout=300)
            put.raise_for_status()
            uploaded += 1
            print("uploaded", key, local.stat().st_size, "bytes ->", info["public_url"])
        items = []
        for it in fx["items"]:
            it = json.loads(json.dumps(it))
            for m in it["media"] + ((it.get("repost_of") or {}).get("media") or []):
                m["url"] = f"https://media.empire.earth/{m['url']}"   # as the collector sends it
            it["collected_at"] = started
            items.append(it)
        print("items     ", cl.put(f"{API}/v1/ingest/items", headers=h, json={"items": items}).json())
        print("highlights", cl.put(f"{API}/v1/ingest/highlights", headers=h, json={"highlights": fx["highlights"]}).json())
        if cl.get(f"{API}/v1/profile").status_code == 404:   # never over a real profile
            print("profile   ", cl.put(f"{API}/v1/ingest/profile", headers=h, json=fx["profile"]).json())
        print("run       ", cl.post(f"{API}/v1/ingest/runs", headers=h, json={
            "started_at": started, "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ok": True, "counts": {"fixtures": len(items), "uploaded": uploaded}}).json())


if __name__ == "__main__":
    sys.exit(main())
