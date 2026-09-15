import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from engine.state.models import (
    AgentExecutionMetric,
    AgentExecutionRecord,
    EvalCaseLensResult,
    EvalCaseResult,
    EvalCaseSchemaFailure,
    EvalRun,
    RunRecord,
    VerificationResult,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_text TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS verification_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    attempt_number INTEGER NOT NULL,
    gate_name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS defects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    attempt_number INTEGER NOT NULL,
    defect_id TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    location TEXT NOT NULL,
    fix TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    attempt_number INTEGER NOT NULL,
    agent_name TEXT NOT NULL,
    agent_role TEXT NOT NULL,
    subtask_text TEXT NOT NULL,
    success INTEGER NOT NULL,
    produced_files TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_execution_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    task_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_creation_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    actual_spend TEXT,
    status TEXT NOT NULL,
    error TEXT,
    stop_reason TEXT,
    thinking_tokens INTEGER NOT NULL DEFAULT 0,
    text_chars INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    git_commit_sha TEXT NOT NULL,
    benchmark_name TEXT NOT NULL,
    benchmark_version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    total_cases INTEGER NOT NULL DEFAULT 0,
    correct_verdicts INTEGER NOT NULL DEFAULT 0,
    false_pass INTEGER NOT NULL DEFAULT 0,
    false_unverified INTEGER NOT NULL DEFAULT 0,
    category_accuracy TEXT NOT NULL DEFAULT '{}',
    average_cost TEXT NOT NULL DEFAULT '0',
    average_latency INTEGER NOT NULL DEFAULT 0,
    total_cost TEXT NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS eval_case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_run_id INTEGER NOT NULL REFERENCES eval_runs(id),
    eval_case_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    expected_verdict TEXT NOT NULL,
    actual_verdict TEXT NOT NULL,
    expected_defect_category TEXT,
    detected_defect_categories TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost TEXT NOT NULL,
    passed INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Phase 2.1: defect-level observability for eval runs. Populated only by
-- eval/runner.py (never by orchestrator/manager.py -- that's what `defects`
-- and `verification_results` above are for, keyed by run_id/attempt_number,
-- a shape that doesn't fit eval cases). See eval_case_id FK, not run_id.
CREATE TABLE IF NOT EXISTS eval_case_defects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_case_result_id INTEGER NOT NULL REFERENCES eval_case_results(id),
    lens TEXT NOT NULL,
    defect_id TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    location TEXT NOT NULL,
    fix TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eval_case_defects_result ON eval_case_defects(eval_case_result_id);

-- Adjudication sidecar. Purely additive: eval_case_defects above is never
-- written or altered by this, so the original judge defect and its original
-- severity survive byte-for-byte whatever the adjudicator concluded. One row
-- per adjudicated defect. admissible_to_block is NULL for a defect that was
-- never in scope (severity below blocking), 0/1 otherwise.
CREATE TABLE IF NOT EXISTS eval_case_defect_adjudications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_case_result_id INTEGER NOT NULL REFERENCES eval_case_results(id),
    lens TEXT NOT NULL,
    defect_id TEXT NOT NULL,
    original_severity TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    adjudication_json TEXT NOT NULL,
    admissible_to_block INTEGER,
    rule TEXT NOT NULL,
    reason TEXT NOT NULL,
    probe_predicate TEXT,
    probe_argument TEXT,
    probe_result TEXT,
    probe_interpreter_version TEXT,
    adjudicator_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eval_case_defect_adjudications_result
    ON eval_case_defect_adjudications(eval_case_result_id);

-- One row per canonical judge lens per eval case, always -- including
-- lenses that ran and found zero defects, so "found nothing" and "never
-- ran" are distinguishable. defect_count/schema_valid are NULL when
-- unknown rather than a fabricated 0 -- see EvalCaseLensResult's docstring.
CREATE TABLE IF NOT EXISTS eval_case_lens_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_case_result_id INTEGER NOT NULL REFERENCES eval_case_results(id),
    lens TEXT NOT NULL,
    call_status TEXT NOT NULL,
    defect_count INTEGER,
    schema_valid INTEGER,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eval_case_lens_results_result ON eval_case_lens_results(eval_case_result_id);

-- Per-gate (ruff/mypy/pytest) outcome per eval case. Expected to be all
-- passing rows for every case in the current dataset (every snippet is
-- ruff/mypy-clean by construction, and none carry test files -- see
-- eval/dataset.py's module docstring). A failing row here on a real
-- benchmark run means that dataset guarantee broke, not a judge problem.
CREATE TABLE IF NOT EXISTS eval_case_automated_gates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_case_result_id INTEGER NOT NULL REFERENCES eval_case_results(id),
    gate_name TEXT NOT NULL,
    passed INTEGER NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eval_case_automated_gates_result ON eval_case_automated_gates(eval_case_result_id);

-- Eval-only schema-failure diagnostics (Phase 2.1 follow-up): one row per
-- judge lens call whose response failed to parse/validate (schema_valid=0
-- in eval_case_lens_results above). Populated by eval/runner.py only --
-- never by gateway.py or the production engine run/engine serve paths.
-- Deliberately separate from eval_case_lens_results.error, which stays
-- reserved for transport/provider failures (call_status='error'); this
-- table only ever holds calls that succeeded but produced unparseable
-- content. raw_response is NOT NULL -- judge.py normalizes response.text
-- to "" before this is ever written, so an empty completion still gets a
-- row instead of being silently skipped.
CREATE TABLE IF NOT EXISTS eval_case_schema_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_case_result_id INTEGER NOT NULL REFERENCES eval_case_results(id),
    lens TEXT NOT NULL,
    error_detail TEXT NOT NULL,
    raw_response TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eval_case_schema_failures_result ON eval_case_schema_failures(eval_case_result_id);
"""


# Columns added to an already-created table after it shipped. SCHEMA above uses
# CREATE TABLE IF NOT EXISTS, which is a no-op on an existing database -- so a
# new column reaches a fresh .db and never reaches .engine/state.db, and the
# very next INSERT there fails. Each entry is (table, column, DDL type).
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("agent_execution_metrics", "stop_reason", "TEXT"),
    ("agent_execution_metrics", "thinking_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("agent_execution_metrics", "text_chars", "INTEGER NOT NULL DEFAULT 0"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any missing column from _ADDED_COLUMNS. Idempotent and additive --
    it never drops, renames, or rewrites a column, so rows written by an older
    version keep their values and simply carry the column default.
    """
    for table, column, ddl in _ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_run(conn: sqlite3.Connection, task_text: str, provider: str, model: str) -> int:
    cursor = conn.execute(
        "INSERT INTO runs (task_text, provider, model) VALUES (?, ?, ?)",
        (task_text, provider, model),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def record_verification(
    conn: sqlite3.Connection, run_id: int, attempt_number: int, results: list[VerificationResult]
) -> None:
    conn.executemany(
        "INSERT INTO verification_results (run_id, attempt_number, gate_name, passed, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        [(run_id, attempt_number, r.gate_name, int(r.passed), r.detail) for r in results],
    )


def record_defects(
    conn: sqlite3.Connection, run_id: int, attempt_number: int, defects: list[dict]
) -> None:
    conn.executemany(
        "INSERT INTO defects (run_id, attempt_number, defect_id, category, severity, location, fix) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                attempt_number,
                _sqlite_safe(d.get("id", "")),
                _sqlite_safe(d.get("category", "")),
                _sqlite_safe(d.get("severity", "")),
                _sqlite_safe(d.get("location", "")),
                _sqlite_safe(d.get("fix", "")),
            )
            for d in defects
        ],
    )


def record_agent_executions(
    conn: sqlite3.Connection, run_id: int, attempt_number: int, records: list[AgentExecutionRecord]
) -> None:
    conn.executemany(
        "INSERT INTO agent_executions "
        "(run_id, attempt_number, agent_name, agent_role, subtask_text, success, produced_files, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                attempt_number,
                r.agent_name,
                r.agent_role,
                r.subtask_text,
                int(r.success),
                json.dumps(r.produced_files),
                r.error,
            )
            for r in records
        ],
    )


