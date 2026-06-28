# 09 — Plugin SDK Design

Plugins extend Vibe Photo without forking it. The SDK is a **published, versioned
contract**; plugins are **discovered, sandboxed, dependency-isolated, and
capability-scoped**.

## 1. Plugin categories

| Category | Extends | Example |
|----------|---------|---------|
| **Import** | ingest sources | tethered capture, cloud/Drive import |
| **Export** | output targets | SmugMug/Zenfolio upload, custom MLS exporter |
| **Preset pack** | preset library | a paid look pack |
| **HDR** | merge/deghost algorithms | alternative tone-mapping/merge |
| **Processing** | new develop nodes | film-emulation node, custom sharpener |
| **AI** | analysis/automation | culling, sky masking, tagging (see [`future`](#7-ai-plugins-placeholder)) |

## 2. Anatomy & manifest

```
my_plugin/
├── plugin.toml          # manifest
├── __init__.py          # entry: register(host: PluginHost) -> None
├── requirements.txt     # isolated dependencies
└── resources/
```

```toml
# plugin.toml
[plugin]
id = "com.example.skymask"
name = "Sky Mask AI"
version = "1.2.0"
category = "ai"
api_version = ">=1.0,<2.0"     # SDK semver range this plugin targets
entry = "skymask:register"

[capabilities]                 # least-privilege; user-approved at install
read_catalog = true
write_develop = true
network = false
filesystem = ["cache"]         # scoped roots only
```

## 3. Host API (capability-scoped)

Plugins never touch internals directly; they receive a `PluginHost` facade that
exposes **only** what their granted capabilities allow:

```python
class PluginHost(Protocol):
    api_version: str
    def register_export_target(self, target: ExportTarget) -> None: ...
    def register_node(self, node_factory: NodeFactory) -> None: ...
    def register_import_source(self, source: ImportSource) -> None: ...
    def register_hdr_merger(self, merger: HdrMerger) -> None: ...
    def logger(self) -> Logger: ...
    def catalog_read(self) -> CatalogReadApi: ...        # if read_catalog
    def develop_api(self) -> DevelopWriteApi: ...        # if write_develop
    # No raw DB/handles, no UI internals.
```

Extension points are the same Protocols the core implements (e.g. a processing
plugin provides a `Node` — see [`06`](06-processing-engine.md)), so plugins are
first-class, not bolted-on.

## 4. Discovery & lifecycle

1. **Discover** plugins in the user plugins dir + installed packs.
2. **Validate** manifest, API-version compatibility, signature (if signed).
3. **Resolve dependencies** into an isolated environment (see §5).
4. **Load** in a sandbox; call `register(host)`.
5. **Activate/deactivate** on demand; **unload** cleanly. Failures are contained:
   a crashing plugin is disabled with a report, never taking down the host.

## 5. Dependency isolation

Each plugin declares its own `requirements.txt`. The host installs them into a
**per-plugin virtual environment / isolated site** and inserts that on the
plugin's import path, so plugin deps can't clash with the app's or each other's
(the classic "two plugins need different NumPy" problem). Pure-Python plugins can
opt into a shared environment for speed.

## 6. Sandboxing & security

- **Capability gating:** no network / arbitrary filesystem unless declared and
  user-approved; the host enforces scoped roots.
- **Process isolation (for untrusted/AI plugins):** run in a subprocess with an
  RPC bridge, so native crashes or heavy ML models don't destabilise the GUI
  process and can be resource-limited/killed.
- **No catalog handles:** plugins get a mediated read/write API, never the SQLite
  connection — the host preserves the single-writer invariant and validates writes.
- **Signing & provenance:** packs carry author/license; the marketplace can require
  signatures.

## 7. Versioning

- The SDK is **semver**; `api_version` ranges in the manifest gate compatibility.
- Protocols are additive within a major version; breaking changes bump the major
  and the host refuses incompatible plugins with a clear message.

## 8. AI plugins (placeholder)

AI is **architected now, implemented later** (see [`12`](12-roadmap.md)). The AI
category + process-isolation + a `analysis` capability are the seams. Planned host
hooks (no-ops until built): scene/subject detection, sky masking, preset
recommendation, auto-culling, duplicate detection, batch categorisation. Because
these are plugins behind stable Protocols, they land **without refactoring** the
core — satisfying the "future AI without major refactoring" requirement.

## 9. Documentation deliverables
A published SDK reference (generated from the Protocol docstrings), a cookie-cutter
plugin template, and an example of each category ship with the SDK.
