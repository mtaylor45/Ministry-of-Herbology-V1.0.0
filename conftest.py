"""Repository-root pytest configuration.

`api/` holds one importable package per parts of the project and `workers/` holds the
background packages, and the suites import both by their canonical names
(`app.main`, `workers.botany.…`). Only `api/` is installed, as an editable
distribution, so `workers` has to be found on the path.

This has to live at the repository root rather than in `tests/`, because a
conftest only applies to tests beneath it: `pytest tests api workers` collects
three trees, and `pytest tests/contract` collects one.

It also has to exist at all — running `python -m pytest` silently prepends the
working directory to `sys.path`, while the bare `pytest` console script does
not. CI uses the latter, so a suite that passes under `python -m pytest` can
still fail in CI with `ModuleNotFoundError: No module named 'workers'`. Both
invocations now behave the same.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

for path in (REPO_ROOT, REPO_ROOT / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
