"""Shadow adjudication: compute and persist, never decide.

The single property every test here defends: with ``shadow_adjudicate=True`` the
authoritative verdict is byte-identical to ``shadow_adjudicate=False`` on the
same inputs. Shadow annotations reach a sidecar table and nothing else -- they
never touch ``merged["defects"]``, so they can never reach
``verdict._has_blocking``.

This is deliberately a different flag from the authoritative ``adjudicate=True``
path, which annotates the dict that ``gate`` reads. Combining the two is
rejected rather than silently ordered.
"""

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from engine.providers.base import GenerationResult, Message
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state import db
from engine.state.models import VerificationResult
from engine.verification import pipeline, verdict

TASK = (
    "Implement get_user_email(user) -> str | None that safely reads "
    "user['profile']['email'], returning None if any part of that path is missing, "
    "without raising."
)
CLEAN = (
    "def get_user_email(user: dict) -> str | None:\n"
    '    profile = user.get("profile")\n'
    "    if not isinstance(profile, dict):\n"
    "        return None\n"
    '    email = profile.get("email")\n'
    "    return email if isinstance(email, str) else None\n"
)


def _defect(**overrides: object) -> dict:
    base: dict = {
        "id": "C1",
        "category": "CORRECTNESS",
        "severity": "HIGH",
        "location": "get_user_email",
        "fix": "user=None raises AttributeError",
        "lens": "correctness",
    }
    base.update(overrides)
    return base


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


def _run(
    monkeypatch,
    tmp_path: Path,
    defects: list[dict],
    *,
    schema_errors: list[str] | None = None,
    automated_ok: bool = True,
    task: str = TASK,
    code: str = CLEAN,
    **kwargs,
):
    (tmp_path / "solution.py").write_text(code, encoding="utf-8")
    monkeypatch.setattr(
        pipeline,
        "run_automated_gates",
        lambda workspace: [VerificationResult("ruff", automated_ok, "detail")],
    )
    monkeypatch.setattr(pipeline, "automated_defects", lambda results: [])
    monkeypatch.setattr(
        pipeline,
        "run_judge_gates",
        lambda gateway, budget, model, task_arg, code_arg, **kw: (
            [{"defects": defects, "verdict": "FAIL" if defects else "OK"}],
            list(schema_errors or []),
        ),
    )
    return pipeline.run_verification(
        tmp_path,
        LLMGateway(_FakeProvider()),
        BudgetController(max_tokens=100_000, planned_budget=Decimal("1.00")),
        "fake-model",
        task,
        run_id=1,
        task_id="task-1",
        conn=None,
        **kwargs,
    )


# ==========================================================================
# A. shadow OFF -- current behaviour unchanged
# ==========================================================================


def test_a_shadow_off_leaves_merged_exactly_as_today(monkeypatch, tmp_path: Path) -> None:
    status, merged, _ = _run(monkeypatch, tmp_path, [_defect(minimal_trigger="user=None")])

    assert status == "UNVERIFIED"
    assert "shadow_adjudications" not in merged
    assert "admissible_to_block" not in merged["defects"][0]


# ==========================================================================
# B/C/D. shadow ON -- authoritative verdict identical
# ==========================================================================


@pytest.mark.parametrize(
    "defects",
    [
        # C: a defect that WOULD be ruled inadmissible authoritatively
        [_defect(minimal_trigger="user=None")],
        # D: every blocker hypothetically inadmissible
        [
            _defect(id="C1", minimal_trigger="user=None"),
            _defect(id="C2", severity="CRITICAL", minimal_trigger="user=None"),
        ],
        # a genuinely grounded blocker with no evidence
        [_defect(id="C1", fix="raises KeyError on missing profile")],
        # non-blocking only
        [_defect(id="C1", severity="MEDIUM")],
        # no defects at all
        [],
    ],
)
def test_bcd_shadow_on_matches_shadow_off_verdict(monkeypatch, tmp_path, defects) -> None:
    off_status, off_merged, _ = _run(monkeypatch, tmp_path, defects)
    on_status, on_merged, _ = _run(monkeypatch, tmp_path, defects, shadow_adjudicate=True)

    assert on_status == off_status
    assert on_merged["defects"] == off_merged["defects"]
    assert on_merged["verdict"] == off_merged["verdict"]
    assert verdict._has_blocking(on_merged) == verdict._has_blocking(off_merged)


