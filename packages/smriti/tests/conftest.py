from __future__ import annotations

from pathlib import Path

import pytest

from smriti.api import Platform, create_app
from smriti.cli import seed
from smriti.config import Settings


def _settings(tmp: Path) -> Settings:
    return Settings.from_env(
        data_dir=tmp,
        database_url=f"sqlite:///{(tmp / 'smriti.db').as_posix()}",
        scheduler=False,
        auth_mode="demo",
    )


@pytest.fixture(scope="session")
def platform(tmp_path_factory: pytest.TempPathFactory) -> Platform:
    plat = Platform(_settings(tmp_path_factory.mktemp("smriti")))
    seed(plat)
    return plat


@pytest.fixture(scope="session")
def tenant(platform: Platform):  # type: ignore[no-untyped-def]
    return platform.tenant(None)


@pytest.fixture
def fresh_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    """An app with its own empty-then-seeded store, for tests that change state."""
    app = create_app(_settings(tmp_path))
    seed(app.state.platform)
    return app
