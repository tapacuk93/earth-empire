"""Backups of every part's state on the box, and their restore (CONTRACT.md "The box").

Every SQLite database under /var/lib/earth-empire/<part>/ (*.sqlite, *.sqlite3, *.db, at most
two levels down; never browser profiles or build caches) is copied with SQLite's online backup
API (consistent while its owner keeps writing), gzipped and uploaded:

  s3://earth-empire-backups/state/latest/<part>/<path>.gz          every hour
  s3://earth-empire-backups/state/daily/<date>/<part>/<path>.gz    the first backup of each day

The bucket expires daily copies after 35 days. `ee restore` (backend/deploy/restore-state.sh
stops the services around it) brings them back, so a rebuilt box starts where the old one stopped:
the archive, the pipeline and posting state, the collector's and the monitor's state.
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .logs import event

ROOT = Path("/var/lib/earth-empire")
SKIP_DIRS = {"browser", "site-build", "node_modules", "screenshots", "facebook", "tmp", "cache"}
SUFFIXES = (".sqlite", ".sqlite3", ".db")
PREFIX = "state"


def databases(root: Path = ROOT) -> list[Path]:
    out = []
    for part in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith(".")):
        for f in sorted(part.rglob("*")):
            rel = f.relative_to(part)
            if len(rel.parts) > 2 or any(x in SKIP_DIRS for x in rel.parts[:-1]):
                continue
            if f.is_file() and f.suffix in SUFFIXES and not f.name.startswith("backup."):
                out.append(f)
    return out


def snapshot(src: Path, dest: Path) -> None:
    """A consistent copy of a live SQLite database."""
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def backup_all(root: Path = ROOT, *, daily: bool = False) -> list[str]:
    import boto3
    s3 = boto3.client("s3", region_name=config.REGION)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    keys = []
    with tempfile.TemporaryDirectory() as tmp:
        for db in databases(root):
            rel = db.relative_to(root)
            snap = Path(tmp) / "snap.sqlite"
            snapshot(db, snap)
            gz = Path(tmp) / "snap.gz"
            with open(snap, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
                shutil.copyfileobj(fi, fo)
            key = f"{PREFIX}/latest/{rel}.gz"
            s3.upload_file(str(gz), config.BACKUP_BUCKET, key)
            keys.append(key)
            if daily:
                s3.copy_object(Bucket=config.BACKUP_BUCKET, Key=f"{PREFIX}/daily/{day}/{rel}.gz",
                               CopySource={"Bucket": config.BACKUP_BUCKET, "Key": key})
            snap.unlink()
            gz.unlink()
    event("backup.done", files=keys, daily=daily)
    return keys


def restore_all(root: Path = ROOT, *, date: str | None = None, only: str | None = None,
                dry_run: bool = False) -> list[dict]:
    """Download every backed-up database (latest, or a day's) and put it in place. The caller
    stops the services first. Each file is integrity-checked before it replaces anything; the
    current file is kept as <name>.before-restore."""
    import boto3
    s3 = boto3.client("s3", region_name=config.REGION)
    prefix = f"{PREFIX}/daily/{date}/" if date else f"{PREFIX}/latest/"
    done = []
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=config.BACKUP_BUCKET, Prefix=prefix)
    for page in pages:
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix):]
            if not rel.endswith(".gz") or (only and not rel.startswith(only + "/")):
                continue
            target = root / rel[:-3]
            with tempfile.TemporaryDirectory() as tmp:
                gz = Path(tmp) / "x.gz"
                s3.download_file(config.BACKUP_BUCKET, obj["Key"], str(gz))
                raw = Path(tmp) / "x.sqlite"
                with gzip.open(gz, "rb") as fi, open(raw, "wb") as fo:
                    shutil.copyfileobj(fi, fo)
                c = sqlite3.connect(raw)
                ok = c.execute("PRAGMA integrity_check").fetchone()[0]
                tables = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
                c.close()
                info = {"file": str(target), "from": obj["Key"], "backed_up": obj["LastModified"].isoformat(),
                        "integrity": ok, "tables": tables}
                if ok != "ok":
                    info["skipped"] = "integrity check failed"
                elif not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        shutil.copy2(target, target.with_name(target.name + ".before-restore"))
                    for side in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
                        side.unlink(missing_ok=True)
                    shutil.copy(raw, target)
                    shutil.chown(target, "earth", "earth")
                done.append(info)
    event("restore.done", files=done, date=date, dry_run=dry_run)
    return done