def test_c_inadmissible_defect_still_blocks_under_shadow(monkeypatch, tmp_path: Path) -> None:
    status, merged, _ = _run(
        monkeypatch, tmp_path, [_defect(minimal_trigger="user=None")], shadow_adjudicate=True
    )

    assert status == "UNVERIFIED"
    # the shadow record says it would be inadmissible ...
    assert merged["shadow_adjudications"][0]["admissible_to_block"] is False
    # ... and the authoritative defect is untouched by that conclusion
    assert "admissible_to_block" not in merged["defects"][0]
    assert verdict._has_blocking(merged) is True


def test_d_all_blockers_inadmissible_still_unverified(monkeypatch, tmp_path: Path) -> None:
    defects = [
        _defect(id="C1", minimal_trigger="user=None"),
        _defect(id="C2", severity="CRITICAL", minimal_trigger="user=None"),
    ]
    status, merged, _ = _run(monkeypatch, tmp_path, defects, shadow_adjudicate=True)

    assert [r["admissible_to_block"] for r in merged["shadow_adjudications"]] == [False, False]
    assert status == "UNVERIFIED"


# ==========================================================================
# E/F. fail-closed dominance is untouched
# ==========================================================================


def test_e_schema_failure_stays_unverified_and_shadow_cannot_rescue(
    monkeypatch, tmp_path: Path
) -> None:
    status, merged, _ = _run(
        monkeypatch,
        tmp_path,
        [_defect(minimal_trigger="user=None")],
        schema_errors=["judge:correctness: bad json"],
        shadow_adjudicate=True,
    )

    assert status == "UNVERIFIED"
    assert merged["schema_errors"] == ["judge:correctness: bad json"]
    assert merged["shadow_adjudications"][0]["admissible_to_block"] is False


def test_f_automated_gate_failure_still_dominates(monkeypatch, tmp_path: Path) -> None:
    status, _merged, _ = _run(
        monkeypatch,
        tmp_path,
        [_defect(id="C1", severity="MEDIUM")],
        automated_ok=False,
        shadow_adjudicate=True,
    )

    assert status == "UNVERIFIED"


# ==========================================================================
# G. retry feedback sees original defects only
# ==========================================================================


def test_g_retry_feedback_identical_between_shadow_modes(monkeypatch, tmp_path: Path) -> None:
    defects = [_defect(minimal_trigger="user=None")]
    _s1, off_merged, _ = _run(monkeypatch, tmp_path, defects)
    _s2, on_merged, _ = _run(monkeypatch, tmp_path, defects, shadow_adjudicate=True)

    feedback = pipeline.build_retry_feedback(on_merged)
    assert feedback == pipeline.build_retry_feedback(off_merged)
    assert "admissible_to_block" not in feedback
    assert "fail-closed-unresolved" not in feedback


# ==========================================================================
# J. optional evidence absent -> UNRESOLVED shadow record, no verdict effect
# ==========================================================================


def test_j_absent_evidence_records_unresolved_and_changes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    status, merged, _ = _run(
        monkeypatch, tmp_path, [_defect(fix="no evidence at all")], shadow_adjudicate=True
    )

    record = merged["shadow_adjudications"][0]
    assert record["admissible_to_block"] is True
    assert record["rule"] == "fail-closed-unresolved"
    assert status == "UNVERIFIED"


def test_j_nonblocking_defects_are_recorded_as_not_applicable(
    monkeypatch, tmp_path: Path
) -> None:
    status, merged, _ = _run(
        monkeypatch, tmp_path, [_defect(severity="LOW")], shadow_adjudicate=True
    )

    assert merged["shadow_adjudications"][0]["admissible_to_block"] is None
    assert status == "OK"


def test_shadow_record_carries_lens_and_original_severity(monkeypatch, tmp_path: Path) -> None:
    _status, merged, _ = _run(
        monkeypatch,
        tmp_path,
        [_defect(lens="security", severity="CRITICAL")],
        shadow_adjudicate=True,
    )

    record = merged["shadow_adjudications"][0]
    assert record["lens"] == "security"
    assert record["original_severity"] == "CRITICAL"
    assert record["adjudicator_version"]


