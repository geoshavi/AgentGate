"""Independent adjudication of the evidence a judge attaches to a defect.

The separation this module exists to enforce: a judge *asserts*, the adjudicator
*decides*. Nothing a model writes is accepted as a verified fact. Every field it
supplies is treated as a claim to be checked against the task text, the
submitted source, or a registered probe -- and anything that cannot be checked
lands on UNRESOLVED, which downstream means the finding keeps its authority.

All evidence is optional. A defect carrying none of it is not malformed; it is
simply unadjudicated, and `enforce_critic_schema` is deliberately not taught
about these keys. That is the lesson from the rejected structured-grounding
contract: making the evidence *required* gave the judge a reason to move
severity around, which is how a blocking finding became a MEDIUM one.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from engine.verification.probes import ProbeResult, run_probe
from engine.verification.rubric import GROUNDING_ROUTES

ADJUDICATOR_VERSION = "adjudication/1"

VERIFIED = "VERIFIED"
CONTRADICTED = "CONTRADICTED"
UNSUPPORTED = "UNSUPPORTED"
UNRESOLVED = "UNRESOLVED"

# Literal markers only, and only ones that state the retraction outright. These
# are recorded for forensics; on their own they never remove blocking authority,
# because corroborating them against the source is not something this module can
# do yet. See admissibility.decide.
_RETRACTION_MARKERS: tuple[str, ...] = (
    "no fix needed",
    "not actually reachable",
    "trigger: none",
    "retracted concern",
)

# Annotations resolvable to a concrete runtime type. Anything else -- a
# subscript, an attribute, a string annotation, a bare alias -- is left alone
# and yields UNRESOLVED rather than a guess.
_SIMPLE_TYPES: dict[str, type] = {
    "bool": bool,
    "bytes": bytes,
    "dict": dict,
    "float": float,
    "int": int,
    "list": list,
    "set": set,
    "str": str,
    "tuple": tuple,
}

_RETURN = "return"


@dataclass(frozen=True)
class Evidence:
    """Exactly what the judge supplied, after discarding anything malformed."""

    grounded_in_clause: str | None = None
    excluded_by_clause: str | None = None
    minimal_trigger: str | None = None
    grounding_route: str | None = None
    runtime_probe: dict[str, Any] | None = None


@dataclass(frozen=True)
class Fact:
    status: str
    rule: str
    detail: str = ""


@dataclass(frozen=True)
class Adjudication:
    trigger_in_contract: Fact
    premise_excluded_by_guarantee: Fact
    premise_depends_on_runtime_behaviour: Fact
    violation_present_in_submitted_code: Fact
    self_contradiction: Fact
    probe: ProbeResult | None = None


_UNRESOLVED_FACT = Fact(UNRESOLVED, "no-evidence")


def _unresolved() -> Adjudication:
    return Adjudication(
        trigger_in_contract=_UNRESOLVED_FACT,
        premise_excluded_by_guarantee=_UNRESOLVED_FACT,
        premise_depends_on_runtime_behaviour=_UNRESOLVED_FACT,
        violation_present_in_submitted_code=_UNRESOLVED_FACT,
        self_contradiction=_UNRESOLVED_FACT,
    )


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def extract_evidence(defect: dict) -> Evidence:
    """Pull the optional evidence keys off a defect. Never raises, never trusts."""
    if not isinstance(defect, dict):
        return Evidence()

    route = _text(defect.get("grounding_route"))
    if route not in GROUNDING_ROUTES:
        route = None

    probe = defect.get("runtime_probe")
    if not (
        isinstance(probe, dict)
        and isinstance(probe.get("predicate"), str)
        and isinstance(probe.get("argument"), str)
    ):
        probe = None

    return Evidence(
        grounded_in_clause=_text(defect.get("grounded_in_clause")),
        excluded_by_clause=_text(defect.get("excluded_by_clause")),
        minimal_trigger=_text(defect.get("minimal_trigger")),
        grounding_route=route,
        runtime_probe=probe,
    )


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _annotation_types(node: ast.expr | None) -> frozenset[type] | None:
    """Resolve an annotation to concrete types, or None if it is not simple."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        resolved = _SIMPLE_TYPES.get(node.id)
        return frozenset({resolved}) if resolved is not None else None
    if isinstance(node, ast.Constant) and node.value is None:
        return frozenset({type(None)})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _annotation_types(node.left)
        right = _annotation_types(node.right)
        return None if left is None or right is None else left | right
    return None


