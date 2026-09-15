import os
import subprocess
from pathlib import Path

import pytest

from engine.codeagent.workspace import (
    ForbiddenPath,
    TooManyFilesChanged,
    Workspace,
    WorkspaceError,
    WorkspaceEscape,
    is_denied_name,
)


def _workspace(tmp_path: Path, **kwargs: int) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace(root, **kwargs)


# -- construction -----------------------------------------------------------


def test_root_must_be_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="not an existing directory"):
        Workspace(tmp_path / "nope")


def test_root_is_resolved(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    assert ws.root.is_absolute()
    assert ws.root == (tmp_path / "ws").resolve()


# -- traversal --------------------------------------------------------------


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    for hostile in ("../escape.py", "a/../../escape.py", "..", "a/b/../../../out.py"):
        with pytest.raises(WorkspaceEscape, match="traversal|escape"):
            ws.resolve(hostile)


def test_posix_absolute_path_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(WorkspaceEscape, match="absolute"):
        ws.resolve("/etc/passwd")


def test_backslash_separators_are_normalized_not_flattened(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    resolved = ws.resolve("pkg\\mod.py")
    assert resolved == ws.root / "pkg" / "mod.py"
    # The important half: a backslash form of traversal is caught too.
    with pytest.raises(WorkspaceEscape):
        ws.resolve("..\\escape.py")


def test_no_hostile_input_ever_resolves_outside_the_root(tmp_path: Path) -> None:
    """The invariant that actually matters, asserted platform-independently.

    Some inputs are refused outright and some are neutralised into an
    in-workspace path (a Windows drive spec means nothing on POSIX). Either is
    acceptable; resolving to a path outside the root never is.
    """
    ws = _workspace(tmp_path)
    hostile = [
        "../escape.py",
        "../../escape.py",
        "/etc/passwd",
        "\\\\server\\share\\x",
        "C:\\Windows\\System32\\config",
        "C:/Windows/System32/config",
        "C:relative.py",
        "a/../../../../../../tmp/x",
        "./../../x",
    ]
    for candidate in hostile:
        try:
            resolved = ws.resolve(candidate)
        except WorkspaceError:
            continue
        assert resolved.is_relative_to(ws.root), candidate


def test_non_string_path_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(WorkspaceEscape, match="must be a string"):
        ws.resolve(Path("x.py"))  # type: ignore[arg-type]


def test_empty_and_dot_resolve_to_the_root(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    assert ws.resolve("") == ws.root
    assert ws.resolve(".") == ws.root


# -- symlinks ---------------------------------------------------------------


def _symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    """Create a link, falling back to a Windows directory junction.

    Creating a symlink on Windows needs developer mode or elevation, which a
    normal test run does not have -- and skipping would leave the single most
    important escape vector unverified on the platform this repo is developed
    on. A junction needs neither, is followed by Path.resolve() exactly as a
    symlink is, and therefore exercises the same guard.
    """
    try:
        link.symlink_to(target, target_is_directory=directory)
        return
    except (OSError, NotImplementedError):
        pass

    if directory and os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode == 0:
            return

    pytest.skip("neither symlink nor junction creation is permitted here")


def test_symlinked_directory_escaping_the_root_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("classified", encoding="utf-8")

    _symlink_or_skip(ws.root / "link", outside, directory=True)

    with pytest.raises(WorkspaceEscape):
        ws.resolve("link/secret.txt")


def test_symlinked_file_escaping_the_root_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("classified", encoding="utf-8")

    _symlink_or_skip(ws.root / "alias.txt", outside_file, directory=False)

    with pytest.raises(WorkspaceEscape):
        ws.resolve("alias.txt")


def test_symlink_staying_inside_the_root_is_allowed(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    (ws.root / "real").mkdir()
    (ws.root / "real" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    _symlink_or_skip(ws.root / "alias", ws.root / "real", directory=True)

    assert ws.resolve("alias/mod.py") == (ws.root / "real" / "mod.py").resolve()


# -- secrets ----------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".ENV",
        "config/.env",
        "id_rsa",
        "id_ed25519",
        "server.pem",
        "private.key",
        "secrets.py",
        "app/secrets.json",
        "credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "store.p12",
        ".git/config",
        ".git/hooks/pre-commit",
        ".ssh/known_hosts",
        ".aws/credentials",
    ],
)
def test_credential_shaped_paths_are_refused(tmp_path: Path, path: str) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(ForbiddenPath):
        ws.resolve(path)


def test_ordinary_paths_are_allowed(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    for path in ("todo.py", "src/pkg/mod.py", "tests/test_todo.py", "README.md", "env.py"):
        assert ws.resolve(path).is_relative_to(ws.root), path


def test_is_denied_name_is_case_insensitive() -> None:
    assert is_denied_name(".ENV")
    assert is_denied_name("ID_RSA")
    assert is_denied_name("Server.PEM")
    assert not is_denied_name("environment.py")
    assert not is_denied_name("keyboard.py")


# -- mutation ledger --------------------------------------------------------


def test_ledger_records_distinct_paths_once(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    ws.note_changed(ws.root / "a.py")
    ws.note_changed(ws.root / "a.py")
    ws.note_changed(ws.root / "b.py")
    ws.note_inspected(ws.root / "a.py")
    ws.note_inspected(ws.root / "a.py")

    assert ws.changed_files == ["a.py", "b.py"]
    assert ws.inspected_files == ["a.py"]


def test_max_files_changed_is_enforced(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, max_files_changed=2)
    ws.note_changed(ws.root / "a.py")
    ws.note_changed(ws.root / "b.py")

    with pytest.raises(TooManyFilesChanged, match="max_files_changed is 2"):
        ws.note_changed(ws.root / "c.py")

    # Re-touching an already-counted file stays allowed at the ceiling.
    ws.note_changed(ws.root / "a.py")
    assert ws.changed_files == ["a.py", "b.py"]


def test_relative_reports_posix_form(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    assert ws.relative(ws.root / "pkg" / "mod.py") == "pkg/mod.py"
    assert os.sep not in ws.relative(ws.root / "pkg" / "mod.py") or os.sep == "/"