def record_agent_execution_metric(conn: sqlite3.Connection, metric: AgentExecutionMetric) -> None:
    """Written by the Gateway after every LLM call -- success or failure.
    ``actual_spend`` is stored as TEXT (``str(Decimal)``), never as a
    numeric SQLite column, so it round-trips at full precision instead of
    passing through SQLite's float-based REAL storage class.
    """
    conn.execute(
        "INSERT INTO agent_execution_metrics "
        "(run_id, task_id, agent_name, model, input_tokens, output_tokens, "
        "cache_read_tokens, cache_creation_tokens, latency_ms, actual_spend, status, error, "
        "stop_reason, thinking_tokens, text_chars) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            metric.run_id,
            metric.task_id,
            metric.agent_name,
            metric.model,
            metric.input_tokens,
            metric.output_tokens,
            metric.cache_read_tokens,
            metric.cache_creation_tokens,
            metric.latency_ms,
            str(metric.actual_spend) if metric.actual_spend is not None else None,
            metric.status,
            metric.error,
            metric.stop_reason,
            metric.thinking_tokens,
            metric.text_chars,
        ),
    )


_METRIC_COLUMNS = (
    "run_id, task_id, agent_name, model, input_tokens, output_tokens, "
    "cache_read_tokens, cache_creation_tokens, latency_ms, actual_spend, status, error, "
    "stop_reason, thinking_tokens, text_chars"
)


