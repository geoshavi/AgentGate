"""Build the Phase 4C workspaces and prove each fixture is what it claims.

Free: no model call, no network, no spend. Every fixture must satisfy all four
conditions or the experiment does not run:

    1. prefix -> the focused reproduction FAILS   (the bug is real)
    2. p      -> the focused reproduction PASSES
    3. p      -> the FULL suite is green           (== PROVEN)
    4. n      -> the focused reproduction STILL FAILS (a genuine negative control)

Condition 4 is the one that makes the safety arm mean anything: a negative
control that quietly got fixed would silently become a second positive case.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fixtures import CONFTEST, FIXTURES

ROOT = Path(__file__).parent
# Generated OUTSIDE the repository on purpose. The `n` variants are wrong by
# design, and `ruff check .` scans the whole tree -- materialising them in-repo
# would fail the lint gate with 19 errors that are the point of the fixture.
BUILD = Path(
    os.environ.get("PHASE4C_WORKSPACES", Path(tempfile.gettempdir()) / "phase4c_workspaces")
)
PYTHON = sys.executable


def build(fixture: dict, state: str) -> Path:
    """Materialise one fixture state as a self-contained workspace."""
    workspace = BUILD / state / fixture["id"]
    if workspace.exists():
        shutil.rmtree(workspace)
    (workspace / "tests").mkdir(parents=True)
    (workspace / "conftest.py").write_bytes(CONFTEST.encode("utf-8"))
    (workspace / fixture["module"]).write_bytes(fixture[state].encode("utf-8"))
    stem = fixture["module"].removesuffix(".py")
    (workspace / "tests" / f"test_{stem}.py").write_bytes(fixture["tests"].encode("utf-8"))
    return workspace


def run(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "pytest", "-q", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
        # A non-zero exit is the expected result for `prefix` and `n`; the exit
        # code IS the measurement, so it must never raise.
        check=False,
    )


def node_for(fixture: dict) -> str:
    stem = fixture["module"].removesuffix(".py")
    return f"tests/test_{stem}.py::{fixture['repro_test']}"


def main() -> int:
    failures: list[str] = []
    header = f"{'fixture':<18}{'prefix repro':<16}{'P repro':<12}{'P suite':<12}{'N repro':<14}"
    print(header)
    print("-" * len(header))

    for fixture in FIXTURES:
        node = node_for(fixture)
        prefix_ws = build(fixture, "prefix")
        p_ws = build(fixture, "p")
        n_ws = build(fixture, "n")

        pre = run(prefix_ws, node)
        p_repro = run(p_ws, node)
        p_suite = run(p_ws)
        n_repro = run(n_ws, node)

        ok_pre = pre.returncode != 0
        ok_p = p_repro.returncode == 0
        ok_suite = p_suite.returncode == 0
        ok_n = n_repro.returncode != 0

        print(
            f"{fixture['id']:<18}"
            f"{('FAILS ok' if ok_pre else 'PASSES BAD'):<16}"
            f"{('PASSES ok' if ok_p else 'FAILS BAD'):<12}"
            f"{('GREEN ok' if ok_suite else 'RED BAD'):<12}"
            f"{('FAILS ok' if ok_n else 'PASSES BAD'):<14}"
        )

        if not ok_pre:
            failures.append(f"{fixture['id']}: prefix reproduction did not fail")
        if not ok_p:
            failures.append(f"{fixture['id']}: P reproduction did not pass\n{p_repro.stdout[-500:]}")
        if not ok_suite:
            failures.append(f"{fixture['id']}: P suite not green\n{p_suite.stdout[-500:]}")
        if not ok_n:
            failures.append(f"{fixture['id']}: N reproduction PASSED -- not a negative control")

    print()
    if failures:
        print("FIXTURE VERIFICATION FAILED -- the experiment must not run:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"All {len(FIXTURES)} fixtures verified: P is PROVEN, N is genuinely still broken.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
