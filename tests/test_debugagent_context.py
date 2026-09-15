"""D2: evidence-first context construction.

Deterministic and model-free -- ``build_context`` decides what the diagnosing
model is allowed to see, and it decides it from D1 evidence rather than from the
repository at large. The tests below are mostly about what is *absent*: an
unrelated file, a secret, a file the evidence never named.
"""

from pathlib import Path

from engine.codeagent.limits import Limits
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.workspace import Workspace
from engine.debugagent.context import build_context
from engine.debugagent.evidence import build_evidence

CART = "".join(f"line {n}\n" for n in range(1, 31))


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Workspace(root)


def _evidence(ws: Workspace, stderr: str, limits: Limits | None = None):
    return build_evidence(
        argv=["python", "-m", "pytest", "-q"],
        stdout="",
        stderr=stderr,
        exit_code=1,
        timed_out=False,
        duration_ms=5,
        workspace=ws,
        limits=limits or Limits(),
    )


def _traceback(ws: Workspace, *files: str) -> str:
    frames = "".join(
        f'  File "{ws.root / name}", line 3, in fn{i}\n' for i, name in enumerate(files)
    )
    return "Traceback (most recent call last):\n" + frames + "ValueError: boom\n"


def _ctx(ws: Workspace, evidence, **limit_overrides: object):
    return build_context(
        evidence=evidence,
        workspace=ws,
        policy=DEFAULT_POLICY,
        limits=Limits(**limit_overrides),  # type: ignore[arg-type]
    )


# -- evidence-first selection ----------------------------------------------


def test_inspects_the_file_the_traceback_named(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART})
    context = _ctx(ws, _evidence(ws, _traceback(ws, "cart.py")))

    assert context.inspected_files == ["cart.py"]
    # ReadFileTool's numbered body -- not the traceback echo in the evidence
    # tail, which also contains the words "line 3".
    assert "3| line 3" in context.render()


def test_unreferenced_files_are_not_inspected(tmp_path: Path) -> None:
    """The whole repository must not be fed in blindly."""
    ws = _ws(tmp_path, {"cart.py": CART, "unrelated.py": "SECRET_MARKER = 1\n"})
    context = _ctx(ws, _evidence(ws, _traceback(ws, "cart.py")))

    assert context.inspected_files == ["cart.py"]
    assert "SECRET_MARKER" not in context.render()


def test_suspect_file_is_inspected_first(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"outer.py": CART, "deep.py": CART})
    context = _ctx(ws, _evidence(ws, _traceback(ws, "outer.py", "deep.py")))

    # `deep.py` is the last frame, so it is the suspect and leads.
    assert context.inspected_files[0] == "deep.py"
    assert set(context.inspected_files) == {"deep.py", "outer.py"}


def test_inspected_file_count_is_bounded(tmp_path: Path) -> None:
    files = {f"m{n}.py": CART for n in range(8)}
    ws = _ws(tmp_path, files)
    evidence = _evidence(ws, _traceback(ws, *files), Limits(max_evidence_frames=20))
    context = _ctx(ws, evidence, max_evidence_frames=20, max_inspected_files=3)

    assert len(context.inspected_files) == 3


def test_file_body_is_bounded(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"big.py": "x = 1\n" * 20_000})
    context = _ctx(ws, _evidence(ws, _traceback(ws, "big.py")), max_inspect_file_bytes=300)

    assert len(context.files[0].body) <= 400  # body + the tool's truncation marker


def test_rendered_context_is_bounded(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"big.py": "x = 1\n" * 20_000})
    context = _ctx(
        ws, _evidence(ws, _traceback(ws, "big.py")), max_debug_context_chars=500
    )

    assert len(context.render()) <= 500
    assert context.truncated is True


def test_evidence_without_frames_still_builds_a_context(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART})
    context = _ctx(ws, _evidence(ws, "make: *** [all] Error 2\n"))

    assert context.inspected_files == []
    assert "FAILURE" in context.render()


def test_context_includes_a_bounded_listing(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART, "other.py": "y = 2\n"})
    context = _ctx(ws, _evidence(ws, _traceback(ws, "cart.py")))

    assert "cart.py" in context.listing
    assert "other.py" in context.listing


def test_secret_files_never_reach_the_context(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART, ".env": "ANTHROPIC_API_KEY=sk-live-real\n"})
    context = _ctx(ws, _evidence(ws, _traceback(ws, "cart.py")))

    rendered = context.render()
    assert "sk-live-real" not in rendered
    assert ".env" not in context.inspected_files


def test_context_carries_the_evidence_summary(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART})
    context = _ctx(ws, _evidence(ws, _traceback(ws, "cart.py")))

    assert "ValueError" in context.render()


def test_build_context_changes_no_files(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART})
    _ctx(ws, _evidence(ws, _traceback(ws, "cart.py")))

    assert ws.changed_files == []


def test_context_is_deterministic(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART, "other.py": CART})
    evidence = _evidence(ws, _traceback(ws, "cart.py"))

    assert _ctx(ws, evidence).render() == _ctx(ws, evidence).render()