def _row_to_metric(row: tuple) -> AgentExecutionMetric:
    return AgentExecutionMetric(
        run_id=row[0],
        task_id=row[1],
        agent_name=row[2],
        model=row[3],
        input_tokens=row[4],
        output_tokens=row[5],
        cache_read_tokens=row[6],
        cache_creation_tokens=row[7],
        latency_ms=row[8],
        actual_spend=Decimal(row[9]) if row[9] is not None else None,
        status=row[10],
        error=row[11],
        stop_reason=row[12],
        thinking_tokens=row[13],
        text_chars=row[14],
    )


def get_agent_execution_metrics(conn: sqlite3.Connection, run_id: int) -> list[AgentExecutionMetric]:
    rows = conn.execute(
        f"SELECT {_METRIC_COLUMNS} FROM agent_execution_metrics WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    return [_row_to_metric(row) for row in rows]


def get_agent_execution_metrics_by_task(
    conn: sqlite3.Connection, run_id: int, task_id: str
) -> list[AgentExecutionMetric]:
    """Exact (run_id, task_id) match -- never timestamps or insertion order.
    Used by eval/runner.py to find the metric rows a specific case produced.
    """
    rows = conn.execute(
        f"SELECT {_METRIC_COLUMNS} FROM agent_execution_metrics WHERE run_id = ? AND task_id = ? ORDER BY id",
        (run_id, task_id),
    ).fetchall()
    return [_row_to_metric(row) for row in rows]


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, attempts: int) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, attempts = ?, finished_at = datetime('now') WHERE id = ?",
        (status, attempts, run_id),
    )


