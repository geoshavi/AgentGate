"""Admissibility gate: suppression targets, preservation controls, and the
fail-closed ordering the design turns on.

The gate may only ever REMOVE blocking authority from a defect that is already
CRITICAL/HIGH, and only on a deterministic contradiction. It never reads or
writes severity beyond deciding whether a defect is in scope at all, and it
never removes a finding from the report or from retry feedback.
"""

import json
import shutil
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from engine.providers.base import GenerationResult, Message
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state import db
from engine.state.models import EvalCaseResult, VerificationResult
from engine.verification import admissibility, pipeline, verdict
from engine.verification.adjudication import ADJUDICATOR_VERSION

EDGE_02_TASK = (
    "Implement get_user_email(user) -> str | None that safely reads "
    "user['profile']['email'], returning None if any part of that path is missing, "
    "without raising."
)
EDGE_02_CLEAN = (
    "def get_user_email(user: dict) -> str | None:\n"
    '    profile = user.get("profile")\n'
    "    if not isinstance(profile, dict):\n"
    "        return None\n"
    '    email = profile.get("email")\n'
    "    return email if isinstance(email, str) else None\n"
)
EDGE_02_BROKEN = (
    "def get_user_email(user: dict) -> str | None:\n"
    '    return user["profile"]["email"]\n'
)

SEC_04_TASK = (
    "Implement resolve_safe_fetch_target(host) -> str | None used to guard a URL-preview "
    "feature against fetching internal/private network addresses (SSRF). Return the network "
    "address the fetch must connect to, or None when the host has no safe address. The "
    "caller connects to the address you return and does not look the host up again, so the "
    "address you return must be one you checked."
)
SEC_04_CLEAN = (
    "import ipaddress\n"
    "import socket\n"
    "\n"
    "\n"
    "def _is_public(addr: str) -> bool:\n"
    "    ip = ipaddress.ip_address(addr)\n"
    "    return not (ip.is_private or ip.is_loopback)\n"
    "\n"
    "\n"
    "def resolve_safe_fetch_target(host: str) -> str | None:\n"
    "    infos = socket.getaddrinfo(host, None)\n"
    "    addresses = [str(info[4][0]) for info in infos]\n"
    "    if not all(_is_public(addr) for addr in addresses):\n"
    "        return None\n"
    "    return addresses[0]\n"
)
SEC_04_BROKEN = (
    "import socket\n"
    "\n"
    "\n"
    "def resolve_safe_fetch_target(host: str) -> str | None:\n"
    "    return socket.gethostbyname(host)\n"
)

SEC_03_TASK = (
    "Implement make_reset_token() -> str that returns an unguessable single-use token "
    "for a password-reset link."
)
SEC_03_BROKEN = "import random\n\n\ndef make_reset_token() -> str:\n    return str(random.random())\n"


def _defect(**overrides: object) -> dict:
    base: dict = {
        "id": "C1",
        "category": "CORRECTNESS",
        "severity": "HIGH",
        "location": "solution.py:1",
        "fix": "change something",
    }
    base.update(overrides)
    return base


def _decide(defect: dict, task: str, code: str) -> admissibility.Decision:
    return admissibility.decide(defect, task, code)


# ==========================================================================
# SUPPRESSION TARGETS
# ==========================================================================