# ==========================================================================
# K. the authoritative adjudicate=True path is unchanged
# ==========================================================================


def test_k_authoritative_path_still_annotates_and_releases(monkeypatch, tmp_path: Path) -> None:
    status, merged, _ = _run(
        monkeypatch, tmp_path, [_defect(minimal_trigger="user=None")], adjudicate=True
    )

    assert merged["defects"][0]["admissible_to_block"] is False
    assert status == "OK"
    assert "shadow_adjudications" not in merged


# ==========================================================================
# L. the ambiguous combination is rejected
# ==========================================================================


def test_l_both_flags_together_is_rejected(monkeypatch, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="adjudicate.*shadow_adjudicate"):
        _run(
            monkeypatch,
            tmp_path,
            [_defect()],
            adjudicate=True,
            shadow_adjudicate=True,
        )


# ==========================================================================
# H/I. persistence -- scratch DB only, production never opened
# ==========================================================================


def test_h_shadow_rows_persist_to_the_sidecar_only(tmp_path: Path) -> None:
    from engine.state.models import EvalCaseResult
    from engine.verification import admissibility

    with db.connect(tmp_path / "scratch.db") as conn:
        run_id = db.create_eval_run(conn, "deadbeef", "bench", "v1", "v6")
        result = EvalCaseResult(
            eval_run_id=run_id,
            eval_case_id="edge_case-02-clean",
            task_id="edge_case-02",
            expected_verdict="OK",
            actual_verdict="UNVERIFIED",
            expected_defect_category=None,
            detected_defect_categories=[],
            latency_ms=1,
            cost=Decimal(0),
            passed=False,
            error=None,
            defects=[_defect(minimal_trigger="user=None")],
            shadow_adjudications=[
                admissibility.adjudication_record(
                    _defect(minimal_trigger="user=None"), "correctness", TASK, CLEAN
                )
            ],
        )
        case_id = db.record_eval_case_result(conn, result)
        db.record_eval_case_defects(conn, case_id, result.defects)
        db.record_defect_adjudications(conn, case_id, result.shadow_adjudications)

        sidecar = conn.execute(
            "SELECT defect_id, original_severity, admissible_to_block, rule "
            "FROM eval_case_defect_adjudications WHERE eval_case_result_id=?", (case_id,)
        ).fetchall()
        original = conn.execute(
            "SELECT severity FROM eval_case_defects WHERE eval_case_result_id=?", (case_id,)
        ).fetchall()

    assert sidecar == [("C1", "HIGH", 0, "declared-interface")]
    assert original == [("HIGH",)]  # untouched


def test_i_production_database_is_never_opened_by_these_tests() -> None:
    prod = Path(__file__).resolve().parents[1] / ".engine" / "state.db"
    if not prod.exists():
        pytest.skip("no production database present")
    # sqlite writes leave -wal/-shm sidecars; their absence is the evidence
    assert not prod.with_name(prod.name + "-wal").exists()
    assert not prod.with_name(prod.name + "-shm").exists()


# ==========================================================================
# runner wiring -- both arms share one authoritative path
# ==========================================================================


def test_runner_passes_shadow_flag_through_without_touching_the_verdict(
    monkeypatch, tmp_path: Path
) -> None:
    from engine.eval import runner
    from engine.eval.dataset import CASES

    captured: dict = {}

    def _fake_run_verification(workspace, gateway, budget, judge_model, task_text, **kw):
        captured.update(kw)
        merged = {
            "defects": [_defect(minimal_trigger="user=None")],
            "verdict": "FAIL",
            "shadow_adjudications": [{"defect_id": "C1", "rule": "declared-interface"}],
        }
        return "UNVERIFIED", merged, [VerificationResult("ruff", True, "ok")]

    monkeypatch.setattr(runner, "run_verification", _fake_run_verification)
    monkeypatch.setattr(runner.db, "get_agent_execution_metrics_by_task", lambda *a, **k: [])

    case = next(c for c in CASES if c.eval_case_id == "edge_case-02-clean")
    with db.connect(tmp_path / "runner.db") as conn:
        result = runner.run_case(
            case,
            gateway=LLMGateway(_FakeProvider()),
            budget=BudgetController(max_tokens=1000, planned_budget=Decimal("1.00")),
            judge_model="fake-model",
            conn=conn,
            run_id=1,
            eval_run_id=1,
            shadow_adjudicate=True,
        )

    assert captured["shadow_adjudicate"] is True
    assert result.actual_verdict == "UNVERIFIED"
    assert result.shadow_adjudications == [{"defect_id": "C1", "rule": "declared-interface"}]
    assert "admissible_to_block" not in result.defects[0]


