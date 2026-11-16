"""Keep recent local review reports across desktop sessions."""

import hashlib
import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time

from .review import fingerprint


REVIEW_CACHE_SECONDS = 7 * 24 * 60 * 60


def report_location(directory, source, analysis, *, project=False):
    """Separate different media revisions and analysis settings."""
    try:
        source = source.resolve()
        version = source.stat()
    except OSError:
        return None
    identity = (os.path.normcase(str(source)), version.st_size, version.st_mtime_ns,
                0 if project else analysis.media.stream_index, asdict(analysis.options), fingerprint(analysis.notes))
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return directory / f"{key}.json"


def is_recent(path):
    try:
        return path is not None and path.stat().st_mtime >= time() - REVIEW_CACHE_SECONDS
    except OSError:
        return False


def remove_expired_reports(directory):
    cutoff = time() - REVIEW_CACHE_SECONDS
    for path in directory.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def remember_report(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A second NoteFlow process should see either the old record or the full new one.
    temporary = None
    try:
        with NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            with source.open("rb") as report:
                shutil.copyfileobj(report, stream)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
