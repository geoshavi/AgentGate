"""Offline, prompt-neutral evidence mining -- a research prototype.

Not wired into any authoritative or shadow path. `pipeline.py`, `verdict.py`,
`admissibility.py` and `adjudication.py` are untouched by this module and do
not call it. It exists to be exercised in isolation (`tests/test_evidence_mining.py`)
and by an offline historical replay, ahead of any decision to pre-register a
shadow-wiring experiment.

The problem this targets: Registration B showed that asking the judge for
*any* additional field -- even one framed as optional and severity-neutral --
shares the judge's single prompt and can move severity as a side effect. This
module never touches the judge. It reads exactly what the judge, under the
unmodified control prompt, already writes today: a defect's own free-text
``location``/``fix`` fields, plus the code snapshot already available to
every lens. From that alone, for exactly one narrow, generalisable shape --
a defect naming a declared, non-Optional, simple-typed parameter alongside a
small closed vocabulary of literal values that contradict that type -- it
recovers the same ``minimal_trigger`` shape a judge could otherwise have
supplied, and hands it to the *existing, unmodified* declared-interface
adjudication path (``adjudication._adjudicate_trigger`` via
``admissibility.decide``).

Fails closed by construction: any ambiguity -- no candidate parameter, more
than one competing (parameter, literal) pair, an Optional/union annotation,
an unparseable snapshot, a lowercase or otherwise non-literal spelling --
yields no evidence at all, which downstream leaves the defect exactly as
unadjudicated (and therefore exactly as blocking) as it is today.
"""

from __future__ import annotations

import ast
import re

from engine.verification.adjudication import _annotation_types, _collect_annotations

# Closed vocabulary of literal values a declared non-Optional simple type
# cannot admit. Deliberately small: each entry must be unambiguous as a
# Python literal in its own right (no bare numbers beyond zero, no strings
# with content) so that a match can never be mistaken for ordinary prose. "0"
# additionally excludes any adjacent word character (not just digits/dot), so
# a hex/other literal like "0x7f000001" -- observed verbatim in a real
# security-04-clean defect -- can never be mistaken for the integer zero.
# Order matters only for readability; every entry is tried independently.
_LITERAL_ALTERNATION = (
    r"None(?!\w)"
    r'|""'
    r"|''"
    r"|\[\]"
    r"|\{\}"
    r"|(?<![\w.])0(?![\w.])"
)

# A literal counts only inside an explicit "e.g." counter-example aside --
# "(e.g., None)", "(e.g. None or other type)" -- the one phrasing every
# genuine historical match in this dataset uses, confirmed by an offline
# replay across every v6 defect record. Requiring it (rather than treating it
# as optional) is what keeps a bare numeric range like "(0 <= hour <= 23)" --
# observed verbatim in a real, correctly-blocking edge_case-04-broken defect
# -- from ever being mistaken for a counter-example.
_PAREN_HINT = re.compile(r"\(\s*e\.g\.,?\s*(" + _LITERAL_ALTERNATION + r")")

# How far back from a matched literal to look for the parameter name it is
# describing. Generous enough for the observed phrasing ("Guard against user
# not being a dict (e.g., None...)"), narrow enough that an unrelated
# parameter mentioned much earlier in a long fix string is not swept in.
_LOOKBACK_CHARS = 80


def _candidate_parameters(code_snapshot: str) -> dict[str, type]:
    """Declared parameters whose annotation is a single, non-Optional simple type.

    Reuses adjudication.py's own annotation resolution so "simple type" and
    "Optional/union" mean exactly what they already mean to
    ``_adjudicate_trigger`` -- this module intentionally does not maintain a
    second notion of either.
    """
    collected = _collect_annotations(code_snapshot)
    if collected is None:
        return {}
    params, _returns = collected
    candidates: dict[str, type] = {}
    for name, annotation in params.items():
        types = _annotation_types(annotation)
        if types is None or len(types) != 1:
            continue
        (only_type,) = types
        if only_type is type(None):
            continue
        candidates[name] = only_type
    return candidates


def mine_trigger_evidence(defect: dict, task_text: str, code_snapshot: str) -> dict:
    """Recover a ``minimal_trigger`` from a defect's own free text, or nothing.

    ``task_text`` is accepted for interface symmetry with a possible future
    ``excluded_by_clause`` miner but is not read by this prototype -- it is
    scoped exclusively to the declared-interface / ``minimal_trigger`` route.

    Returns ``{"minimal_trigger": "<name>=<literal>"}`` on exactly one
    unambiguous match, else ``{}``. Never raises, never trusts a caller-typed
    field, never reads or writes severity, never mutates ``defect``.
    """
    del task_text  # reserved for a future, separately-scoped miner; unused here
    if not isinstance(defect, dict):
        return {}

    location = defect.get("location")
    fix = defect.get("fix")
    text = " ".join(v for v in (location, fix) if isinstance(v, str))
    if not text:
        return {}

    candidates = _candidate_parameters(code_snapshot)
    if not candidates:
        return {}

    hits: set[tuple[str, str]] = set()
    for match in _PAREN_HINT.finditer(text):
        literal = match.group(1)
        window = text[max(0, match.start() - _LOOKBACK_CHARS) : match.start()]
        nearby = [
            name
            for name in candidates
            if re.search(r"\b" + re.escape(name) + r"\b", window)
        ]
        # More than one candidate parameter in this occurrence's own window is
        # itself an unresolved ambiguity (which one is this literal about?),
        # and it also means the defect text has more than one parameter "in
        # play" -- both are reasons to give up on the whole defect, not just
        # this occurrence, so an ambiguous window poisons the result below via
        # the "more than one distinct parameter" check.
        if len(nearby) == 1:
            hits.add((nearby[0], literal))
        elif len(nearby) > 1:
            hits.update((name, literal) for name in nearby)

    distinct_params = {name for name, _ in hits}
    if len(distinct_params) != 1:
        return {}

    # Exactly one parameter is implicated; it must also point to exactly one
    # literal -- "user=None" and "user=[]" both present would be a different,
    # equally unresolved kind of ambiguity.
    if len(hits) != 1:
        return {}

    (name, literal) = next(iter(hits))
    return {"minimal_trigger": f"{name}={literal}"}