# -- bounded, evidence-derived search expansion -----------------------------
#
# The gap these cover: a file that is genuinely relevant but never appears in
# the traceback. Search terms come from the traceback's own function names, so
# the expansion stays evidence-first rather than becoming a repository dump.

CART_SRC = (
    "def _discount(items):\n"
    "    return min(i.price for i in items)\n"
    "\n"
    "\n"
    "def cart_total(items):\n"
    "    return _discount(items)\n"
)
# A second entry point onto the same helper. Genuinely relevant -- it hits the
# same bug -- but absent from this run's traceback, which went through cart.py.
CHECKOUT = "from cart import _discount\n\n\ndef preview(items):\n    return _discount(items)\n"
UNRELATED = "def format_address(user):\n    return user.street\n"


def _suspect_traceback(ws: Workspace, file: str, function: str) -> str:
    return (
        "Traceback (most recent call last):\n"
        f'  File "{ws.root / file}", line 2, in {function}\n'
        "ValueError: min() arg is an empty sequence\n"
    )


def _searched(tmp_path: Path, **limit_overrides: object):
    ws = _ws(
        tmp_path, {"cart.py": CART_SRC, "checkout.py": CHECKOUT, "unrelated.py": UNRELATED}
    )
    evidence = _evidence(ws, _suspect_traceback(ws, "cart.py", "_discount"))
    return ws, _ctx(ws, evidence, **limit_overrides)


def test_search_discovers_a_relevant_file_absent_from_the_traceback(tmp_path: Path) -> None:
    _, context = _searched(tmp_path)

    assert "checkout.py" in context.inspected_files
    assert "cart.py" in context.inspected_files


def test_search_still_excludes_unrelated_files(tmp_path: Path) -> None:
    _, context = _searched(tmp_path)

    assert "unrelated.py" not in context.inspected_files
    assert "format_address" not in context.render()


def test_discovered_files_are_labelled_as_search_results(tmp_path: Path) -> None:
    _, context = _searched(tmp_path)
    by_path = {item.path: item.source for item in context.files}

    assert by_path["cart.py"] == "evidence"
    assert by_path["checkout.py"] == "search"


def test_evidence_files_always_precede_discovered_ones(tmp_path: Path) -> None:
    _, context = _searched(tmp_path)

    assert context.inspected_files.index("cart.py") < context.inspected_files.index("checkout.py")


def test_search_terms_come_from_traceback_function_names(tmp_path: Path) -> None:
    _, context = _searched(tmp_path)

    assert context.search_terms == ["_discount"]


def test_synthetic_frame_names_are_not_searched(tmp_path: Path) -> None:
    """`<module>` and friends are not symbols; searching them finds noise."""
    ws = _ws(tmp_path, {"cart.py": CART_SRC, "checkout.py": CHECKOUT})
    evidence = _evidence(ws, _suspect_traceback(ws, "cart.py", "<module>"))
    context = _ctx(ws, evidence)

    assert context.search_terms == []


def test_search_can_be_disabled_by_its_bound(tmp_path: Path) -> None:
    _, context = _searched(tmp_path, max_search_terms=0)

    assert context.search_terms == []
    assert context.inspected_files == ["cart.py"]


def test_discovered_file_count_is_bounded(tmp_path: Path) -> None:
    extra = {f"caller{n}.py": CHECKOUT for n in range(5)}
    extra.update({"cart.py": CART_SRC})
    ws = _ws(tmp_path, extra)
    evidence = _evidence(ws, _suspect_traceback(ws, "cart.py", "_discount"))
    context = _ctx(ws, evidence, max_searched_files=2)

    discovered = [item.path for item in context.files if item.source == "search"]
    assert len(discovered) == 2


def test_search_respects_the_overall_inspected_file_ceiling(tmp_path: Path) -> None:
    extra = {f"caller{n}.py": CHECKOUT for n in range(5)}
    extra.update({"cart.py": CART_SRC})
    ws = _ws(tmp_path, extra)
    evidence = _evidence(ws, _suspect_traceback(ws, "cart.py", "_discount"))
    context = _ctx(ws, evidence, max_inspected_files=2, max_searched_files=5)

    assert len(context.inspected_files) == 2


def test_search_never_surfaces_a_secret_file(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        {"cart.py": CART_SRC, ".env": "SECRET=_discount_token_leak\n", "checkout.py": CHECKOUT},
    )
    evidence = _evidence(ws, _suspect_traceback(ws, "cart.py", "_discount"))
    context = _ctx(ws, evidence)

    assert ".env" not in context.inspected_files
    assert "_discount_token_leak" not in context.render()


def test_search_expansion_changes_no_files(tmp_path: Path) -> None:
    ws, _ = _searched(tmp_path)

    assert ws.changed_files == []


def test_search_expansion_is_deterministic(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART_SRC, "checkout.py": CHECKOUT, "unrelated.py": UNRELATED})
    evidence = _evidence(ws, _suspect_traceback(ws, "cart.py", "_discount"))

    assert _ctx(ws, evidence).render() == _ctx(ws, evidence).render()