def get_run(conn: sqlite3.Connection, run_id: int) -> RunRecord | None:
    row = conn.execute(
        "SELECT id, task_text, provider, model, status, attempts, created_at, finished_at "
        "FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return RunRecord(*row)


def create_eval_run(
    conn: sqlite3.Connection,
    git_commit_sha: str,
    benchmark_name: str,
    benchmark_version: str,
    dataset_version: str,
) -> int:
    """Creates the row with placeholder (zero) aggregate fields. The id is
    needed before any case runs (baked into every case's task_id), but the
    aggregates can only be computed once every case has finished --
    finish_eval_run() fills them in afterward.
    """
    cursor = conn.execute(
        "INSERT INTO eval_runs (git_commit_sha, benchmark_name, benchmark_version, dataset_version) "
        "VALUES (?, ?, ?, ?)",
        (git_commit_sha, benchmark_name, benchmark_version, dataset_version),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def finish_eval_run(
    conn: sqlite3.Connection,
    eval_run_id: int,
    *,
    total_cases: int,
    correct_verdicts: int,
    false_pass: int,
    false_unverified: int,
    category_accuracy: dict[str, float],
    average_cost: Decimal,
    average_latency: int,
    total_cost: Decimal,
) -> None:
    conn.execute(
        "UPDATE eval_runs SET total_cases = ?, correct_verdicts = ?, false_pass = ?, "
        "false_unverified = ?, category_accuracy = ?, average_cost = ?, average_latency = ?, "
        "total_cost = ? WHERE id = ?",
        (
            total_cases,
            correct_verdicts,
            false_pass,
            false_unverified,
            json.dumps(category_accuracy),
            str(average_cost),
            average_latency,
            str(total_cost),
            eval_run_id,
        ),
    )


def get_eval_run(conn: sqlite3.Connection, eval_run_id: int) -> EvalRun | None:
    row = conn.execute(
        "SELECT id, created_at, git_commit_sha, benchmark_name, benchmark_version, dataset_version, "
        "total_cases, correct_verdicts, false_pass, false_unverified, category_accuracy, "
        "average_cost, average_latency, total_cost FROM eval_runs WHERE id = ?",
        (eval_run_id,),
    ).fetchone()
    if row is None:
        return None
    return EvalRun(
        id=row[0],
        created_at=row[1],
        git_commit_sha=row[2],
        benchmark_name=row[3],
        benchmark_version=row[4],
        dataset_version=row[5],
        total_cases=row[6],
        correct_verdicts=row[7],
        false_pass=row[8],
        false_unverified=row[9],
        category_accuracy=json.loads(row[10]),
        average_cost=Decimal(row[11]),
        average_latency=row[12],
        total_cost=Decimal(row[13]),
    )


def record_eval_case_result(conn: sqlite3.Connection, result: EvalCaseResult) -> int:
    """Returns the new row's id -- Phase 2.1's eval_case_defects/
    eval_case_lens_results/eval_case_automated_gates all FK off of it, and
    that id doesn't exist until this INSERT runs.
    """
    cursor = conn.execute(
        "INSERT INTO eval_case_results "
        "(eval_run_id, eval_case_id, task_id, expected_verdict, actual_verdict, "
        "expected_defect_category, detected_defect_categories, latency_ms, cost, passed, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            result.eval_run_id,
            result.eval_case_id,
            result.task_id,
            result.expected_verdict,
            result.actual_verdict,
            result.expected_defect_category,
            json.dumps(result.detected_defect_categories),
            result.latency_ms,
            str(result.cost),
            int(result.passed),
            result.error,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def get_eval_case_results(conn: sqlite3.Connection, eval_run_id: int) -> list[EvalCaseResult]:
    rows = conn.execute(
        "SELECT eval_run_id, eval_case_id, task_id, expected_verdict, actual_verdict, "
        "expected_defect_category, detected_defect_categories, latency_ms, cost, passed, error "
        "FROM eval_case_results WHERE eval_run_id = ? ORDER BY id",
        (eval_run_id,),
    ).fetchall()
    return [
        EvalCaseResult(
            eval_run_id=row[0],
            eval_case_id=row[1],
            task_id=row[2],
            expected_verdict=row[3],
            actual_verdict=row[4],
            expected_defect_category=row[5],
            detected_defect_categories=json.loads(row[6]),
            latency_ms=row[7],
            cost=Decimal(row[8]),
            passed=bool(row[9]),
            error=row[10],
        )
        for row in rows
    ]


def _sqlite_safe(text: str) -> str:
    """Model-supplied text can carry an unpaired UTF-16 surrogate.

    ``json.loads`` accepts one -- a model escaping an emoji as a surrogate
    pair and running out of tokens mid-pair produces exactly this -- but
    sqlite3 must encode its parameters to UTF-8 and raises
    UnicodeEncodeError instead. Observed in production: one such defect
    string aborted a 40-case benchmark at case 36, discarding 35
    already-computed case results. Judge output is untrusted input to this
    layer, so a malformed character in it must cost that one string, never a
    run.

    Escapes only the code points that cannot be encoded and leaves every
    valid character -- astral planes included -- byte for byte, so the stored
    diagnostic stays readable and lossless for everything well formed.
    """
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def record_eval_case_defects(
    conn: sqlite3.Connection, eval_case_result_id: int, defects: list[dict]
) -> None:
    """``defects`` is merged["defects"] as produced by verification/pipeline.py
    -- judge-sourced entries carry a "lens" key (tagged in judge.py's
    run_judge_gates); script/automated-gate-sourced entries (from
    automated_defects()) don't, so they fall back to "automated" here.
    """
    conn.executemany(
        "INSERT INTO eval_case_defects "
        "(eval_case_result_id, lens, defect_id, category, severity, location, fix) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                eval_case_result_id,
                d.get("lens") or "automated",
                _sqlite_safe(d.get("id", "")),
                _sqlite_safe(d.get("category", "")),
                _sqlite_safe(d.get("severity", "")),
                _sqlite_safe(d.get("location", "")),
                _sqlite_safe(d.get("fix", "")),
            )
            for d in defects
        ],
    )


def _sqlite_safe_optional(value: object) -> str | None:
    return _sqlite_safe(value) if isinstance(value, str) else None


def record_defect_adjudications(
    conn: sqlite3.Connection, eval_case_result_id: int, records: list[dict]
) -> None:
    """``records`` is a list of ``admissibility.adjudication_record()`` dicts.

    Writes only to the sidecar table. ``eval_case_defects`` is left exactly as
    ``record_eval_case_defects`` wrote it, so the original defect text and the
    original severity survive whatever the adjudicator concluded -- an
    admissibility result is an additional fact about a defect, never a revision
    of it.
    """
    conn.executemany(
        "INSERT INTO eval_case_defect_adjudications "
        "(eval_case_result_id, lens, defect_id, original_severity, evidence_json, "
        "adjudication_json, admissible_to_block, rule, reason, probe_predicate, "
        "probe_argument, probe_result, probe_interpreter_version, adjudicator_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                eval_case_result_id,
                _sqlite_safe(str(r.get("lens", ""))),
                _sqlite_safe(str(r.get("defect_id", ""))),
                _sqlite_safe(str(r.get("original_severity", ""))),
                _sqlite_safe(str(r.get("evidence_json", ""))),
                _sqlite_safe(str(r.get("adjudication_json", ""))),
                None if r.get("admissible_to_block") is None else int(r["admissible_to_block"]),
                _sqlite_safe(str(r.get("rule", ""))),
                _sqlite_safe(str(r.get("reason", ""))),
                _sqlite_safe_optional(r.get("probe_predicate")),
                _sqlite_safe_optional(r.get("probe_argument")),
                _sqlite_safe_optional(r.get("probe_result")),
                _sqlite_safe_optional(r.get("probe_interpreter_version")),
                _sqlite_safe(str(r.get("adjudicator_version", ""))),
            )
            for r in records
        ],
    )