# ==========================================================================
# mine_return_value_evidence -- a second, independent miner
#
# Targets a different adjudication Fact entirely: not "does a caller-supplied
# argument contradict a declared parameter type" (adjudication._adjudicate_trigger,
# above), but "does the function's own return statement, in the shape the
# judge is objecting to, contradict its own declared return type"
# (adjudication._adjudicate_return -> rule "factual-premise"). Wholly
# independent of mine_trigger_evidence: does not read its vocabulary, its
# regex, or its parameter-candidate logic, and does not change any of it.
# ==========================================================================

# Bounded objection phrases only -- never bare "type"/"isinstance"/
# "validation"/"defensive" on their own. Each phrase was observed verbatim
# (or as a direct paraphrase) in the three historical defects this targets;
# the infix in the "do not filter" variant is capped at 20 characters so it
# cannot drift into matching an unrelated sentence spanning the same words.
_RETURN_OBJECTION = re.compile(
    r"regardless of (?:its|the) type"
    r"|without filtering (?:on|by) type"
    r"|do not filter (?:based on|by) [\w' ]{0,20}type"
    r"|return(?:ing|s|ed)?\b[^.;]{0,40}\bas[- ]is\b",
    re.IGNORECASE,
)


def _statements_in_own_scope(node: ast.AST):
    """Yield every descendant statement of ``node``, without crossing into a
    nested function/lambda's own scope -- a nested def's return statements
    belong to it, not to ``node``, and must never be attributed to the wrong
    function's return annotation."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        yield child
        yield from _statements_in_own_scope(child)


def _return_none_ifexp_candidates(code_snapshot: str) -> list[tuple[str, str]]:
    """Every ``(name, type_name)`` pair for a return statement shaped exactly
    ``<name> if isinstance(<name>, <type_name>) else None``, inside a function
    whose own declared return annotation admits ``NoneType``. Proof, not a
    guess: identity between the ternary's test subject and its true-branch is
    checked structurally, and the annotation is resolved the same way
    ``adjudication._adjudicate_return`` itself resolves it.
    """
    try:
        tree = ast.parse(code_snapshot)
    except (SyntaxError, ValueError):
        return []

    candidates: list[tuple[str, str]] = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        return_types = _annotation_types(func.returns)
        if return_types is None or type(None) not in return_types:
            continue
        for stmt in _statements_in_own_scope(func):
            if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.IfExp):
                continue
            ifexp = stmt.value
            test = ifexp.test
            if not (
                isinstance(test, ast.Call)
                and isinstance(test.func, ast.Name)
                and test.func.id == "isinstance"
                and len(test.args) == 2
                and isinstance(test.args[0], ast.Name)
                and isinstance(test.args[1], ast.Name)
            ):
                continue
            tested_name = test.args[0].id
            if not (isinstance(ifexp.body, ast.Name) and ifexp.body.id == tested_name):
                continue
            if not (isinstance(ifexp.orelse, ast.Constant) and ifexp.orelse.value is None):
                continue
            candidates.append((tested_name, test.args[1].id))
    return candidates


def mine_return_value_evidence(defect: dict, task_text: str, code_snapshot: str) -> dict:
    """Recover a ``return=None`` trigger from a defect's own free text, or nothing.

    Fires only when BOTH hold: (1) exactly one function in the whole snapshot
    has exactly one return statement shaped
    ``<name> if isinstance(<name>, <type>) else None``, with its own declared
    return annotation admitting ``NoneType`` -- proving that returning
    ``None`` there is genuinely in-contract, not merely plausible -- and (2)
    the defect's own ``location``/``fix`` text contains one of a small,
    bounded set of phrases objecting to exactly that type-filter-to-None
    shape. More than one qualifying function or return statement anywhere in
    the snapshot is an unresolved ambiguity, not a pick-one.

    ``task_text`` is unused, kept for interface symmetry with
    ``mine_trigger_evidence``. Never raises, never mutates ``defect``, never
    touches severity, never marks admissibility -- ``adjudication._adjudicate_return``
    via ``admissibility.decide`` remains the sole authority over what this
    evidence resolves to.
    """
    del task_text
    if not isinstance(defect, dict):
        return {}

    location = defect.get("location")
    fix = defect.get("fix")
    text = " ".join(v for v in (location, fix) if isinstance(v, str))
    if not text or not _RETURN_OBJECTION.search(text):
        return {}

    candidates = _return_none_ifexp_candidates(code_snapshot)
    if len(candidates) != 1:
        return {}

    return {"minimal_trigger": "return=None"}
