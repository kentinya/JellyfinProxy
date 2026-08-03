from __future__ import annotations

import re

from main import app
from version import __version__


def test_version_uses_semantic_versioning() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", __version__)


def test_fastapi_metadata_uses_release_version() -> None:
    assert app.version == __version__