def test_1_edge_case_02_clean_out_of_contract_user_none_blocker_is_inadmissible() -> None:
    defect = _defect(
        severity="HIGH",
        location="get_user_email",
        fix="user=None raises AttributeError on user.get",
        minimal_trigger="user=None",
    )

    decision = _decide(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert decision.admissible is False
    assert decision.rule == "declared-interface"


def test_2_edge_case_02_clean_return_type_contradiction_is_inadmissible() -> None:
    defect = _defect(
        severity="HIGH",
        fix="returns None when email is not a str, instead of the email",
        minimal_trigger="return=None",
    )

    decision = _decide(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert decision.admissible is False
    assert decision.rule == "factual-premise"


def test_3_security_04_clean_caller_guarantee_blocker_is_inadmissible() -> None:
    defect = _defect(
        category="SECURITY",
        severity="HIGH",
        fix="DNS rebinding between the check and the caller's connect is not prevented",
        excluded_by_clause="The caller connects to the address you return and does not look "
        "the host up again",
    )

    decision = _decide(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert decision.admissible is False
    assert decision.rule == "explicit-guarantee"


def test_3b_caller_guarantee_only_paraphrased_stays_admissible() -> None:
    defect = _defect(
        category="SECURITY",
        severity="HIGH",
        fix="DNS rebinding is not prevented",
        excluded_by_clause="the caller does not re-resolve",  # not verbatim
    )

    decision = _decide(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert decision.admissible is True


def test_4_mapped_address_premise_suppressed_only_when_probe_refutes_it() -> None:
    defect = _defect(
        category="SECURITY",
        severity="HIGH",
        fix="::ffff:127.0.0.1 is not caught by the loopback check",
        runtime_probe={
            "predicate": "ipaddress.is_loopback",
            "argument": "::ffff:127.0.0.1",
            "claim": False,
        },
    )

    decision = _decide(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert decision.admissible is False
    assert decision.rule == "factual-premise"


@pytest.mark.parametrize(
    "probe",
    [
        {"predicate": "os.system", "argument": "x", "claim": False},  # unknown
        {"predicate": "ipaddress.is_loopback", "argument": "nonsense", "claim": False},  # errors
        {"predicate": "ipaddress.is_loopback", "argument": "::ffff:127.0.0.1"},  # no claim
    ],
)
def test_4b_unavailable_or_failing_probe_leaves_defect_admissible(probe: dict) -> None:
    defect = _defect(category="SECURITY", severity="HIGH", runtime_probe=probe)

    decision = _decide(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert decision.admissible is True
    assert decision.rule == "fail-closed-unresolved"


def test_4c_defect_with_no_probe_at_all_stays_admissible() -> None:
    defect = _defect(
        category="SECURITY",
        severity="HIGH",
        fix="mapped addresses may not be caught depending on Python version",
    )

    decision = _decide(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert decision.admissible is True


# ==========================================================================
# PRESERVATION CONTROLS
# ==========================================================================


def test_5_edge_case_02_broken_missing_path_blocker_survives_non_dict_prose() -> None:
    defect = _defect(
        severity="CRITICAL",
        location="solution.py:2",
        fix=(
            "user['profile']['email'] raises KeyError when 'profile' is missing; also note "
            "the function would fail on a non-dict user"
        ),
        minimal_trigger="user={}",
    )

    decision = _decide(defect, EDGE_02_TASK, EDGE_02_BROKEN)

    assert decision.admissible is True


def test_5b_edge_case_02_broken_blocker_with_no_evidence_survives() -> None:
    defect = _defect(severity="CRITICAL", location="solution.py:2", fix="raises KeyError")

    decision = _decide(defect, EDGE_02_TASK, EDGE_02_BROKEN)

    assert decision.admissible is True
    assert decision.rule == "fail-closed-unresolved"


def test_6_security_03_broken_stated_purpose_sole_blocker_survives() -> None:
    defect = _defect(
        category="SECURITY",
        severity="CRITICAL",
        fix="random.random() is predictable; use secrets.token_urlsafe",
        grounding_route="stated_purpose",
        grounded_in_clause="an unguessable single-use token",
    )

    decision = _decide(defect, SEC_03_TASK, SEC_03_BROKEN)

    assert decision.admissible is True


def test_6b_stated_purpose_route_can_never_reach_an_inadmissible_branch() -> None:
    # Even carrying a verbatim clause, a stated_purpose finding is never suppressed.
    defect = _defect(
        category="SECURITY",
        severity="CRITICAL",
        grounding_route="stated_purpose",
        grounded_in_clause="an unguessable single-use token",
        excluded_by_clause="an unguessable single-use token",
    )

    decision = _decide(defect, SEC_03_TASK, SEC_03_BROKEN)

    assert decision.admissible is True


def test_7_security_04_broken_no_validation_blocker_survives() -> None:
    defect = _defect(
        category="SECURITY",
        severity="HIGH",
        location="resolve_safe_fetch_target",
        fix="no validation of the resolved address; never returns None for unsafe hosts",
        minimal_trigger="host='localhost'",
        grounded_in_clause="Return the network address the fetch must connect to, or None "
        "when the host has no safe address",
    )

    decision = _decide(defect, SEC_04_TASK, SEC_04_BROKEN)

    assert decision.admissible is True


def test_8_cgnat_and_fec0_findings_remain_visible_at_original_severity() -> None:
    defects = [
        _defect(
            id="C4",
            category="SECURITY",
            severity="LOW",
            fix="100.64.0.0/10 (CGNAT) is not rejected by _is_public",
        ),
        _defect(
            id="C5",
            category="SECURITY",
            severity="LOW",
            fix="fec0::/10 (site-local) is not rejected by _is_public",
        ),
    ]
    merged = {"defects": defects, "verdict": "OK"}

    annotated = admissibility.annotate(merged, SEC_04_TASK, SEC_04_CLEAN)

    assert len(annotated["defects"]) == 2
    assert [d["severity"] for d in annotated["defects"]] == ["LOW", "LOW"]
    # not blocking, so never evaluated -- and certainly never removed
    assert all(d["admissible_to_block"] is None for d in annotated["defects"])


def test_9_quality_04_broken_shape_is_unchanged_by_the_gate() -> None:
    # MEDIUM/MEDIUM/LOW -- zero blocking defects. The gate must not touch it.
    merged = {
        "defects": [
            _defect(id="C1", severity="MEDIUM", fix="Define a named constant for 100"),
            _defect(id="C2", category="CODE-QUALITY", severity="MEDIUM", fix="duplicate literal"),
            _defect(id="C3", category="CODE-QUALITY", severity="LOW", fix="naming"),
        ],
        "verdict": "OK",
    }
    before = json.dumps(merged, sort_keys=True)

    annotated = admissibility.annotate(merged, "task", "code")

    assert verdict.gate(annotated, True, []) == verdict.gate(merged, True, [])
    # the original dict is untouched; annotation is a copy
    assert json.dumps(merged, sort_keys=True) == before
    assert all(d["admissible_to_block"] is None for d in annotated["defects"])


# Real dataset fixtures for the two razor-margin safety controls: each rests
# on exactly one blocking defect in every Phase 0 control run (BASELINE.md,
# Registration B's sole-blocker census). Verbatim from dataset.py, not the
# generic "task"/"code" placeholders test_9 uses above.
QUALITY_04_TASK = (
    "Implement classify_order(total, is_member, has_coupon, in_stock) -> str. Return "
    "'rejected' when not in_stock. Otherwise an order is high-value when total is "
    "strictly greater than 100, and the tier is: members with a coupon get "
    "'vip_discount' when high-value and 'member_coupon_discount' otherwise; members "
    "without a coupon get 'member_discount' when high-value and 'member_standard' "
    "otherwise; non-members get 'coupon_discount' with a coupon and 'standard' "
    "without. Define the high-value threshold once as a single named constant."
)
QUALITY_04_BROKEN = (
    "def classify_order(total: float, is_member: bool, has_coupon: bool, in_stock: bool) -> str:\n"
    "    if in_stock:\n"
    "        if is_member:\n"
    "            if has_coupon:\n"
    "                if total > 100:\n"
    '                    return "vip_discount"\n'
    "                else:\n"
    '                    return "member_coupon_discount"\n'
    "            else:\n"
    "                if total > 100:\n"
    '                    return "member_discount"\n'
    "                else:\n"
    '                    return "member_standard"\n'
    "        else:\n"
    "            if has_coupon:\n"
    '                return "coupon_discount"\n'
    "            else:\n"
    '                return "standard"\n'
    "    else:\n"
    '        return "rejected"\n'
)


def test_9b_quality_04_broken_real_phase0_high_shape_stays_blocking() -> None:
    """Closes the gap the AgentGate forensic-analysis turn flagged: test_9 above only
    proves the gate leaves an already-non-blocking (MEDIUM/MEDIUM/LOW) shape alone. This
    test uses the actual Phase 0 control-arm shape instead -- a HIGH code-quality finding
    on the missing named constant, with zero evidence fields, exactly as
    eval_case_defects records it in runs 58-61 (BASELINE.md) and as the control prompt
    (which requests no evidence) always produces. It goes through the real decision path
    (admissibility.decide() and admissibility.annotate() + verdict.gate()), not the
    miner -- tests/test_evidence_mining.py separately proves the miner mines nothing for
    this exact shape; this test is the independent guarantee on the downstream decision
    path a real run actually exercises."""
    defect = _defect(
        id="C1",
        category="CODE-QUALITY",
        severity="HIGH",
        location="solution.py: total > 100 (used twice)",
        fix=(
            "Define a module-level constant, e.g. HIGH_VALUE_THRESHOLD = 100, and replace "
            "both literal comparisons 'total > 100' with 'total > HIGH_VALUE_THRESHOLD' as "
            "explicitly requested by the task."
        ),
    )
    assert "minimal_trigger" not in defect
    assert "excluded_by_clause" not in defect
    assert "grounding_route" not in defect

    decision = _decide(defect, QUALITY_04_TASK, QUALITY_04_BROKEN)

    assert decision.admissible is True
    assert decision.rule == "fail-closed-unresolved"

    merged = {"defects": [defect], "verdict": "FAIL"}
    annotated = admissibility.annotate(merged, QUALITY_04_TASK, QUALITY_04_BROKEN)

    assert annotated["defects"][0]["admissible_to_block"] is True
    assert verdict.gate(annotated, True, []) == "UNVERIFIED"


def test_6c_security_03_broken_sole_high_with_no_evidence_stays_blocking() -> None:
    """Mirrors test_9b's rigor for the other razor-margin case: real control-prompt
    shape (no evidence fields at all), run through the actual decision path rather than
    a hand-supplied grounding_route as test_6/test_6b do."""
    defect = _defect(
        category="SECURITY",
        severity="HIGH",
        location="solution.py: generate_reset_token",
        fix=(
            "random.choice over a fixed alphabet is not cryptographically secure; use "
            "secrets.token_hex instead."
        ),
    )
    assert "minimal_trigger" not in defect
    assert "grounding_route" not in defect

    decision = _decide(defect, SEC_03_TASK, SEC_03_BROKEN)

    assert decision.admissible is True
    assert decision.rule == "fail-closed-unresolved"

    merged = {"defects": [defect], "verdict": "FAIL"}
    annotated = admissibility.annotate(merged, SEC_03_TASK, SEC_03_BROKEN)

    assert annotated["defects"][0]["admissible_to_block"] is True
    assert verdict.gate(annotated, True, []) == "UNVERIFIED"


# ==========================================================================
# SEVERITY IS NEVER TOUCHED
# ==========================================================================


def test_annotation_never_changes_any_severity() -> None:
    merged = {
        "defects": [
            _defect(id="C1", severity="HIGH", minimal_trigger="user=None"),
            _defect(id="C2", severity="CRITICAL"),
            _defect(id="C3", severity="MEDIUM"),
            _defect(id="C4", severity="LOW"),
        ],
        "verdict": "FAIL",
    }

    annotated = admissibility.annotate(merged, EDGE_02_TASK, EDGE_02_CLEAN)

    assert [d["severity"] for d in annotated["defects"]] == ["HIGH", "CRITICAL", "MEDIUM", "LOW"]


def test_only_blocking_severities_are_evaluated() -> None:
    merged = {
        "defects": [_defect(id="C1", severity="MEDIUM", minimal_trigger="user=None")],
        "verdict": "OK",
    }

    annotated = admissibility.annotate(merged, EDGE_02_TASK, EDGE_02_CLEAN)

    # a MEDIUM defect with a contradicted trigger is still not evaluated
    assert annotated["defects"][0]["admissible_to_block"] is None


# ==========================================================================
# GATE ORDERING / FAIL-CLOSED DOMINANCE
# ==========================================================================


def test_10_missing_severity_is_a_schema_error_and_stays_unverified() -> None:
    from engine.verification.schema import enforce_critic_schema

    critic = {
        "defects": [
            {"id": "C1", "category": "CORRECTNESS", "location": "x", "fix": "y"}
        ],
        "verdict": "OK",
    }
    errors = enforce_critic_schema(critic)

    assert any("severity" in e for e in errors)
    assert verdict.gate({"defects": []}, True, errors) == "UNVERIFIED"


def test_11_schema_error_dominates_even_when_every_defect_is_inadmissible() -> None:
    merged = admissibility.annotate(
        {"defects": [_defect(severity="HIGH", minimal_trigger="user=None")], "verdict": "FAIL"},
        EDGE_02_TASK,
        EDGE_02_CLEAN,
    )

    assert merged["defects"][0]["admissible_to_block"] is False
    assert verdict.gate(merged, True, ["judge:correctness: bad json"]) == "UNVERIFIED"


def test_12_automated_gate_failure_dominates_even_when_defects_are_inadmissible() -> None:
    merged = admissibility.annotate(
        {"defects": [_defect(severity="HIGH", minimal_trigger="user=None")], "verdict": "FAIL"},
        EDGE_02_TASK,
        EDGE_02_CLEAN,
    )

    assert verdict.gate(merged, False, []) == "UNVERIFIED"


def test_inadmissible_blocking_defect_alone_yields_ok() -> None:
    merged = admissibility.annotate(
        {"defects": [_defect(severity="HIGH", minimal_trigger="user=None")], "verdict": "FAIL"},
        EDGE_02_TASK,
        EDGE_02_CLEAN,
    )

    assert verdict.gate(merged, True, []) == "OK"


def test_one_admissible_blocker_among_inadmissible_ones_still_blocks() -> None:
    merged = admissibility.annotate(
        {
            "defects": [
                _defect(id="C1", severity="HIGH", minimal_trigger="user=None"),
                _defect(id="C2", severity="HIGH", fix="genuine KeyError"),
            ],
            "verdict": "FAIL",
        },
        EDGE_02_TASK,
        EDGE_02_CLEAN,
    )

    assert verdict.gate(merged, True, []) == "UNVERIFIED"


# ==========================================================================
# REPORTING / RETRY VISIBILITY
# ==========================================================================


def test_13_retry_feedback_still_lists_inadmissible_defects() -> None:
    merged = admissibility.annotate(
        {
            "defects": [
                _defect(
                    id="C1",
                    severity="HIGH",
                    location="get_user_email",
                    fix="user=None raises AttributeError",
                    minimal_trigger="user=None",
                )
            ],
            "verdict": "FAIL",
        },
        EDGE_02_TASK,
        EDGE_02_CLEAN,
    )

    feedback = pipeline.build_retry_feedback(merged)

    assert "user=None raises AttributeError" in feedback
    assert "get_user_email" in feedback


def test_13b_retry_feedback_is_byte_identical_with_and_without_annotation() -> None:
    merged = {
        "defects": [
            _defect(id="C1", severity="HIGH", fix="a fix", minimal_trigger="user=None")
        ],
        "verdict": "FAIL",
    }

    assert pipeline.build_retry_feedback(
        admissibility.annotate(merged, EDGE_02_TASK, EDGE_02_CLEAN)
    ) == pipeline.build_retry_feedback(merged)


# ==========================================================================
# DEFAULT-OFF / NO-ANNOTATION EQUIVALENCE
# ==========================================================================


def test_14_has_blocking_defaults_to_true_when_annotation_absent() -> None:
    merged = {"defects": [_defect(severity="HIGH")], "verdict": "FAIL"}

    assert verdict._has_blocking(merged) is True
    assert verdict.gate(merged, True, []) == "UNVERIFIED"


def test_14b_has_blocking_unchanged_across_every_severity_without_annotation() -> None:
    for severity, expected in (
        ("CRITICAL", True),
        ("HIGH", True),
        ("MEDIUM", False),
        ("LOW", False),
    ):
        merged = {"defects": [_defect(severity=severity)], "verdict": "FAIL"}
        assert verdict._has_blocking(merged) is expected


def test_14c_explicit_true_annotation_behaves_like_no_annotation() -> None:
    a = {"defects": [_defect(severity="HIGH")]}
    b = {"defects": [_defect(severity="HIGH", admissible_to_block=True)]}

    assert verdict._has_blocking(a) == verdict._has_blocking(b)


def test_14d_not_applicable_annotation_never_grants_blocking_to_a_medium() -> None:
    merged = {"defects": [_defect(severity="MEDIUM", admissible_to_block=None)]}

    assert verdict._has_blocking(merged) is False


class _FakeProvider:
    name = "fake"

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
        thinking_disabled: bool = False,
    ) -> GenerationResult:
        return GenerationResult(
            text="", model=model, provider=self.name, input_tokens=1, output_tokens=1
        )


def _blocking_judge_output(**extra: object) -> tuple[list[dict], list[str]]:
    defect = _defect(severity="HIGH", fix="fix the bug")
    defect.update(extra)
    return ([{"defects": [defect], "verdict": "FAIL"}], [])


def _run_pipeline(monkeypatch, tmp_path: Path, judge_output, **kwargs) -> tuple:
    monkeypatch.setattr(
        pipeline,
        "run_automated_gates",
        lambda workspace: [VerificationResult("ruff", True, "ok")],
    )
    monkeypatch.setattr(pipeline, "automated_defects", lambda results: [])
    monkeypatch.setattr(
        pipeline,
        "run_judge_gates",
        lambda gateway, budget, model, task, code, **kw: judge_output,
    )
    return pipeline.run_verification(
        tmp_path,
        LLMGateway(_FakeProvider()),
        BudgetController(max_tokens=100_000, planned_budget=Decimal("1.00")),
        "fake-model",
        EDGE_02_TASK,
        run_id=1,
        task_id="task-1",
        conn=None,
        **kwargs,
    )


def test_14e_pipeline_without_the_flag_adds_no_annotation_and_keeps_blocking(
    monkeypatch, tmp_path: Path
) -> None:
    status, merged, _ = _run_pipeline(
        monkeypatch, tmp_path, _blocking_judge_output(minimal_trigger="user=None")
    )

    assert status == "UNVERIFIED"
    assert "admissible_to_block" not in merged["defects"][0]


def test_14f_pipeline_with_the_flag_annotates_and_can_release(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "solution.py").write_text(EDGE_02_CLEAN, encoding="utf-8")

    status, merged, _ = _run_pipeline(
        monkeypatch,
        tmp_path,
        _blocking_judge_output(minimal_trigger="user=None"),
        adjudicate=True,
    )

    assert merged["defects"][0]["admissible_to_block"] is False
    assert status == "OK"


def test_14g_pipeline_with_the_flag_still_blocks_a_grounded_defect(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "solution.py").write_text(EDGE_02_CLEAN, encoding="utf-8")

    status, merged, _ = _run_pipeline(
        monkeypatch, tmp_path, _blocking_judge_output(), adjudicate=True
    )

    assert merged["defects"][0]["admissible_to_block"] is True
    assert status == "UNVERIFIED"


# ==========================================================================
# PERSISTENCE (additive, scratch DB only)
# ==========================================================================


def test_adjudication_records_persist_without_touching_eval_case_defects(
    tmp_path: Path,
) -> None:
    with db.connect(tmp_path / "scratch.db") as conn:
        run_id = db.create_eval_run(conn, "deadbeef", "bench", "v1", "v6")
        case_id = db.record_eval_case_result(
            conn,
            EvalCaseResult(
                eval_run_id=run_id,
                eval_case_id="edge_case-02-clean",
                task_id="edge_case-02",
                expected_verdict="OK",
                actual_verdict="OK",
                expected_defect_category=None,
                detected_defect_categories=[],
                latency_ms=1,
                cost=Decimal(0),
                passed=True,
                error=None,
            ),
        )
        defect = _defect(severity="HIGH", minimal_trigger="user=None")
        db.record_eval_case_defects(conn, case_id, [{**defect, "lens": "correctness"}])
        db.record_defect_adjudications(
            conn,
            case_id,
            [
                admissibility.adjudication_record(
                    defect, "correctness", EDGE_02_TASK, EDGE_02_CLEAN
                )
            ],
        )

        rows = list(conn.execute("SELECT * FROM eval_case_defect_adjudications"))
        assert len(rows) == 1

        cols = {d[0] for d in conn.execute("PRAGMA table_info(eval_case_defects)")}
        defect_row = conn.execute(
            "SELECT severity FROM eval_case_defects WHERE eval_case_result_id = ?", (case_id,)
        ).fetchone()

    assert defect_row[0] == "HIGH"  # original severity untouched
    assert "admissible_to_block" not in cols  # nothing added to the original table


def test_adjudication_record_marks_nonblocking_defects_not_applicable() -> None:
    # Same severity scope as decide(): a MEDIUM defect is never evaluated, so its
    # record must not claim it is admissible to block.
    for severity in ("MEDIUM", "LOW"):
        record = admissibility.adjudication_record(
            _defect(severity=severity, minimal_trigger="user=None"),
            "correctness",
            EDGE_02_TASK,
            EDGE_02_CLEAN,
        )
        assert record["admissible_to_block"] is None
        assert record["rule"] == "not-applicable"
        assert record["original_severity"] == severity


def test_adjudication_record_captures_forensic_fields(tmp_path: Path) -> None:
    defect = _defect(
        severity="HIGH",
        runtime_probe={
            "predicate": "ipaddress.is_loopback",
            "argument": "::ffff:127.0.0.1",
            "claim": False,
        },
    )

    record = admissibility.adjudication_record(defect, "security", SEC_04_TASK, SEC_04_CLEAN)

    assert record["original_severity"] == "HIGH"
    assert record["defect_id"] == "C1"
    assert record["lens"] == "security"
    assert record["admissible_to_block"] is False
    assert record["probe_predicate"] == "ipaddress.is_loopback"
    assert record["probe_interpreter_version"]
    assert record["adjudicator_version"] == ADJUDICATOR_VERSION
    assert json.loads(record["adjudication_json"])
    assert json.loads(record["evidence_json"])


# ==========================================================================
# FREE OFFLINE REPLAY
# ==========================================================================

_ARCHIVE = Path(
    r"C:\Users\PC\Documents\Codex\2026-09-10"
    r"\referenced-chatgpt-conversation-this-is-an-5\outputs\scratchpad"
    r"\reconciled-adjudication-v2\raw"
)
_PROD_DB = Path(__file__).resolve().parents[1] / ".engine" / "state.db"

_PRESERVED_CASES = ("edge_case-02-broken", "security-03-broken")


@pytest.mark.skipif(not _PROD_DB.exists(), reason="no recorded eval history available")
def test_replay_over_stored_defect_corpus_preserves_every_control_blocker(
    tmp_path: Path,
) -> None:
    """Replay the gate over historical defects from a COPY of the database.

    Historical defects carry no adjudication evidence, so every one of them must
    land on fail-closed-unresolved and keep its blocking authority. Production is
    never opened for writing.
    """
    scratch = tmp_path / "replay.db"
    shutil.copy2(_PROD_DB, scratch)
    conn = sqlite3.connect(f"file:{scratch}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT r.eval_case_id, d.lens, d.defect_id, d.severity, d.location, d.fix "
            "FROM eval_case_defects d "
            "JOIN eval_case_results r ON r.id = d.eval_case_result_id "
            "WHERE d.severity IN ('CRITICAL','HIGH') "
            f"AND r.eval_case_id IN ({','.join('?' * len(_PRESERVED_CASES))})",
            _PRESERVED_CASES,
        ).fetchall()
    finally:
        conn.close()

    assert rows, "expected recorded control blockers to replay against"

    for case_id, _lens, defect_id, severity, location, fix in rows:
        defect = {
            "id": defect_id,
            "category": "CORRECTNESS",
            "severity": severity,
            "location": location,
            "fix": fix,
        }
        decision = _decide(defect, "task text unavailable for replay", "code unavailable")
        assert decision.admissible is True, f"{case_id}/{defect_id} lost blocking authority"
        assert decision.rule == "fail-closed-unresolved"


@pytest.mark.skipif(not _ARCHIVE.exists(), reason="archived judge blobs not present")
def test_replay_over_archived_schema_failure_blobs_never_suppresses_a_blocker() -> None:
    """Every archived malformed blob replays without any blocker being suppressed.

    These blobs are exactly the corpus the frozen adjudication spec was built
    from, including the heavily self-retracting ones. None of them carries
    structured evidence, so none may lose blocking authority here.
    """
    blobs = sorted(_ARCHIVE.glob("failure-*.txt"))
    assert blobs

    seen = 0
    for path in blobs:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        payload = json.loads(text)
        for raw in payload.get("defects", []):
            if raw.get("severity") not in ("CRITICAL", "HIGH"):
                continue
            seen += 1
            decision = _decide(raw, SEC_04_TASK, SEC_04_CLEAN)
            assert decision.admissible is True, f"{path.name}/{raw.get('id')} was suppressed"

    assert seen, "expected at least one archived blocking defect"