def test_runner_defaults_to_no_shadow(monkeypatch, tmp_path: Path) -> None:
    from engine.eval import runner
    from engine.eval.dataset import CASES

    captured: dict = {}

    def _fake_run_verification(workspace, gateway, budget, judge_model, task_text, **kw):
        captured.update(kw)
        return "OK", {"defects": [], "verdict": "OK"}, []

    monkeypatch.setattr(runner, "run_verification", _fake_run_verification)
    monkeypatch.setattr(runner.db, "get_agent_execution_metrics_by_task", lambda *a, **k: [])

    case = next(c for c in CASES if c.eval_case_id == "edge_case-02-clean")
    with db.connect(tmp_path / "runner.db") as conn:
        result = runner.run_case(
            case,
            gateway=LLMGateway(_FakeProvider()),
            budget=BudgetController(max_tokens=1000, planned_budget=Decimal("1.00")),
            judge_model="fake-model",
            conn=conn,
            run_id=1,
            eval_run_id=1,
        )

    assert captured.get("shadow_adjudicate") is False
    assert result.shadow_adjudications == []


# ==========================================================================
# no-op proof over a replayed corpus
# ==========================================================================


def test_no_op_proof_across_a_replayed_defect_corpus(monkeypatch, tmp_path: Path) -> None:
    """Same inputs, both modes, every observable compared."""
    corpus = [
        [],
        [_defect(id="C1", severity="LOW")],
        [_defect(id="C1", severity="MEDIUM", minimal_trigger="user=None")],
        [_defect(id="C1", minimal_trigger="user=None")],
        [_defect(id="C1", minimal_trigger="user={}")],
        [_defect(id="C1", severity="CRITICAL", fix="raises KeyError")],
        [
            _defect(id="C1", minimal_trigger="user=None"),
            _defect(id="C2", severity="CRITICAL", fix="genuine"),
        ],
        [_defect(id="C1", minimal_trigger="return=None")],
        [_defect(id="C1", grounding_route="stated_purpose")],
    ]

    for defects in corpus:
        off_status, off_merged, off_auto = _run(monkeypatch, tmp_path, defects)
        on_status, on_merged, on_auto = _run(
            monkeypatch, tmp_path, defects, shadow_adjudicate=True
        )

        assert on_status == off_status
        assert on_merged["defects"] == off_merged["defects"]
        assert on_merged["verdict"] == off_merged["verdict"]
        assert on_merged.get("schema_errors") == off_merged.get("schema_errors")
        assert verdict._has_blocking(on_merged) == verdict._has_blocking(off_merged)
        assert pipeline.build_retry_feedback(on_merged) == pipeline.build_retry_feedback(
            off_merged
        )
        assert [r.passed for r in on_auto] == [r.passed for r in off_auto]
        # the ONLY difference permitted
        assert set(on_merged) - set(off_merged) == {"shadow_adjudications"}


def test_shadow_records_cover_every_defect_including_nonblocking(
    monkeypatch, tmp_path: Path
) -> None:
    defects = [
        _defect(id="C1", severity="HIGH"),
        _defect(id="C2", severity="MEDIUM"),
        _defect(id="C3", severity="LOW"),
    ]
    _status, merged, _ = _run(monkeypatch, tmp_path, defects, shadow_adjudicate=True)

    assert [r["defect_id"] for r in merged["shadow_adjudications"]] == ["C1", "C2", "C3"]
    assert [r["admissible_to_block"] for r in merged["shadow_adjudications"]] == [
        True,
        None,
        None,
    ]


