"""Integration tests for the composition root and Application lifecycle."""

from __future__ import annotations

import pytest

from vibephoto.app.application import Application, ApplicationContext
from vibephoto.app.bootstrap import build_application
from vibephoto.core.config import AppSettings, CacheSettings
from vibephoto.core.events import EventBus
from vibephoto.core.paths import AppPaths


@pytest.mark.integration
def test_build_application_headless(app_paths: AppPaths) -> None:
    app = build_application(paths=app_paths, settings=AppSettings(), configure_logs=False)
    assert isinstance(app, Application)
    # Core singletons resolvable from the container.
    assert isinstance(app.resolve(EventBus), EventBus)
    assert app.resolve(AppSettings) is app.settings
    assert app.resolve(AppPaths) is app.paths


@pytest.mark.integration
def test_section_settings_are_individually_resolvable(app_paths: AppPaths) -> None:
    app = build_application(paths=app_paths, settings=AppSettings(), configure_logs=False)
    cache = app.resolve(CacheSettings)
    assert isinstance(cache, CacheSettings)
    assert cache is app.settings.cache


@pytest.mark.integration
def test_application_context_manager_starts_and_stops(app_paths: AppPaths) -> None:
    app = build_application(paths=app_paths, settings=AppSettings(), configure_logs=False)
    with app as running:
        assert running.state.name == "STARTED"
    assert app.state.name == "STOPPED"


@pytest.mark.integration
def test_application_context_is_registered(app_paths: AppPaths) -> None:
    app = build_application(paths=app_paths, settings=AppSettings(), configure_logs=False)
    ctx = app.resolve(ApplicationContext)
    assert isinstance(ctx, ApplicationContext)
    assert ctx.paths is app_paths


@pytest.mark.integration
def test_build_application_ensures_directories(tmp_path) -> None:
    paths = AppPaths.under(tmp_path)
    assert not paths.config_dir.exists()
    build_application(paths=paths, settings=AppSettings(), configure_logs=False)
    assert paths.config_dir.is_dir()
    assert paths.cache_dir.is_dir()
