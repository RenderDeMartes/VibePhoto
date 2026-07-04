# Vibe Photo — project guide for Claude

Vibe Photo is a fast, non-destructive RAW photo editor and catalog manager for the
desktop. The folder and the project are both **Vibe Photo**; the Python package,
command, and catalog files use the slug **`vibephoto`** (no space). Architecture and
milestone status live in `docs/` (see `docs/12-roadmap.md`).

## Standing rule: rebuild the executable AND the installer when a request is finished

**When you finish and verify a request, rebuild the Windows executable and the
installer as the final step, then report their paths.** The installer must always be
current with the code. This is a hard requirement from the user.

Do this only after tests/lint/types are green — a broken build of broken code helps
no one. If a rebuild would be very slow or the user is mid-conversation, it is fine
to **ask** "rebuild the installer now?" rather than skip it silently — but never let
the shipped installer drift behind the code.

```bash
.venv/Scripts/python.exe scripts/build_exe.py        # 1) one-folder bundle -> dist/VibePhoto/
.venv/Scripts/python.exe scripts/build_installer.py  # 2) installer + root copy
```

- `build_exe.py` → `dist/VibePhoto/VibePhoto.exe` (one-folder PyInstaller bundle,
  driven by `packaging/VibePhoto.spec`).
- `build_installer.py` → a **single** `VibePhoto-Setup.exe` in the **repo root**,
  overwriting the previous one (fixed name = there is always exactly one installer).
  Needs Inno Setup 6 (`winget install JRSoftware.InnoSetup`); the script auto-finds
  ISCC.exe (incl. the per-user `%LOCALAPPDATA%\Programs` install location).
- The root `VibePhoto-Setup.exe` **is committed** (the user wants it in the repo).
  It is ~47 MB — if git history bloat becomes a problem, move it to Git LFS or a
  GitHub Release. `dist/` and the one-folder bundle stay git-ignored.
- Missing build tooling? `pip install -e .[build]` first.
- **macOS/Linux packages cannot be built on this machine** (PyInstaller doesn't
  cross-compile). They are built by `.github/workflows/release.yml` when a `v*`
  tag is pushed: the workflow tests, then builds the Windows installer, a macOS
  `.app` zip, and a Linux tarball, and attaches all three to the GitHub Release.
  Release steps are documented in the README ("Releasing").

## Environment & commands

- Python 3.12, venv at `.venv` (Windows). Activate: `.venv\Scripts\activate`.
- Run the app: `vibephoto` (GUI) or `vibephoto --headless`.
- Install everything: `pip install -e .[ui,raw,cv,dev,build]`.
- Tests: `pytest` (set `QT_QPA_PLATFORM=offscreen` for the GUI tests on a
  headless machine). RAW + Develop integration tests need the `raw` extra.
- Lint/format: `ruff check src tests`. Types: `mypy` (strict).
- If the project folder is ever renamed, **recreate** the venv (don't move it) —
  a moved venv breaks its editable `.pth`, the `vibephoto.exe` launcher, and the
  `activate` scripts.

## Quality bar (keep green)

`ruff` clean · `mypy --strict` 0 issues · full `pytest` suite passing. The
`processing`, `catalog`, `raw`, and `presets` layers must stay **headless** (never
import `vibephoto.ui`); GUI lives only under `vibephoto.ui`. Wiring goes in the one
composition root: `vibephoto/app/bootstrap.py`.

## Naming history (so you're not confused)

This project was briefly called *TuesdayPhoto*, then *Revela*, and is now
**Vibe Photo** (slug `vibephoto`). There should be no `revela`/`tuesdayphoto`
references left anywhere — if you find one, it's a miss; fix it.