def test_shadow_adjudication_failure_never_breaks_verification(
    monkeypatch, tmp_path: Path
) -> None:
    """If shadow bookkeeping raises, the authoritative verdict must still land."""
    from engine.verification import admissibility

    def _boom(*_a, **_k):
        raise RuntimeError("shadow exploded")

    monkeypatch.setattr(admissibility, "adjudication_record", _boom)
    status, merged, _ = _run(
        monkeypatch, tmp_path, [_defect()], shadow_adjudicate=True
    )

    assert status == "UNVERIFIED"
    assert merged["shadow_adjudications"] == []


def test_sqlite_connection_is_read_only_safe_for_replay(tmp_path: Path) -> None:
    """Sanity: a mode=ro connection refuses writes, which is how replay reads."""
    path = tmp_path / "ro.db"
    with db.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO t VALUES (1)")
    finally:
        ro.close()


# ==========================================================================
# Contract evidence mining wired into the shadow-only sidecar
# (CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md). Every property proven
# above for shadow adjudication in general must still hold once the sidecar
# additionally mines evidence from a defect's own free text -- these tests
# exercise that through the real pipeline.run_verification() path, not the
# miner or admissibility.decide() in isolation (already covered by
# tests/test_evidence_mining.py and tests/test_admissibility.py).
# ==========================================================================

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

