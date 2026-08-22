import json
import sys
from decimal import Decimal
from pathlib import Path

from engine.providers.base import GenerationResult, Message
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state import db
from engine.state.models import EvalCaseResult, VerificationResult
from engine.verification import pipeline, verdict
from engine.verification.automated import _run, automated_defects, run_automated_gates
from engine.verification.judge import _extract_json_objects, _parse_critic, run_judge_gates
from engine.verification.schema import enforce_critic_schema


def test_automated_gates_pass_on_clean_code(tmp_path: Path) -> None:
    (tmp_path / "solution.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

    results = run_automated_gates(tmp_path)

    by_gate = {r.gate_name: r for r in results}
    assert by_gate["ruff"].passed
    assert by_gate["pytest"].passed  # no test files present -> auto-pass


def test_automated_gates_skip_when_no_python_files(tmp_path: Path) -> None:
    results = run_automated_gates(tmp_path)
    assert len(results) == 1
    assert results[0].passed


def test_automated_defects_only_for_failed_gates() -> None:
    results = [
        VerificationResult("ruff", True, "ok"),
        VerificationResult("mypy", False, "type error on line 4"),
    ]
    defects = automated_defects(results)
    assert len(defects) == 1
    assert defects[0]["category"] == "CORRECTNESS"
    assert defects[0]["severity"] == "HIGH"
    assert "type error on line 4" in defects[0]["fix"]


def test_enforce_critic_schema_accepts_well_formed_critic() -> None:
    critic = {"defects": [], "verdict": "OK"}
    assert enforce_critic_schema(critic) == []


def test_enforce_critic_schema_rejects_inconsistent_verdict() -> None:
    critic = {
        "defects": [
            {"id": "C1", "category": "CORRECTNESS", "severity": "CRITICAL", "location": "x", "fix": "y"}
        ],
        "verdict": "OK",
    }
    errors = enforce_critic_schema(critic)
    assert any("verdict" in e for e in errors)


def test_enforce_critic_schema_rejects_non_dict() -> None:
    assert enforce_critic_schema("not a dict") != []


class _FakeProvider:
    name = "fake"

    def __init__(
        self, response_text: str, stop_reason: str | None = None, thinking_tokens: int = 0
    ) -> None:
        self._response_text = response_text
        self._stop_reason = stop_reason
        self._thinking_tokens = thinking_tokens

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        return GenerationResult(
            text=self._response_text,
            model=model,
            provider=self.name,
            input_tokens=1,
            output_tokens=1,
            stop_reason=self._stop_reason,
            thinking_tokens=self._thinking_tokens,
        )


def _gateway(response_text: str) -> LLMGateway:
    return LLMGateway(_FakeProvider(response_text))


def _budget() -> BudgetController:
    return BudgetController(max_tokens=100_000, planned_budget=Decimal("1.00"))


def _ok_critic_json() -> str:
    return json.dumps({"defects": [], "verdict": "OK"})


def test_parse_critic_accepts_valid_json() -> None:
    critic, errors = _parse_critic(_ok_critic_json())
    assert errors == []
    assert critic["verdict"] == "OK"


def test_parse_critic_rejects_non_json_text() -> None:
    critic, errors = _parse_critic("looks fine to me, no issues")
    assert critic == {}
    assert errors


def test_extract_json_objects_finds_each_balanced_span_separately() -> None:
    text = '{"a": 1} noise {"b": 2}'
    assert _extract_json_objects(text) == ['{"a": 1}', '{"b": 2}']


def test_parse_critic_takes_the_last_of_two_complete_json_objects() -> None:
    """Mirrors an observed production failure: the model drafts a defect,
    second-guesses itself mid-response ("Wait, let me reconsider more
    carefully"), and emits a second, corrected JSON object. The old greedy
    \\{.*\\} regex spanned first-brace-to-last-brace across both into one
    invalid blob; the fix must recover the model's final answer, not its
    discarded draft.
    """
    draft = json.dumps(
        {
            "defects": [
                {"id": "C1", "category": "CORRECTNESS", "severity": "HIGH", "location": "x", "fix": "y"}
            ],
            "verdict": "FAIL",
        }
    )
    final = _ok_critic_json()
    response_text = f"{draft}\n\nWait, let me reconsider more carefully:\n\n{final}"

    critic, errors = _parse_critic(response_text)

    assert errors == []
    assert critic == json.loads(final)
    assert critic["defects"] == []


def test_parse_critic_ignores_braces_inside_quoted_strings() -> None:
    """A "fix" value describing a literal dict in the reviewed code (e.g.
    {"name": "New User"}) must stay inside its own string span, not be
    mistaken for the start of a second top-level object.
    """
    response_text = json.dumps(
        {
            "defects": [
                {
                    "id": "C1",
                    "category": "CODE-QUALITY",
                    "severity": "MEDIUM",
                    "location": "solution.py:4",
                    "fix": 'extract {"name": "New User"} to a named constant',
                }
            ],
            "verdict": "OK",
        }
    )

    critic, errors = _parse_critic(response_text)

    assert errors == []
    assert critic["defects"][0]["fix"] == 'extract {"name": "New User"} to a named constant'


def test_parse_critic_rejects_truncated_json_with_unclosed_brace() -> None:
    truncated = '{"defects": [], "verdict": "OK"'  # missing closing brace

    critic, errors = _parse_critic(truncated)

    assert critic == {}
    assert errors == ["response did not contain a JSON object"]


def test_parse_critic_still_rejects_out_of_enum_category_unchanged_by_this_fix() -> None:
    """The parser fix only changes JSON *extraction* -- schema validation
    (enforce_critic_schema) is untouched. A well-formed JSON object with a
    category outside the fixed enum (observed in production: a security
    lens labeling a sort-order bug "LOGIC" instead of "SECURITY") must still
    fail closed exactly as before -- a separate, deliberately out-of-scope
    problem for this commit.
    """
    response_text = json.dumps(
        {
            "defects": [
                {"id": "C1", "category": "LOGIC", "severity": "LOW", "location": "x", "fix": "y"}
            ],
            "verdict": "OK",
        }
    )

    critic, errors = _parse_critic(response_text)

    assert critic == {}
    assert any("category" in e for e in errors)


def test_run_judge_gates_returns_one_critic_per_lens() -> None:
    critics, schema_errors = run_judge_gates(
        _gateway(_ok_critic_json()),
        _budget(),
        "claude-haiku-4-5-20251001",
        "do the thing",
        "print('hi')",
        run_id=1,
        task_id="task-1",
        conn=None,
    )
    assert schema_errors == []
    assert len(critics) == 3


def test_run_judge_gates_tags_each_defect_with_the_lens_that_produced_it() -> None:
    """Every lens call in this test gets the identical canned response (the
    fake provider ignores which lens/system prompt it was called with), and
    that response's defect always claims category "SECURITY" regardless of
    which lens is calling. If tagging fell back to trusting the model's own
    "category" field instead of the lens that actually made the call, every
    tagged defect here would incorrectly read "security" -- proving the tag
    must come from run_judge_gates' own loop variable, not from the parsed
    JSON.
    """
    response_text = json.dumps(
        {
            "defects": [
                {"id": "X1", "category": "SECURITY", "severity": "LOW", "location": "x", "fix": "y"}
            ],
            "verdict": "OK",
        }
    )
    critics, schema_errors = run_judge_gates(
        _gateway(response_text),
        _budget(),
        "claude-haiku-4-5-20251001",
        "do the thing",
        "print('hi')",
        run_id=1,
        task_id="task-1",
        conn=None,
    )
    assert schema_errors == []
    lenses_seen = {d["lens"] for critic in critics for d in critic["defects"]}
    assert lenses_seen == {"correctness", "security", "code-quality"}


class _SequencedFakeProvider:
    """Returns responses in call order rather than keying off the lens's
    system prompt text -- lets a test target exactly one lens via LENSES'
    stable dict iteration order (correctness, security, code-quality)
    without coupling to lens prompt wording.
    """

    name = "fake"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._calls = 0

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        text = self._responses[self._calls]
        self._calls += 1
        return GenerationResult(
            text=text, model=model, provider=self.name, input_tokens=1, output_tokens=1
        )


def test_run_judge_gates_invokes_on_schema_failure_only_for_the_failing_lens() -> None:
    responses = [_ok_critic_json(), "not json at all", _ok_critic_json()]
    gateway = LLMGateway(_SequencedFakeProvider(responses))
    captured: list[tuple[str, str, list[str]]] = []

    critics, schema_errors = run_judge_gates(
        gateway,
        _budget(),
        "claude-haiku-4-5-20251001",
        "do the thing",
        "print('hi')",
        run_id=1,
        task_id="task-1",
        conn=None,
        on_schema_failure=lambda lens, text, errs: captured.append((lens, text, errs)),
    )

    assert len(critics) == 2  # only the 2 well-formed lenses
    assert len(captured) == 1
    lens, raw_response, errors = captured[0]
    assert lens == "security"
    assert raw_response == "not json at all"
    assert errors
    assert any(e.startswith("judge:security:") for e in schema_errors)


def test_run_judge_gates_on_schema_failure_gets_empty_string_not_none_for_empty_response() -> None:
    responses = [_ok_critic_json(), _ok_critic_json(), ""]
    gateway = LLMGateway(_SequencedFakeProvider(responses))
    captured: list[tuple[str, str, list[str]]] = []

    run_judge_gates(
        gateway,
        _budget(),
        "claude-haiku-4-5-20251001",
        "do the thing",
        "print('hi')",
        run_id=1,
        task_id="task-1",
        conn=None,
        on_schema_failure=lambda lens, text, errs: captured.append((lens, text, errs)),
    )

    assert len(captured) == 1
    lens, raw_response, _errors = captured[0]
    assert lens == "code-quality"
    assert raw_response == ""
    assert raw_response is not None


def test_run_judge_gates_without_callback_behaves_exactly_as_before() -> None:
    """on_schema_failure defaults to None -- every existing caller (api.py,
    orchestrator/engine.py) omits it, so this proves the default path is
    unaffected: no crash, same return shape, schema failures still recorded
    in schema_errors (just not individually diagnosed).
    """
    responses = [_ok_critic_json(), "not json at all", _ok_critic_json()]
    gateway = LLMGateway(_SequencedFakeProvider(responses))

    critics, schema_errors = run_judge_gates(
        gateway,
        _budget(),
        "claude-haiku-4-5-20251001",
        "do the thing",
        "print('hi')",
        run_id=1,
        task_id="task-1",
        conn=None,
    )

    assert len(critics) == 2
    assert any(e.startswith("judge:security:") for e in schema_errors)


def test_pipeline_run_verification_forwards_on_schema_failure_unchanged(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        pipeline, "run_automated_gates", lambda workspace: [VerificationResult("ruff", True, "ok")]
    )
    monkeypatch.setattr(pipeline, "automated_defects", lambda results: [])
    received = {}

    def fake_run_judge_gates(gateway, budget, model, task, code, **kwargs):
        received["on_schema_failure"] = kwargs.get("on_schema_failure")
        return [], []

    monkeypatch.setattr(pipeline, "run_judge_gates", fake_run_judge_gates)

    def sentinel(lens: str, text: str, errors: list[str]) -> None:
        return None

    pipeline.run_verification(
        tmp_path,
        _gateway(""),
        _budget(),
        "fake-model",
        "task",
        run_id=1,
        task_id="task-1",
        conn=None,
        on_schema_failure=sentinel,
    )

    assert received["on_schema_failure"] is sentinel


def test_verdict_merge_fails_when_any_blocking_defect_present() -> None:
    critics = [
        {"defects": [], "verdict": "OK"},
        {
            "defects": [
                {"id": "S1", "category": "SECURITY", "severity": "CRITICAL", "location": "x", "fix": "y"}
            ],
            "verdict": "FAIL",
        },
    ]
    merged = verdict.merge(critics, [])
    assert merged["verdict"] == "FAIL"
    assert len(merged["defects"]) == 1


def test_verdict_gate_fails_closed_on_schema_errors() -> None:
    merged = {"defects": [], "verdict": "OK"}
    assert verdict.gate(merged, automated_passed=True, schema_errors=["bad json"]) == "UNVERIFIED"


def test_verdict_gate_fails_when_automated_gates_failed() -> None:
    merged = {"defects": [], "verdict": "OK"}
    assert verdict.gate(merged, automated_passed=False, schema_errors=[]) == "UNVERIFIED"


def test_verdict_gate_passes_when_everything_clean() -> None:
    merged = {"defects": [], "verdict": "OK"}
    assert verdict.gate(merged, automated_passed=True, schema_errors=[]) == "OK"


def test_pipeline_run_verification_fails_when_judges_report_blocking_defects(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        pipeline, "run_automated_gates", lambda workspace: [VerificationResult("ruff", True, "ok")]
    )
    monkeypatch.setattr(pipeline, "automated_defects", lambda results: [])
    monkeypatch.setattr(
        pipeline,
        "run_judge_gates",
        lambda gateway, budget, model, task, code, **kwargs: (
            [
                {"defects": [], "verdict": "OK"},
                {
                    "defects": [
                        {
                            "id": "C1",
                            "category": "CORRECTNESS",
                            "severity": "HIGH",
                            "location": "solution.py:1",
                            "fix": "fix the bug",
                        }
                    ],
                    "verdict": "FAIL",
                },
                {"defects": [], "verdict": "OK"},
            ],
            [],
        ),
    )

    status, merged, automated_results = pipeline.run_verification(
        tmp_path,
        _gateway(""),
        _budget(),
        "fake-model",
        "task",
        run_id=1,
        task_id="task-1",
        conn=None,
    )

    assert status == "UNVERIFIED"
    assert len(merged["defects"]) == 1
    assert len(automated_results) == 1


def test_build_retry_feedback_includes_defect_fix_text() -> None:
    merged = {
        "defects": [
            {
                "id": "C1",
                "category": "CORRECTNESS",
                "severity": "HIGH",
                "location": "solution.py:3",
                "fix": "handle the empty-string case",
            }
        ],
        "verdict": "FAIL",
    }
    feedback = pipeline.build_retry_feedback(merged)
    assert "handle the empty-string case" in feedback
    assert "solution.py:3" in feedback


def test_build_retry_feedback_empty_when_no_defects() -> None:
    assert pipeline.build_retry_feedback({"defects": [], "verdict": "OK"}) == ""


# --- DF-1: mypy empty-output / ambiguous "ok" sentinel and lost returncode ---
#
# `_run` used to derive `detail = (stdout + stderr).strip() or "ok"`, so a
# subprocess that exited non-zero without writing a single byte was recorded
# as `passed = 0, detail = "ok"` -- a sentinel that reads as success on a
# failed gate -- and `result.returncode` was discarded, leaving no way to
# attribute the failure to a cause. These tests drive `_run` with real
# subprocesses (no mocks, no network) so every branch is exercised as the
# gate actually runs it.


def _python(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_run_reports_normal_output_verbatim_on_success(tmp_path: Path) -> None:
    passed, detail = _run(_python("print('Success: no issues found in 1 source file')"), tmp_path)

    assert passed is True
    assert detail == "Success: no issues found in 1 source file"


def test_run_reports_normal_output_verbatim_on_failure(tmp_path: Path) -> None:
    passed, detail = _run(_python("print('x.py:4: error: bad type'); raise SystemExit(1)"), tmp_path)

    assert passed is False
    assert detail == "x.py:4: error: bad type"


def test_run_never_reports_ok_for_a_failed_gate_that_wrote_no_output(tmp_path: Path) -> None:
    """The DF-1 defect itself: exit 2 with empty stdout/stderr used to be
    recorded as detail == "ok" on a failed gate."""
    passed, detail = _run(_python("raise SystemExit(2)"), tmp_path)

    assert passed is False
    assert detail != "ok"
    assert detail == "(no output, exit 2)"


def test_run_preserves_the_exit_code_for_each_distinct_silent_failure(tmp_path: Path) -> None:
    """The exit status is the one value that distinguishes a crash, a kill and
    a mypy internal exit 2 from one another, so distinct codes must produce
    distinct details rather than one shared sentinel."""
    _, detail_two = _run(_python("raise SystemExit(2)"), tmp_path)
    _, detail_three = _run(_python("raise SystemExit(3)"), tmp_path)

    assert "2" in detail_two
    assert "3" in detail_three
    assert detail_two != detail_three


def test_run_reports_empty_output_explicitly_even_when_the_gate_passed(tmp_path: Path) -> None:
    passed, detail = _run(_python("pass"), tmp_path)

    assert passed is True
    assert detail != "ok"
    assert detail == "(no output, exit 0)"


def test_silent_failure_detail_reaches_the_defect_fix_text() -> None:
    """The gate's diagnostic must survive into the defect handed to the judge
    and the retry feedback, not just into the VerificationResult."""
    defects = automated_defects([VerificationResult("mypy", False, "(no output, exit 2)")])

    assert defects[0]["fix"] == "(no output, exit 2)"


def test_silent_failure_detail_round_trips_through_the_gate_record(tmp_path: Path) -> None:
    """eval_case_automated_gates has no returncode column; the exit status is
    persisted inside `detail`, so it must survive a write/read cycle intact."""
    with db.connect(tmp_path / "state.db") as conn:
        case_result_id = db.record_eval_case_result(
            conn,
            EvalCaseResult(
                eval_run_id=1,
                eval_case_id="quality-04-clean",
                task_id="t",
                expected_verdict="OK",
                actual_verdict="UNVERIFIED",
                expected_defect_category=None,
                detected_defect_categories=[],
                latency_ms=0,
                cost=Decimal(0),
                passed=False,
            ),
        )
        db.record_eval_case_automated_gates(
            conn, case_result_id, [VerificationResult("mypy", False, "(no output, exit 2)")]
        )
        stored = db.get_eval_case_automated_gates(conn, case_result_id)

    assert stored == [VerificationResult("mypy", False, "(no output, exit 2)")]


_PRICED_MODEL = "claude-haiku-4-5-20251001"

# --- Phase 9C.2 step 1: the observability metadata must be inert -------------
# These are the "cannot alter a verdict" proofs. Each one holds the response
# text fixed and varies ONLY the new metadata; any divergence means the
# observability commit leaked into the decision path.

_TRUNCATION_METADATA = [
    (None, 0),               # provider reported nothing (pre-change shape)
    ("end_turn", 0),         # completed, no thinking
    ("end_turn", 900),       # completed, thought a lot
    ("max_tokens", 1600),    # the exact 9C truncation signature
    ("refusal", 12),         # an unrelated terminal reason
]


def _verify_with(metadata, response_text: str, monkeypatch, tmp_path: Path):
    stop_reason, thinking_tokens = metadata
    monkeypatch.setattr(
        pipeline, "run_automated_gates", lambda workspace: [VerificationResult("ruff", True, "ok")]
    )
    return pipeline.run_verification(
        tmp_path,
        LLMGateway(_FakeProvider(response_text, stop_reason, thinking_tokens)),
        _budget(),
        _PRICED_MODEL,
        "task",
        run_id=1,
        task_id="task-1",
        conn=None,
    )


def test_verdict_is_identical_for_every_stop_reason_when_the_text_is_clean(
    monkeypatch, tmp_path: Path
) -> None:
    results = [
        _verify_with(m, _ok_critic_json(), monkeypatch, tmp_path) for m in _TRUNCATION_METADATA
    ]
    statuses = {r[0] for r in results}
    merged = {json.dumps(r[1], sort_keys=True) for r in results}

    assert statuses == {"OK"}, f"stop_reason/thinking metadata changed the status: {statuses}"
    assert len(merged) == 1, "stop_reason/thinking metadata changed the merged critic output"


def test_verdict_is_identical_for_every_stop_reason_when_the_text_is_blocking(
    monkeypatch, tmp_path: Path
) -> None:
    blocking = json.dumps(
        {
            "defects": [
                {
                    "id": "C1",
                    "category": "CORRECTNESS",
                    "severity": "HIGH",
                    "location": "solution.py:1",
                    "fix": "fix the bug",
                }
            ],
            "verdict": "FAIL",
        }
    )

    results = [_verify_with(m, blocking, monkeypatch, tmp_path) for m in _TRUNCATION_METADATA]
    statuses = {r[0] for r in results}
    defect_counts = {len(r[1]["defects"]) for r in results}

    assert statuses == {"UNVERIFIED"}, f"metadata changed the status: {statuses}"
    assert defect_counts == {3}, "metadata changed how many defects survived merge"


def test_verdict_is_identical_for_every_stop_reason_when_the_text_is_unparseable(
    monkeypatch, tmp_path: Path
) -> None:
    """A stop_reason of 'max_tokens' must not become a second, independent
    route to UNVERIFIED. The schema error alone decides -- exactly as before."""
    results = [
        _verify_with(m, "I think this looks fine", monkeypatch, tmp_path)
        for m in _TRUNCATION_METADATA
    ]
    statuses = {r[0] for r in results}
    errors = {len(r[1].get("schema_errors", [])) for r in results}

    assert statuses == {"UNVERIFIED"}
    assert errors == {3}, "metadata changed the schema-error count"


def test_run_judge_gates_output_does_not_depend_on_response_metadata() -> None:
    """Same proof one layer down, bypassing the pipeline entirely."""
    outputs = []
    for stop_reason, thinking_tokens in _TRUNCATION_METADATA:
        critics, schema_errors = run_judge_gates(
            LLMGateway(_FakeProvider(_ok_critic_json(), stop_reason, thinking_tokens)),
            _budget(),
            _PRICED_MODEL,
            "do the thing",
            "print('hi')",
            run_id=1,
            task_id="task-1",
            conn=None,
        )
        outputs.append(json.dumps([critics, schema_errors], sort_keys=True))

    assert len(set(outputs)) == 1


# --- Phase 9E: retry a judge lens only when it truncated in max_tokens ------
#
# Every test here holds the retry to one rule: it may only ever turn an
# unparseable lens into a parseable one. It must never fire on a lens that
# already produced a valid critic, and a retry that fails for any reason must
# land exactly where the run would have landed with no retry at all.

_TRUNCATED = "max_tokens"
_COMPLETE = "end_turn"


def _blocking_critic_json() -> str:
    return json.dumps(
        {
            "defects": [
                {
                    "id": "C1",
                    "category": "CORRECTNESS",
                    "severity": "HIGH",
                    "location": "solution.py:1",
                    "fix": "fix the bug",
                }
            ],
            "verdict": "FAIL",
        }
    )


class _SequencedProvider:
    """Returns queued (text, stop_reason) responses in order, then falls back
    to a clean OK critic. Records every call so a test can prove exactly how
    many were made and with what prompt."""

    name = "fake"

    def __init__(
        self, queued: list[tuple[str, str | None]], raises: Exception | None = None
    ) -> None:
        self._queued = list(queued)
        self._raises_after_queue = raises
        self.calls: list[tuple[str | None, int]] = []  # (system prompt, max_tokens)

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.calls.append((system, max_tokens))
        if self._queued:
            text, stop_reason = self._queued.pop(0)
        elif self._raises_after_queue is not None:
            # Fires exactly once -- the call right after the queue drains, i.e.
            # the retry. Later lenses must still be able to run normally, or
            # the test could not tell "the retry failed" apart from "every
            # remaining call failed".
            exc, self._raises_after_queue = self._raises_after_queue, None
            raise exc
        else:
            text, stop_reason = _ok_critic_json(), _COMPLETE
        return GenerationResult(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=1,
            output_tokens=1,
            stop_reason=stop_reason,
            thinking_tokens=0,
        )


def _run_lenses(provider: _SequencedProvider) -> tuple[list[dict], list[str]]:
    return run_judge_gates(
        LLMGateway(provider),
        _budget(),
        _PRICED_MODEL,
        "do the thing",
        "print('hi')",
        run_id=1,
        task_id="task-1",
        conn=None,
    )


def test_a_complete_valid_response_is_never_retried() -> None:
    provider = _SequencedProvider([])  # all three lenses: valid + end_turn
    critics, schema_errors = _run_lenses(provider)

    assert len(provider.calls) == 3, "a valid end_turn response must not be retried"
    assert schema_errors == []
    assert len(critics) == 3


def test_b_truncated_unparseable_response_triggers_exactly_one_retry() -> None:
    provider = _SequencedProvider([("half a json {", _TRUNCATED)])
    _run_lenses(provider)

    assert len(provider.calls) == 4  # 3 lenses + exactly 1 retry for the first


def test_c_successful_retry_critic_is_used() -> None:
    provider = _SequencedProvider(
        [("half a json {", _TRUNCATED), (_blocking_critic_json(), _COMPLETE)]
    )
    critics, schema_errors = _run_lenses(provider)

    assert schema_errors == [], "a rescued lens must not leave a schema error behind"
    assert len(critics) == 3
    assert critics[0]["defects"][0]["severity"] == "HIGH"
    assert critics[0]["defects"][0]["lens"] == "correctness", "retry keeps lens tagging"


def test_d_retry_that_truncates_again_fails_closed() -> None:
    provider = _SequencedProvider(
        [("half a json {", _TRUNCATED), ("still half a json {", _TRUNCATED)]
    )
    critics, schema_errors = _run_lenses(provider)

    assert len(provider.calls) == 4, "must not retry a second time"
    assert any(e.startswith("judge:correctness:") for e in schema_errors)
    assert len(critics) == 2, "the truncated lens contributes no critic"


def test_e_retry_returning_malformed_schema_fails_closed() -> None:
    malformed = json.dumps({"defects": [], "verdict": "MAYBE"})
    provider = _SequencedProvider([("half a json {", _TRUNCATED), (malformed, _COMPLETE)])
    critics, schema_errors = _run_lenses(provider)

    assert len(provider.calls) == 4
    assert any(e.startswith("judge:correctness:") for e in schema_errors)
    assert len(critics) == 2


def test_f_provider_error_on_the_retry_falls_back_to_fail_closed() -> None:
    """A retry is a bonus attempt. If it cannot be made at all, the run must
    land exactly where it would have landed without the retry -- never worse."""
    provider = _SequencedProvider([("half a json {", _TRUNCATED)], raises=RuntimeError("boom"))
    critics, schema_errors = _run_lenses(provider)

    assert any(e.startswith("judge:correctness:") for e in schema_errors)
    assert len(critics) == 2, "the other two lenses must still run"


def test_g_valid_blocking_response_is_never_retried_or_replaced() -> None:
    """Even when the provider reports max_tokens, a response that parses is
    final. Losing a HIGH defect to a retry is the failure this forbids."""
    provider = _SequencedProvider([(_blocking_critic_json(), _TRUNCATED)])
    critics, schema_errors = _run_lenses(provider)

    assert len(provider.calls) == 3, "a parseable critic must never be retried"
    assert schema_errors == []
    assert critics[0]["defects"][0]["severity"] == "HIGH"


def test_h_valid_ok_response_is_never_retried() -> None:
    provider = _SequencedProvider([(_ok_critic_json(), _TRUNCATED)])
    critics, schema_errors = _run_lenses(provider)

    assert len(provider.calls) == 3
    assert schema_errors == []
    assert critics[0]["defects"] == []


def test_i_retry_count_never_exceeds_one_per_lens() -> None:
    """All three lenses truncate, and so do all three retries."""
    provider = _SequencedProvider([("{", _TRUNCATED)] * 6)
    critics, schema_errors = _run_lenses(provider)

    assert len(provider.calls) == 6, "3 lenses x (1 initial + 1 retry), never more"
    assert critics == []
    assert len(schema_errors) == 3


def test_unparseable_response_that_completed_normally_is_not_retried() -> None:
    """The trigger is the provider's terminal state, not the parse failure.
    A model that simply answered in prose gets no second attempt."""
    provider = _SequencedProvider([("I think this looks fine", _COMPLETE)])
    _run_lenses(provider)

    assert len(provider.calls) == 3


def test_retry_reuses_the_same_prompt_and_cap_as_the_first_attempt() -> None:
    provider = _SequencedProvider([("half a json {", _TRUNCATED)])
    _run_lenses(provider)

    first, retry = provider.calls[0], provider.calls[1]
    assert first == retry, "retry must reuse the same system prompt and max_tokens"
    assert first[1] == 1600, "the cap must remain 1600"


# --- Phase 9G-prep: invariants the 9E suite left implicit --------------------
#
# Offline, zero-cost additions only. Each one pins an invariant that the Phase
# 9E tests establish indirectly (or not at all); none of them required a
# production change, and none of them relaxes an existing assertion.


class _RecordingGateway(LLMGateway):
    """Captures the full keyword set of every gateway call, so a retry can be
    compared field-by-field against the attempt it repeats. Records and
    delegates -- it changes no behavior, and the production Gateway is used
    unmodified underneath."""

    def __init__(self, provider: _SequencedProvider) -> None:
        super().__init__(provider)
        self.calls: list[dict] = []

    def generate(self, **kwargs: object) -> GenerationResult:
        self.calls.append(dict(kwargs))
        return super().generate(**kwargs)  # type: ignore[arg-type]


def _run_lenses_recording(
    gateway: _RecordingGateway, *, timeout_seconds: float | None = None
) -> tuple[list[dict], list[str]]:
    return run_judge_gates(
        gateway,
        _budget(),
        _PRICED_MODEL,
        "do the thing",
        "print('hi')",
        run_id=7,
        task_id="task-7",
        conn=None,
        timeout_seconds=timeout_seconds,
    )


def test_i_retry_repeats_every_call_argument_except_the_agent_label() -> None:
    """Invariant I. The 9E suite compared only (system, max_tokens) at the
    provider boundary. This compares the whole gateway keyword set, so a future
    edit that varied the model, the user prompt, the timeout or the run/task
    attribution on the second attempt would fail here."""
    gateway = _RecordingGateway(_SequencedProvider([("half a json {", _TRUNCATED)]))
    _run_lenses_recording(gateway, timeout_seconds=31.5)

    initial, retry = gateway.calls[0], gateway.calls[1]

    assert initial["agent_name"] == "judge:correctness"
    assert retry["agent_name"] == "judge:correctness:retry"

    differing = {k for k in initial if initial[k] != retry[k]}
    assert differing == {"agent_name"}, f"retry must differ only by its label, got {differing}"

    # Spelled out as well, so a failure names the field rather than a set diff.
    assert retry["model"] == initial["model"] == _PRICED_MODEL
    assert retry["messages"] == initial["messages"]
    assert retry["system"] == initial["system"]
    assert retry["max_tokens"] == initial["max_tokens"] == 1600
    assert retry["timeout_seconds"] == initial["timeout_seconds"] == 31.5
    assert (retry["run_id"], retry["task_id"]) == (initial["run_id"], initial["task_id"])
    assert retry["budget"] is initial["budget"]


def test_l_a_retry_is_never_itself_retried() -> None:
    """Invariant L. Every lens truncates, and so does every retry: the call
    labels must be exactly one initial and one retry per lens, in order, with
    no ':retry:retry' anywhere."""
    gateway = _RecordingGateway(_SequencedProvider([("{", _TRUNCATED)] * 6))
    critics, schema_errors = _run_lenses_recording(gateway)

    assert [c["agent_name"] for c in gateway.calls] == [
        "judge:correctness",
        "judge:correctness:retry",
        "judge:security",
        "judge:security:retry",
        "judge:code-quality",
        "judge:code-quality:retry",
    ]
    assert not any(str(c["agent_name"]).endswith(":retry:retry") for c in gateway.calls)
    assert critics == []
    assert len(schema_errors) == 3


def test_k_a_parsed_blocking_defect_is_kept_even_with_a_clean_response_queued() -> None:
    """Invariant K. The first lens returns a parseable HIGH *and* reports
    max_tokens, with a clean critic sitting next in the queue. If the retry
    ever fired on a parsed response, that clean critic would replace the HIGH.
    Three calls proves it never fired; the surviving HIGH proves nothing was
    discarded."""
    provider = _SequencedProvider(
        [(_blocking_critic_json(), _TRUNCATED), (_ok_critic_json(), _COMPLETE)]
    )
    critics, schema_errors = _run_lenses(provider)

    assert len(provider.calls) == 3, "a parsed critic must not be retried, truncated or not"
    assert schema_errors == []
    assert critics[0]["defects"][0]["severity"] == "HIGH"
    assert critics[0]["defects"][0]["lens"] == "correctness"


def _verify_with_sequence(
    queued: list[tuple[str, str | None]],
    monkeypatch,
    tmp_path: Path,
    raises: Exception | None = None,
) -> tuple[str, dict, list[VerificationResult]]:
    monkeypatch.setattr(
        pipeline, "run_automated_gates", lambda workspace: [VerificationResult("ruff", True, "ok")]
    )
    return pipeline.run_verification(
        tmp_path,
        LLMGateway(_SequencedProvider(queued, raises=raises)),
        _budget(),
        _PRICED_MODEL,
        "task",
        run_id=1,
        task_id="task-1",
        conn=None,
    )


def test_j_a_rescued_critic_changes_what_gate_sees_never_how_gate_decides(
    monkeypatch, tmp_path: Path
) -> None:
    """Invariant J. End to end through run_verification: a rescued critic is
    ordinary data reaching verdict.gate(), which applies its unchanged rule to
    it. A rescued HIGH still blocks; a rescued clean critic still passes."""
    blocking_status, blocking_merged, _ = _verify_with_sequence(
        [("half a json {", _TRUNCATED), (_blocking_critic_json(), _COMPLETE)], monkeypatch, tmp_path
    )
    assert blocking_status == "UNVERIFIED"
    assert "schema_errors" not in blocking_merged, "a rescued lens leaves no schema error"
    assert blocking_merged["defects"][0]["severity"] == "HIGH"

    clean_status, clean_merged, _ = _verify_with_sequence(
        [("half a json {", _TRUNCATED), (_ok_critic_json(), _COMPLETE)], monkeypatch, tmp_path
    )
    assert clean_status == "OK"
    assert clean_merged["defects"] == []

    # gate() is a pure function of its three arguments and is reached the same
    # way with or without a rescue.
    assert verdict.gate(blocking_merged, True, []) == "UNVERIFIED"
    assert verdict.gate(clean_merged, True, []) == "OK"


def test_h_a_retry_provider_error_never_becomes_a_case_level_error(
    monkeypatch, tmp_path: Path
) -> None:
    """Invariant H, completed. The 9E suite proved run_judge_gates survives a
    raising retry; this proves the exception never escapes run_verification
    either, so eval/runner.py records a normal UNVERIFIED case rather than an
    error row excluded from the accuracy denominator."""
    status, merged, _ = _verify_with_sequence(
        [("half a json {", _TRUNCATED)], monkeypatch, tmp_path, raises=RuntimeError("boom")
    )

    assert status == "UNVERIFIED"
    assert merged["schema_errors"], "the first attempt's schema errors must survive"
    assert all(e.startswith("judge:correctness:") for e in merged["schema_errors"])
