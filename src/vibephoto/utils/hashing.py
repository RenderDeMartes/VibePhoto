"""Fast, stable content hashing for duplicate detection and relinking.

Hashing whole multi-megabyte RAW files during a 10k-photo import is wasteful. We
hash the file size plus the first and last chunks, which is effectively unique for
distinct photos while staying O(1) in file size. The scheme is versioned via the
prefix so it can evolve without misinterpreting old hashes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 64 * 1024  # 64 KiB head + tail


def content_hash(path: Path) -> str:
    """Return a stable, cheap content hash (``"1:" + sha1`` of size + head + tail)."""
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.sha1(usedforsecurity=False)
    h.update(str(size).encode("ascii"))
    with path.open("rb") as fh:
        head = fh.read(_CHUNK)
        h.update(head)
        if size > _CHUNK:
            fh.seek(max(size - _CHUNK, 0))
            h.update(fh.read(_CHUNK))
    return f"1:{h.hexdigest()}"
