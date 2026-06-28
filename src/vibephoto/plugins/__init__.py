"""Plugin layer — discovery, loading, sandboxing, and the public SDK surface.

Hosts third-party extensions (import/export plugins, preset packs, HDR and
processing plugins, and future AI plugins) behind versioned, capability-scoped
contracts. Plugins are isolated with their own dependency environments and a
restricted host API so a faulty plugin cannot corrupt the catalog or crash the
host.

Depends on: ``core`` and the published SDK protocols only. Never imports ``ui``
directly; UI contributions are declarative.
Designed in: ``docs/09-plugin-sdk.md``.
Built in: Phase 9.
"""

from __future__ import annotations

__all__: list[str] = []