def get_eval_case_defects(conn: sqlite3.Connection, eval_case_result_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT lens, defect_id, category, severity, location, fix "
        "FROM eval_case_defects WHERE eval_case_result_id = ? ORDER BY id",
        (eval_case_result_id,),
    ).fetchall()
    return [
        {
            "lens": row[0],
            "id": row[1],
            "category": row[2],
            "severity": row[3],
            "location": row[4],
            "fix": row[5],
        }
        for row in rows
    ]


def record_eval_case_lens_results(
    conn: sqlite3.Connection, eval_case_result_id: int, lens_results: list[EvalCaseLensResult]
) -> None:
    conn.executemany(
        "INSERT INTO eval_case_lens_results "
        "(eval_case_result_id, lens, call_status, defect_count, schema_valid, error) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                eval_case_result_id,
                lr.lens,
                lr.call_status,
                lr.defect_count,
                None if lr.schema_valid is None else int(lr.schema_valid),
                lr.error,
            )
            for lr in lens_results
        ],
    )


def get_eval_case_lens_results(
    conn: sqlite3.Connection, eval_case_result_id: int
) -> list[EvalCaseLensResult]:
    rows = conn.execute(
        "SELECT lens, call_status, defect_count, schema_valid, error "
        "FROM eval_case_lens_results WHERE eval_case_result_id = ? ORDER BY id",
        (eval_case_result_id,),
    ).fetchall()
    return [
        EvalCaseLensResult(
            lens=row[0],
            call_status=row[1],
            defect_count=row[2],
            schema_valid=None if row[3] is None else bool(row[3]),
            error=row[4],
        )
        for row in rows
    ]


def record_eval_case_automated_gates(
    conn: sqlite3.Connection, eval_case_result_id: int, results: list[VerificationResult]
) -> None:
    conn.executemany(
        "INSERT INTO eval_case_automated_gates (eval_case_result_id, gate_name, passed, detail) "
        "VALUES (?, ?, ?, ?)",
        [(eval_case_result_id, r.gate_name, int(r.passed), r.detail) for r in results],
    )


def get_eval_case_automated_gates(
    conn: sqlite3.Connection, eval_case_result_id: int
) -> list[VerificationResult]:
    rows = conn.execute(
        "SELECT gate_name, passed, detail FROM eval_case_automated_gates "
        "WHERE eval_case_result_id = ? ORDER BY id",
        (eval_case_result_id,),
    ).fetchall()
    return [VerificationResult(gate_name=row[0], passed=bool(row[1]), detail=row[2]) for row in rows]


def record_eval_case_schema_failures(
    conn: sqlite3.Connection, eval_case_result_id: int, failures: list[EvalCaseSchemaFailure]
) -> None:
    """``raw_response`` is coerced with ``or ""`` as a last-mile guard --
    belt-and-suspenders alongside judge.py's own normalization -- so a
    None/empty response can never violate the NOT NULL column or cause the
    diagnostic row to be silently dropped.
    """
    conn.executemany(
        "INSERT INTO eval_case_schema_failures "
        "(eval_case_result_id, lens, error_detail, raw_response) "
        "VALUES (?, ?, ?, ?)",
        [
            (
                eval_case_result_id,
                f.lens,
                _sqlite_safe(f.error_detail or ""),
                _sqlite_safe(f.raw_response or ""),
            )
            for f in failures
        ],
    )


def get_eval_case_schema_failures(
    conn: sqlite3.Connection, eval_case_result_id: int
) -> list[EvalCaseSchemaFailure]:
    rows = conn.execute(
        "SELECT lens, error_detail, raw_response FROM eval_case_schema_failures "
        "WHERE eval_case_result_id = ? ORDER BY id",
        (eval_case_result_id,),
    ).fetchall()
    return [
        EvalCaseSchemaFailure(lens=row[0], error_detail=row[1], raw_response=row[2]) for row in rows
    ]
