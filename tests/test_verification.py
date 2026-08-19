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
        self.efforts: list[str | None] = []

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
        effort: str | None = None,
    ) -> GenerationResult:
        self.efforts.append(effort)
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
        effort: str | None = None,
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


# --- Phase 9C.2 step 2: judge-only reasoning control ------------------------


def test_every_judge_lens_call_requests_medium_effort() -> None:
    """Sonnet 5 defaults to effort=high with adaptive thinking, which is what
    consumed the whole 1600-token budget on the Phase 9C truncations."""
    provider = _FakeProvider(_ok_critic_json())

    run_judge_gates(
        LLMGateway(provider),
        _budget(),
        _PRICED_MODEL,
        "do the thing",
        "print('hi')",
        run_id=1,
        task_id="task-1",
        conn=None,
    )

    assert provider.efforts == ["medium", "medium", "medium"]
