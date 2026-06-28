"""Utils layer — small, dependency-light, broadly-reused helpers.

Cross-cutting helpers that don't belong to a single domain (timing, hashing,
human-readable sizes, image-geometry math). Anything here must be pure and have
no upward dependencies on domain or UI layers, so it stays safe to import from
anywhere.
"""

from __future__ import annotations

__all__: list[str] = []
