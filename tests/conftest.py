from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.helpers import build_tiny_library

FROZEN_NOW = datetime(2026, 8, 23, 15, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen_now() -> datetime:
    return FROZEN_NOW


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    return build_tiny_library(tmp_path / "media")