def _collect_annotations(
    code: str,
) -> tuple[dict[str, ast.expr | None], list[ast.expr | None]] | None:
    """(parameter name -> annotation, public return annotations). None if unparseable."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None

    params: dict[str, ast.expr | None] = {}
    returns: list[ast.expr | None] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for arg in [*node.args.args, *node.args.kwonlyargs]:
                params.setdefault(arg.arg, arg.annotation)
            if not node.name.startswith("_"):
                returns.append(node.returns)
    return params, returns


def _parse_trigger(text: str | None) -> tuple[str, Any] | None:
    """Parse the ``<name>=<python literal>`` grammar. None if it is anything else."""
    if not text or "=" not in text:
        return None
    name, _, literal = text.partition("=")
    name = name.strip()
    if not name.isidentifier():
        return None
    try:
        return name, ast.literal_eval(literal.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def _adjudicate_trigger(
    trigger: tuple[str, Any] | None, params: dict[str, ast.expr | None] | None
) -> Fact:
    if trigger is None or params is None:
        return _UNRESOLVED_FACT
    name, value = trigger
    if name == _RETURN or name not in params:
        return Fact(UNRESOLVED, "declared-interface", f"no declared parameter {name!r}")
    types = _annotation_types(params[name])
    if types is None:
        return Fact(UNRESOLVED, "declared-interface", "annotation is not a simple type")
    if type(value) in types:
        return Fact(VERIFIED, "declared-interface", f"{name} admits {type(value).__name__}")
    return Fact(
        CONTRADICTED,
        "declared-interface",
        f"{name} is annotated {sorted(t.__name__ for t in types)}, "
        f"witness is {type(value).__name__}",
    )


def _adjudicate_guarantee(clause: str | None, task_text: str) -> Fact:
    if clause is None:
        return _UNRESOLVED_FACT
    if _normalize(clause) in _normalize(task_text):
        return Fact(VERIFIED, "explicit-guarantee", "clause quoted verbatim from the task")
    return Fact(UNSUPPORTED, "explicit-guarantee", "clause is not a verbatim span of the task")


def _adjudicate_probe(probe: dict[str, Any] | None) -> tuple[Fact, ProbeResult | None]:
    """A probe may only ever CONTRADICT a premise. It can never verify one."""
    if probe is None:
        return _UNRESOLVED_FACT, None

    result = run_probe(str(probe["predicate"]), str(probe["argument"]))
    claim = probe.get("claim")

    if not result.ok:
        return Fact(UNRESOLVED, "runtime-probe", result.error), result
    if not isinstance(claim, bool):
        return Fact(UNRESOLVED, "runtime-probe", "no boolean claim to refute"), result
    if result.value != claim:
        return (
            Fact(
                CONTRADICTED,
                "runtime-probe",
                f"{result.predicate}({result.argument!r}) is {result.value}, "
                f"claim was {claim} (python {result.interpreter_version})",
            ),
            result,
        )
    return Fact(UNRESOLVED, "runtime-probe", "probe agrees with the claim; grants nothing"), result


def _adjudicate_return(
    trigger: tuple[str, Any] | None, returns: list[ast.expr | None] | None
) -> Fact:
    if trigger is None or not returns or len(returns) != 1:
        return _UNRESOLVED_FACT
    name, value = trigger
    if name != _RETURN:
        return _UNRESOLVED_FACT
    types = _annotation_types(returns[0])
    if types is None:
        return Fact(UNRESOLVED, "declared-return-type", "annotation is not a simple type")
    if type(value) in types:
        return Fact(
            CONTRADICTED,
            "declared-return-type",
            f"declared return admits {type(value).__name__}",
        )
    return Fact(UNRESOLVED, "declared-return-type", "declared return does not admit the witness")


def _adjudicate_retraction(defect: dict) -> Fact:
    prose = " ".join(
        str(defect.get(key, "")) for key in ("fix", "location", "violated_requirement", "trigger")
    ).lower()
    for marker in _RETRACTION_MARKERS:
        if marker in prose:
            return Fact(VERIFIED, "retraction", f"prose contains {marker!r}")
    return Fact(UNRESOLVED, "retraction", "no explicit retraction marker")


def adjudicate(
    defect: dict, evidence: Evidence, task_text: str, code_snapshot: str
) -> Adjudication:
    """Decide each fact independently. Never raises, never mutates ``defect``."""
    try:
        collected = _collect_annotations(code_snapshot)
        params = collected[0] if collected else None
        returns = collected[1] if collected else None
        trigger = _parse_trigger(evidence.minimal_trigger)

        probe_fact, probe_result = _adjudicate_probe(evidence.runtime_probe)
        violation = probe_fact
        if violation.status != CONTRADICTED and evidence.runtime_probe is None:
            violation = _adjudicate_return(trigger, returns)

        depends = (
            Fact(VERIFIED, "runtime-probe", "settled by a registered probe")
            if probe_result is not None and probe_result.ok
            else _UNRESOLVED_FACT
        )

        return Adjudication(
            trigger_in_contract=_adjudicate_trigger(trigger, params),
            premise_excluded_by_guarantee=_adjudicate_guarantee(
                evidence.excluded_by_clause, task_text
            ),
            premise_depends_on_runtime_behaviour=depends,
            violation_present_in_submitted_code=violation,
            self_contradiction=_adjudicate_retraction(defect),
            probe=probe_result,
        )
    except Exception:  # noqa: BLE001 -- adjudication failure must fail safe, not propagate
        return _unresolved()