SEC_03_TASK = (
    "Implement generate_reset_token() -> str returning a random 32-character hex "
    "token for password-reset links."
)
SEC_03_BROKEN = (
    "import random\n\n\n"
    "def generate_reset_token() -> str:\n"
    '    return "".join(random.choice("0123456789abcdef") for _ in range(32))\n'
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

_MINED_HIGH = _defect(
    id="C1",
    category="CORRECTNESS",
    severity="HIGH",
    location='solution.py: user.get("profile")',
    fix=(
        "Guard against user not being a dict (e.g., None or other type) by checking "
        "isinstance(user, dict) before calling .get, to avoid AttributeError."
    ),
)


def test_shadow_mining_a_actual_verdict_unchanged_with_mining_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    """A: the miner recognizes this defect's text and would, under shadow, mark it
    inadmissible -- but the ACTUAL verdict must be identical with mining on vs off,
    exactly like every other shadow-adjudication property proven above."""
    off_status, off_merged, _ = _run(monkeypatch, tmp_path, [_MINED_HIGH])
    on_status, on_merged, _ = _run(monkeypatch, tmp_path, [_MINED_HIGH], shadow_adjudicate=True)

    assert on_status == off_status == "UNVERIFIED"
    assert on_merged["defects"] == off_merged["defects"]
    assert on_merged["verdict"] == off_merged["verdict"]
    assert "minimal_trigger" not in on_merged["defects"][0]  # mining never touches the original
    assert set(on_merged) - set(off_merged) == {"shadow_adjudications"}


def test_shadow_mining_b_edge_case_02_clean_mined_and_shadow_inadmissible_but_still_blocks(
    monkeypatch, tmp_path: Path
) -> None:
    """B."""
    status, merged, _ = _run(monkeypatch, tmp_path, [_MINED_HIGH], shadow_adjudicate=True)

    record = merged["shadow_adjudications"][0]
    assert json.loads(record["evidence_json"])["minimal_trigger"] == "user=None"
    assert record["rule"] == "declared-interface"
    assert record["admissible_to_block"] is False
    # non-authoritative: the actual verdict still blocks
    assert status == "UNVERIFIED"
    assert verdict._has_blocking(merged) is True


def test_shadow_mining_c_quality_04_broken_miner_emits_nothing_blocker_survives(
    monkeypatch, tmp_path: Path
) -> None:
    """C."""
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

    status, merged, _ = _run(
        monkeypatch,
        tmp_path,
        [defect],
        task=QUALITY_04_TASK,
        code=QUALITY_04_BROKEN,
        shadow_adjudicate=True,
    )

    record = merged["shadow_adjudications"][0]
    assert json.loads(record["evidence_json"])["minimal_trigger"] is None
    assert record["admissible_to_block"] is True
    assert status == "UNVERIFIED"


def test_shadow_mining_d_security_03_broken_miner_emits_nothing_sole_blocker_survives(
    monkeypatch, tmp_path: Path
) -> None:
    """D."""
    defect = _defect(
        category="SECURITY",
        severity="HIGH",
        location="solution.py: generate_reset_token",
        fix=(
            "random.choice over a fixed alphabet is not cryptographically secure; use "
            "secrets.token_hex instead."
        ),
    )

    status, merged, _ = _run(
        monkeypatch,
        tmp_path,
        [defect],
        task=SEC_03_TASK,
        code=SEC_03_BROKEN,
        shadow_adjudicate=True,
    )

    record = merged["shadow_adjudications"][0]
    assert json.loads(record["evidence_json"])["minimal_trigger"] is None
    assert record["admissible_to_block"] is True
    assert status == "UNVERIFIED"


def test_shadow_mining_e_edge_case_02_broken_no_unsafe_hit_remains_blocked(
    monkeypatch, tmp_path: Path
) -> None:
    """E."""
    defect = _defect(
        location='solution.py: user["profile"]["email"]',
        fix=(
            "Missing handling for an absent 'profile' or 'email' key: this raises "
            "KeyError instead of returning None."
        ),
    )

    status, merged, _ = _run(
        monkeypatch,
        tmp_path,
        [defect],
        task=TASK,
        code=EDGE_02_BROKEN,
        shadow_adjudicate=True,
    )

    record = merged["shadow_adjudications"][0]
    assert json.loads(record["evidence_json"])["minimal_trigger"] is None
    assert record["admissible_to_block"] is True
    assert status == "UNVERIFIED"


def test_shadow_mining_f_security_04_broken_no_unsafe_hit_remains_blocked(
    monkeypatch, tmp_path: Path
) -> None:
    """F."""
    defect = _defect(
        category="SECURITY",
        location="solution.py: resolve_safe_fetch_target",
        fix=(
            "No validation of the resolved address at all; internal/private addresses "
            "are never rejected, allowing SSRF against internal services."
        ),
    )

    status, merged, _ = _run(
        monkeypatch,
        tmp_path,
        [defect],
        task=SEC_04_TASK,
        code=SEC_04_BROKEN,
        shadow_adjudicate=True,
    )

    record = merged["shadow_adjudications"][0]
    assert json.loads(record["evidence_json"])["minimal_trigger"] is None
    assert record["admissible_to_block"] is True
    assert status == "UNVERIFIED"


def test_shadow_mining_g_security_04_clean_no_hit_explicitly_unsolved(
    monkeypatch, tmp_path: Path
) -> None:
    """G."""
    defect = _defect(
        category="SECURITY",
        severity="CRITICAL",
        location="solution.py: resolve_safe_fetch_target return addresses[0]",
        fix=(
            "The function validates ALL resolved addresses are public but then returns "
            "addresses[0], the first address from getaddrinfo, not necessarily the one "
            "that was validated in a TOCTOU/DNS-rebinding sense."
        ),
    )

    status, merged, _ = _run(
        monkeypatch,
        tmp_path,
        [defect],
        task=SEC_04_TASK,
        code=SEC_04_CLEAN,
        shadow_adjudicate=True,
    )

    record = merged["shadow_adjudications"][0]
    assert json.loads(record["evidence_json"])["minimal_trigger"] is None
    # still blocking -- unsolved by this mechanism, exactly as registered/designed
    assert record["admissible_to_block"] is True
    assert status == "UNVERIFIED"


def test_shadow_mining_h_no_judge_prompt_severity_or_schema_change(
    monkeypatch, tmp_path: Path
) -> None:
    """H: this wiring touches only pipeline.py's shadow path."""
    import hashlib

    from engine.verification.judge import RESPONSE_INSTRUCTION
    from engine.verification.rubric import DEFECT_KEYS, SEVERITIES
    from engine.verification.schema import enforce_critic_schema

    assert (
        hashlib.sha256(RESPONSE_INSTRUCTION.encode()).hexdigest()
        == "e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f"
    )
    assert SEVERITIES == frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
    assert DEFECT_KEYS == frozenset({"id", "category", "severity", "location", "fix"})
    # a mined-shaped defect must not confuse the unmodified schema validator
    assert enforce_critic_schema({"defects": [_MINED_HIGH], "verdict": "FAIL"}) == []

    # and the ACTUAL verdict is unaffected by shadow mining regardless
    status, merged, _ = _run(monkeypatch, tmp_path, [_MINED_HIGH], shadow_adjudicate=True)
    assert status == "UNVERIFIED"
    assert "minimal_trigger" not in merged["defects"][0]
