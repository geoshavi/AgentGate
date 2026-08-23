"""D2: the structured root-cause hypothesis.

The discipline under test is the same one D1 established: where a fact is
available to the harness, the harness owns it. The model proposes a diagnosis;
this layer decides whether the diagnosis points at anything real, and computes
the confidence label itself rather than believing the one it was handed.

Offline throughout -- every model response is scripted.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import MODEL, ScriptedProvider

from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.state import SessionStatus
from engine.codeagent.workspace import Workspace
from engine.debugagent.evidence import build_evidence
from engine.debugagent.repro import freeze_repro
from engine.debugagent.rootcause import (
    Confidence,
    DiagnosisStatus,
    RootCause,
    diagnose,
    parse_rootcause_block,
    validate_rootcause,
)
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway

CART = "".join(f"line {n}\n" for n in range(1, 31))  # 30 lines


def rootcause_block(**payload: object) -> str:
    return f"```rootcause\n{json.dumps(payload)}\n```"


def valid_payload(**overrides: object) -> dict:
    payload: dict = {
        "summary": "min() is called on an unguarded sequence",
        "mechanism": "cart_total applies the discount before checking the cart is non-empty",
        "primary_file": "cart.py",
        "primary_line": 23,
        "related_files": ["helper.py"],
        "evidence_refs": ["traceback names cart.py:23"],
        "proposed_fix": "guard the discount computation",
        "validation_plan": [["python", "-m", "pytest", "-q"]],
    }
    payload.update(overrides)
    return payload


def _ws(tmp_path: Path, files: dict[str, str] | None = None) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    for relative, content in (files or {"cart.py": CART, "helper.py": CART}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Workspace(root)


def _evidence(ws: Workspace, *, line: int = 23, file: str = "cart.py", frames: bool = True):
    stderr = (
        "Traceback (most recent call last):\n"
        + (f'  File "{ws.root / file}", line {line}, in _discount\n' if frames else "")
        + "ValueError: min() arg is an empty sequence\n"
    )
    return build_evidence(
        argv=["python", "-m", "pytest", "-q"],
        stdout="",
        stderr=stderr,
        exit_code=1,
        timed_out=False,
        duration_ms=7,
        workspace=ws,
        limits=Limits(),
    )


def _validate(ws: Workspace, payload: dict, evidence=None, **limit_overrides: object):
    return validate_rootcause(
        payload,
        workspace=ws,
        evidence=evidence if evidence is not None else _evidence(ws),
        policy=DEFAULT_POLICY,
        limits=Limits(**limit_overrides),  # type: ignore[arg-type]
    )


def _diagnose(
    tmp_path: Path,
    responses: list[str],
    *,
    limits: Limits | None = None,
    ws: Workspace | None = None,
    log: SessionLog | None = None,
    raise_on_call: int | None = None,
    max_tokens: int = 1_000_000,
):
    workspace = ws if ws is not None else _ws(tmp_path)
    provider = ScriptedProvider(responses, raise_on_call=raise_on_call)
    outcome = diagnose(
        task_text="cart_total crashes on an empty cart",
        evidence=_evidence(workspace),
        repro=freeze_repro(["python", "-m", "pytest", "-q"]),
        workspace=workspace,
        gateway=LLMGateway(provider),
        budget=BudgetController(max_tokens=max_tokens, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="dbg-test",
        limits=limits if limits is not None else Limits(),
        policy=DEFAULT_POLICY,
        log=log,
    )
    return outcome, provider


# -- parsing ----------------------------------------------------------------


def test_parses_a_rootcause_block() -> None:
    payload, error = parse_rootcause_block(rootcause_block(**valid_payload()))

    assert error is None
    assert payload is not None
    assert payload["primary_file"] == "cart.py"


def test_malformed_json_is_reported() -> None:
    payload, error = parse_rootcause_block('```rootcause\n{"summary": nope}\n```')

    assert payload is None
    assert error is not None
    assert "not valid JSON" in error


def test_missing_block_is_reported() -> None:
    payload, error = parse_rootcause_block("I think the bug is in cart.py.")

    assert payload is None
    assert error is not None


def test_two_blocks_are_reported() -> None:
    text = rootcause_block(**valid_payload()) + "\n" + rootcause_block(**valid_payload())
    payload, error = parse_rootcause_block(text)

    assert payload is None
    assert error is not None


# -- validation: the happy path --------------------------------------------


def test_valid_payload_produces_a_root_cause(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, errors = _validate(ws, valid_payload())

    assert errors == []
    assert isinstance(cause, RootCause)
    assert cause.primary_file == "cart.py"
    assert cause.primary_line == 23
    assert cause.related_files == ["helper.py"]
    assert cause.validation_plan == [["python", "-m", "pytest", "-q"]]


# -- validation: paths and lines -------------------------------------------


def test_nonexistent_primary_file_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(primary_file="ghost.py"))

    assert cause is None
    assert any("ghost.py" in e for e in errors)


def test_outside_workspace_primary_file_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(primary_file="../outside.py"))

    assert cause is None
    assert any("outside.py" in e for e in errors)


def test_absolute_primary_file_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(primary_file="/etc/passwd"))

    assert cause is None
    assert errors != []


def test_secret_primary_file_is_rejected(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART, ".env": "ANTHROPIC_API_KEY=sk-live\n"})
    cause, errors = _validate(ws, valid_payload(primary_file=".env", related_files=[]))

    assert cause is None
    assert errors != []


def test_line_beyond_end_of_file_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(primary_line=9_999))

    assert cause is None
    assert any("9999" in e or "30" in e for e in errors)


def test_zero_line_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(primary_line=0))

    assert cause is None
    assert errors != []


def test_non_integer_line_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(primary_line="twenty-three"))

    assert cause is None
    assert errors != []


def test_last_line_of_file_is_accepted(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(primary_line=30))

    assert errors == []
    assert cause is not None


# -- validation: related files ---------------------------------------------


def test_secret_related_file_is_rejected(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": CART, ".env": "K=v\n"})
    cause, errors = _validate(ws, valid_payload(related_files=[".env"]))

    assert cause is None
    assert errors != []


def test_nonexistent_related_file_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(related_files=["nope.py"]))

    assert cause is None
    assert errors != []


def test_related_files_are_bounded(tmp_path: Path) -> None:
    files = {f"m{n}.py": CART for n in range(8)}
    files["cart.py"] = CART
    ws = _ws(tmp_path, files)
    cause, errors = _validate(
        ws, valid_payload(related_files=[f"m{n}.py" for n in range(8)]), max_related_files=3
    )

    assert cause is None
    assert any("max_related_files" in e for e in errors)


def test_primary_file_is_not_repeated_in_related(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, errors = _validate(ws, valid_payload(related_files=["cart.py", "helper.py"]))

    assert errors == []
    assert cause is not None
    assert cause.related_files == ["helper.py"]


# -- validation: required fields and commands ------------------------------


@pytest.mark.parametrize("field", ["summary", "mechanism", "proposed_fix", "primary_file"])
def test_missing_required_field_is_rejected(tmp_path: Path, field: str) -> None:
    payload = valid_payload()
    del payload[field]
    cause, errors = _validate(_ws(tmp_path), payload)

    assert cause is None
    assert any(field in e for e in errors)


def test_empty_summary_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(_ws(tmp_path), valid_payload(summary="   "))

    assert cause is None
    assert errors != []


def test_disallowed_validation_command_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(
        _ws(tmp_path), valid_payload(validation_plan=[["git", "push", "--force"]])
    )

    assert cause is None
    assert any("git" in e for e in errors)


def test_shell_string_validation_command_is_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(
        _ws(tmp_path), valid_payload(validation_plan=["python -m pytest"])
    )

    assert cause is None
    assert errors != []


def test_too_many_validation_commands_are_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(
        _ws(tmp_path),
        valid_payload(validation_plan=[["python", "-m", "pytest"]] * 5),
        max_rootcause_validation_commands=2,
    )

    assert cause is None
    assert errors != []


def test_long_text_is_clipped_not_rejected(tmp_path: Path) -> None:
    cause, errors = _validate(
        _ws(tmp_path), valid_payload(summary="z" * 5_000), max_root_cause_text_chars=100
    )

    assert errors == []
    assert cause is not None
    assert len(cause.summary) <= 100


# -- confidence is computed, never accepted --------------------------------


def test_confidence_is_observed_when_file_and_line_match_the_traceback(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, errors = _validate(ws, valid_payload(), _evidence(ws, line=23))

    assert errors == []
    assert cause is not None
    assert cause.confidence is Confidence.OBSERVED


def test_confidence_is_corroborated_when_only_the_file_matches(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, _ = _validate(ws, valid_payload(primary_line=5), _evidence(ws, line=23))

    assert cause is not None
    assert cause.confidence is Confidence.CORROBORATED


def test_confidence_is_inferred_when_the_file_is_not_in_the_traceback(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, _ = _validate(
        ws, valid_payload(primary_file="helper.py", related_files=[]), _evidence(ws, file="cart.py")
    )

    assert cause is not None
    assert cause.confidence is Confidence.INFERRED


def test_confidence_is_inferred_when_there_are_no_frames(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, _ = _validate(ws, valid_payload(), _evidence(ws, frames=False))

    assert cause is not None
    assert cause.confidence is Confidence.INFERRED


def test_model_supplied_confidence_is_ignored(tmp_path: Path) -> None:
    """A model claiming OBSERVED for an uncorroborated file must not get it."""
    ws = _ws(tmp_path)
    cause, _ = _validate(
        ws,
        valid_payload(primary_file="helper.py", related_files=[], confidence="OBSERVED"),
        _evidence(ws, file="cart.py"),
    )

    assert cause is not None
    assert cause.confidence is Confidence.INFERRED


# -- the diagnose loop ------------------------------------------------------


def test_valid_first_response_is_accepted(tmp_path: Path) -> None:
    outcome, provider = _diagnose(tmp_path, [rootcause_block(**valid_payload())])

    assert outcome.status is DiagnosisStatus.OK
    assert outcome.attempts == 1
    assert provider.calls == 1
    assert outcome.root_cause is not None
    assert outcome.terminal_status is None


def test_malformed_then_valid_recovers_on_the_retry(tmp_path: Path) -> None:
    outcome, provider = _diagnose(
        tmp_path, ["no block at all", rootcause_block(**valid_payload())]
    )

    assert outcome.status is DiagnosisStatus.OK
    assert outcome.attempts == 2
    assert provider.calls == 2


def test_errors_are_fed_back_on_the_retry(tmp_path: Path) -> None:
    _, provider = _diagnose(
        tmp_path,
        [rootcause_block(**valid_payload(primary_file="ghost.py")), rootcause_block(**valid_payload())],
    )

    retry_prompt = provider.seen_messages[-1][-1].content
    assert "ghost.py" in retry_prompt


def test_attempts_are_exhausted_and_rejected(tmp_path: Path) -> None:
    outcome, provider = _diagnose(tmp_path, ["garbage", "still garbage", "more garbage"])

    assert outcome.status is DiagnosisStatus.REJECTED
    assert outcome.root_cause is None
    assert outcome.attempts == 2
    assert provider.calls == 2
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_ROOT_CAUSE


def test_no_diagnosis_is_fabricated_when_rejected(tmp_path: Path) -> None:
    outcome, _ = _diagnose(tmp_path, ["garbage"])

    assert outcome.root_cause is None
    assert outcome.errors != []


def test_provider_failure_is_unavailable_not_a_crash(tmp_path: Path) -> None:
    outcome, _ = _diagnose(tmp_path, [rootcause_block(**valid_payload())], raise_on_call=1)

    assert outcome.status is DiagnosisStatus.UNAVAILABLE
    assert outcome.root_cause is None
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_ROOT_CAUSE


def test_budget_exhaustion_is_unavailable(tmp_path: Path) -> None:
    outcome, provider = _diagnose(
        tmp_path, [rootcause_block(**valid_payload())], max_tokens=1
    )

    assert outcome.status is DiagnosisStatus.UNAVAILABLE
    assert provider.calls == 0


def test_attempt_bound_is_configurable(tmp_path: Path) -> None:
    outcome, provider = _diagnose(
        tmp_path, ["garbage"] * 5, limits=Limits(max_rootcause_attempts=1)
    )

    assert provider.calls == 1
    assert outcome.attempts == 1


# -- what D2 must not do ----------------------------------------------------


def test_diagnosis_changes_no_files(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    _diagnose(tmp_path, [rootcause_block(**valid_payload())], ws=ws)

    assert ws.changed_files == []


def test_diagnosis_changes_no_files_even_when_rejected(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    _diagnose(tmp_path, ["garbage", "garbage"], ws=ws)

    assert ws.changed_files == []


def test_no_write_tool_is_offered_to_the_diagnosing_model(tmp_path: Path) -> None:
    _, provider = _diagnose(tmp_path, [rootcause_block(**valid_payload())])
    system = provider.seen_systems[0] or ""

    assert "write_file" not in system
    assert "replace_exact" not in system


def test_the_prompt_carries_evidence_and_inspected_code(tmp_path: Path) -> None:
    _, provider = _diagnose(tmp_path, [rootcause_block(**valid_payload())])
    prompt = provider.seen_messages[0][0].content

    assert "ValueError" in prompt
    assert "cart.py" in prompt


def test_inspected_files_are_recorded(tmp_path: Path) -> None:
    outcome, _ = _diagnose(tmp_path, [rootcause_block(**valid_payload())])

    assert "cart.py" in outcome.inspected_files


def test_usage_counts_are_recorded(tmp_path: Path) -> None:
    outcome, _ = _diagnose(tmp_path, [rootcause_block(**valid_payload())])

    assert outcome.input_tokens > 0
    assert outcome.output_tokens > 0


# -- logging holds no prose -------------------------------------------------


def test_log_records_counts_never_model_text(tmp_path: Path) -> None:
    log = SessionLog()
    _diagnose(tmp_path, [rootcause_block(**valid_payload())], log=log)

    attempts = log.of_kind("rootcause_attempt")
    assert attempts
    payload = attempts[0].payload
    assert "text_chars" in payload
    assert "text" not in payload


def test_rejected_attempts_log_errors_not_the_response(tmp_path: Path) -> None:
    log = SessionLog()
    _diagnose(tmp_path, ["garbage", "garbage"], log=log)

    rejected = log.of_kind("rootcause_rejected")
    assert rejected
    assert "errors" in rejected[0].payload
    assert "garbage" not in json.dumps(rejected[0].payload)


def test_result_is_logged_with_its_status(tmp_path: Path) -> None:
    log = SessionLog()
    _diagnose(tmp_path, [rootcause_block(**valid_payload())], log=log)

    results = log.of_kind("rootcause_result")
    assert results
    assert results[0].payload["status"] == "OK"


# -- serialization ----------------------------------------------------------


def test_root_cause_serializes_to_json(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, _ = _validate(ws, valid_payload())

    assert cause is not None
    payload = json.loads(json.dumps(cause.as_dict()))
    assert payload["confidence"] == "OBSERVED"
    assert payload["primary_file"] == "cart.py"


def test_root_cause_carries_no_hidden_reasoning_field(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    cause, _ = _validate(ws, valid_payload(thinking="secret chain of thought"))

    assert cause is not None
    payload = cause.as_dict()
    assert "thinking" not in payload
    assert "secret chain of thought" not in json.dumps(payload)


# -- no direct provider access ----------------------------------------------


def test_d2_modules_reach_the_model_only_through_the_gateway() -> None:
    import ast

    from engine import debugagent

    root = Path(debugagent.__file__).parent
    banned_sdks = ("anthropic", "openai", "httpx")
    violations: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(banned_sdks) or name.startswith("engine.providers"):
                    violations.append(f"{path.name}: {name}")

    assert violations == []


def test_d1_modules_still_reach_no_runtime_at_all() -> None:
    """D1 stays model-free even though D2 next door now uses a gateway."""
    import ast

    from engine.debugagent import evidence, repro

    for module in (evidence, repro):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n.startswith("engine.runtime") for n in names), module.__name__


# -- model usage accounting -------------------------------------------------
#
# Usage must total ACROSS attempts, not report only the successful one: a run
# that needed a retry cost two calls and the accounting has to say so.


class ThinkingProvider(ScriptedProvider):
    """A scripted provider that also reports reasoning-token counts.

    ``ScriptedProvider`` leaves ``thinking_tokens`` at its default of 0, which
    is indistinguishable from a provider that does not report them. This one
    sets it so the accumulation can actually be observed.
    """

    name = "thinking"

    def generate(self, *args: object, **kwargs: object):  # type: ignore[override]
        from dataclasses import replace as _replace

        result = super().generate(*args, **kwargs)  # type: ignore[arg-type]
        return _replace(result, thinking_tokens=7)


def _diagnose_with(tmp_path: Path, provider: ScriptedProvider):
    ws = _ws(tmp_path)
    return diagnose(
        task_text="cart_total crashes on an empty cart",
        evidence=_evidence(ws),
        repro=freeze_repro(["python", "-m", "pytest", "-q"]),
        workspace=ws,
        gateway=LLMGateway(provider),
        budget=BudgetController(max_tokens=1_000_000, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="dbg-usage",
        limits=Limits(),
        policy=DEFAULT_POLICY,
    )


def test_single_attempt_records_one_model_call(tmp_path: Path) -> None:
    outcome, _ = _diagnose(tmp_path, [rootcause_block(**valid_payload())])

    assert outcome.model_calls == 1


def test_usage_totals_across_a_malformed_first_response_and_a_retry(tmp_path: Path) -> None:
    """The retry is real work and real money; the totals must include it."""
    outcome, provider = _diagnose(
        tmp_path, ["not a block", rootcause_block(**valid_payload())]
    )

    assert outcome.status is DiagnosisStatus.OK
    assert provider.calls == 2
    assert outcome.model_calls == 2
    # ScriptedProvider reports 10 in / 20 out per call.
    assert outcome.input_tokens == 20
    assert outcome.output_tokens == 40


def test_usage_totals_when_every_attempt_is_rejected(tmp_path: Path) -> None:
    outcome, _ = _diagnose(tmp_path, ["garbage", "garbage"])

    assert outcome.status is DiagnosisStatus.REJECTED
    assert outcome.model_calls == 2
    assert outcome.input_tokens == 20
    assert outcome.output_tokens == 40


def test_thinking_tokens_are_recorded_when_the_gateway_reports_them(tmp_path: Path) -> None:
    outcome = _diagnose_with(tmp_path, ThinkingProvider([rootcause_block(**valid_payload())]))

    assert outcome.thinking_tokens == 7


def test_thinking_tokens_accumulate_across_retries(tmp_path: Path) -> None:
    outcome = _diagnose_with(
        tmp_path, ThinkingProvider(["not a block", rootcause_block(**valid_payload())])
    )

    assert outcome.model_calls == 2
    assert outcome.thinking_tokens == 14


def test_thinking_tokens_are_zero_when_unreported(tmp_path: Path) -> None:
    """Zero means 'not reported', and must not be confused with an error."""
    outcome, _ = _diagnose(tmp_path, [rootcause_block(**valid_payload())])

    assert outcome.thinking_tokens == 0


def test_thinking_tokens_are_a_count_never_text(tmp_path: Path) -> None:
    outcome = _diagnose_with(tmp_path, ThinkingProvider([rootcause_block(**valid_payload())]))

    assert isinstance(outcome.thinking_tokens, int)


def test_a_first_call_that_raises_still_counts_as_one_attempt(tmp_path: Path) -> None:
    """model_calls counts requests made, not results returned.

    The request left the building and may well have been billed; reporting zero
    would describe a run that never contacted the provider.
    """
    outcome, _ = _diagnose(tmp_path, [rootcause_block(**valid_payload())], raise_on_call=1)

    assert outcome.status is DiagnosisStatus.UNAVAILABLE
    assert outcome.model_calls == 1
    # Nothing came back, so nothing is claimed. Usage is never estimated.
    assert outcome.input_tokens == 0
    assert outcome.output_tokens == 0
    assert outcome.thinking_tokens == 0


def test_a_raising_retry_counts_but_contributes_no_tokens(tmp_path: Path) -> None:
    """Two attempts were made; only the first returned usage."""
    outcome, _ = _diagnose(tmp_path, ["garbage", "unused"], raise_on_call=2)

    assert outcome.status is DiagnosisStatus.UNAVAILABLE
    assert outcome.model_calls == 2
    # Exactly the first call's returned usage -- the second added nothing.
    assert outcome.input_tokens == 10
    assert outcome.output_tokens == 20


def test_budget_exhaustion_still_counts_the_attempt(tmp_path: Path) -> None:
    """The gateway was invoked; it refused before reaching the provider."""
    outcome, provider = _diagnose(
        tmp_path, [rootcause_block(**valid_payload())], max_tokens=1
    )

    assert outcome.status is DiagnosisStatus.UNAVAILABLE
    assert outcome.model_calls == 1
    assert provider.calls == 0
    assert outcome.input_tokens == 0


def test_usage_is_logged_per_attempt(tmp_path: Path) -> None:
    log = SessionLog()
    _diagnose(tmp_path, ["garbage", rootcause_block(**valid_payload())], log=log)

    attempts = log.of_kind("rootcause_attempt")
    assert len(attempts) == 2
    assert all("input_tokens" in event.payload for event in attempts)
    assert all("thinking_tokens" in event.payload for event in attempts)


def test_diagnosis_context_log_payload_is_flat(tmp_path: Path) -> None:
    """Same nesting defect as the repro events -- see that test for why."""
    log = SessionLog()
    _diagnose(tmp_path, [rootcause_block(**valid_payload())], log=log)

    payload = log.of_kind("diagnosis_context")[0].payload

    assert "payload" not in payload
    assert payload["inspected_files"] == ["cart.py"]
