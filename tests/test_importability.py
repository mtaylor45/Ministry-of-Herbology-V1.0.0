"""The suite must collect the same way under every runner.

importing `workers.botany`, and the only local check had been run with
`python -m pytest`, which prepends the working directory to `sys.path`. The
bare `pytest` console script CI uses does not, so the failure was invisible
locally: 23 passed and 21 errored in CI on a change that looked clean.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_both_source_roots_are_importable():
    """`api/` is installed; the repo root, which carries `workers/`, is not."""
    import app.main  # noqa: F401 — the API entrypoint

    import workers.botany.router  # noqa: F401 — a package outside api/


def test_the_contract_suite_collects_under_the_bare_pytest_script():
    """Exactly what CI runs, and exactly what silently broke.

    `python -m pytest` would pass this even with the path misconfigured,
    because it prepends the working directory. The console script does not,
    so this is the invocation worth asserting.
    """
    result = subprocess.run(
        [
            str(Path(sys.executable).parent / "pytest"),
            "--collect-only",
            "-q",
            "tests/contract",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "ModuleNotFoundError" not in result.stdout + result.stderr, (
        "a source root is missing from sys.path under the bare pytest script; "
        "see conftest.py at the repository root"
    )
    assert result.returncode == 0, result.stdout[-2000:]
