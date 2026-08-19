from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass
class RunRecord:
    id: int
    task_text: str
    provider: str
    model: str
    status: str  # "running" | "passed" | "failed"
    attempts: int
    created_at: str
    finished_at: str | None


@dataclass
class VerificationResult:
    gate_name: str
    passed: bool
    detail: str


@dataclass
class AgentExecutionRecord:
    agent_name: str  # concrete class, e.g. "CodingAgent"
    agent_role: str  # registry key, e.g. "coding"
    subtask_text: str
    success: bool
    produced_files: list[str]
    error: str | None = None


@dataclass
class AttemptRecord:
    status: str  # "OK" | "UNVERIFIED" -- decided by verdict.gate, never by an LLM
    automated_results: list[VerificationResult]
    merged_critic: dict
    agent_executions: list[AgentExecutionRecord] = field(default_factory=list)


@dataclass
class AgentExecutionMetric:
    """One row per LLM call made through the Gateway -- an agent's call, or
    a single judge lens's call. Cost is always derived (see runtime/budget.py
    PRICE_TABLE), never accepted as a raw input.
    """

    run_id: int
    task_id: str
    agent_name: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    latency_ms: int
    actual_spend: Decimal | None  # None iff status == "error" before any usage was returned
    status: str  # "ok" | "error"
    error: str | None = None
    # Phase 9C.2 observability. Purely descriptive: nothing reads these back to
    # make a decision, and no verdict path consults them (see the inertness
    # tests in tests/test_verification.py). stop_reason is NULL when the
    # provider did not report one. text_chars is the length of the visible
    # response, which separates "produced no answer" from "produced a short
    # one" -- both look identical in output_tokens once thinking is included.
    stop_reason: str | None = None
    thinking_tokens: int = 0
    text_chars: int = 0


@dataclass
class RunResult:
    run_id: int
    task_text: str
    workspace: Path
    passed: bool
    attempts: int
    verification_history: list[AttemptRecord] = field(default_factory=list)


@dataclass
class EvalRun:
    """One row per `engine bench` invocation. Created with placeholder (zero)
    aggregate fields before any case runs -- the id is baked into every
    case's task_id for agent_execution_metrics attribution, but the
    aggregates can only be computed once every case has finished.
    """

    id: int
    created_at: str
    git_commit_sha: str
    benchmark_name: str
    benchmark_version: str
    dataset_version: str
    total_cases: int
    correct_verdicts: int
    false_pass: int
    false_unverified: int
    category_accuracy: dict[str, float]
    average_cost: Decimal
    average_latency: int
    total_cost: Decimal


@dataclass
class EvalCaseLensResult:
    """One row per judge lens per eval case -- proof a lens ran and found
    nothing is different from a lens that never got called (Phase 2.1:
    without this, an empty result and a missing result look identical).

    ``defect_count``/``schema_valid`` are None when unknown rather than a
    fabricated 0/False: this happens when the lens's own call succeeded
    (status == "ok" in agent_execution_metrics) but a LATER lens's
    exception aborted run_judge_gates before merge() ever ran, discarding
    the already-parsed critic. See the limitation documented in
    verification/judge.py's run_judge_gates for why that data can't be
    recovered without changing judge.py's per-lens fault isolation, which
    is out of scope for Phase 2.1.
    """

    lens: str  # "correctness" | "security" | "code-quality"
    call_status: str  # "ok" | "error" | "not_run"
    defect_count: int | None
    schema_valid: bool | None
    error: str | None = None


@dataclass
class EvalCaseSchemaFailure:
    """One row per judge lens call whose response failed to parse/validate
    (schema_valid=False on EvalCaseLensResult) -- eval-only diagnostics
    (Phase 2.1 follow-up), populated by eval/runner.py alone. Deliberately
    separate from EvalCaseLensResult.error, which is reserved for transport/
    provider failures (call_status="error"); this table only ever exists for
    calls that succeeded but produced unparseable content.

    ``raw_response`` is never None: judge.py normalizes response.text (typed
    str, but defended anyway) to "" before invoking the diagnostics hook, so
    an empty completion still produces a row instead of being skipped.
    """

    lens: str  # "correctness" | "security" | "code-quality"
    error_detail: str  # _parse_critic's error message(s), newline-joined
    raw_response: str


@dataclass
class EvalCaseResult:
    """One row per evaluated case. ``task_id`` is the exact value passed to
    run_verification() for this case, so agent_execution_metrics rows for
    it are found by an explicit (run_id, task_id) match -- never inferred
    from timestamps or insertion order. ``cost``/``latency_ms`` are the SUM
    of whatever metric rows exist for that task_id -- if ``error`` is set,
    that sum may reflect only the lenses that completed before the failure,
    not a full 3-lens measurement.

    ``defects``/``lens_results``/``automated_gate_results``/``schema_failures``
    (Phase 2.1) are NOT columns of eval_case_results itself -- they're
    carried on this dataclass purely so run_benchmark() can hand them to the
    eval_case_defects/eval_case_lens_results/eval_case_automated_gates/
    eval_case_schema_failures writers once record_eval_case_result() has
    produced the FK id. Reading a row back via get_eval_case_results() always
    yields these as empty lists; use the dedicated getters for the child
    tables instead.
    """

    eval_run_id: int
    eval_case_id: str
    task_id: str
    expected_verdict: str  # "OK" | "UNVERIFIED"
    actual_verdict: str
    expected_defect_category: str | None
    detected_defect_categories: list[str]
    latency_ms: int
    cost: Decimal
    passed: bool
    error: str | None = None  # set iff run_verification() raised for this case
    defects: list[dict] = field(default_factory=list)
    lens_results: list[EvalCaseLensResult] = field(default_factory=list)
    automated_gate_results: list[VerificationResult] = field(default_factory=list)
    schema_failures: list[EvalCaseSchemaFailure] = field(default_factory=list)
