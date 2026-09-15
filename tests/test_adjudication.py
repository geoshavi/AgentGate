"""Unit tests for the adjudication layer and its probe registry.

These cover the separation the design turns on: a judge *asserts*, the
adjudicator *decides*. Nothing here may let a model-supplied field stand as a
verified fact, and every ambiguous path must land on UNRESOLVED.
"""

from engine.verification.adjudication import (
    CONTRADICTED,
    UNRESOLVED,
    VERIFIED,
    adjudicate,
    extract_evidence,
)
from engine.verification.probes import PROBE_REGISTRY, run_probe

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


# --------------------------------------------------------------------------
# evidence extraction never trusts, never raises
# --------------------------------------------------------------------------


def test_extract_evidence_returns_all_none_when_defect_carries_no_evidence() -> None:
    ev = extract_evidence(_defect())

    assert ev.grounded_in_clause is None
    assert ev.excluded_by_clause is None
    assert ev.minimal_trigger is None
    assert ev.grounding_route is None
    assert ev.runtime_probe is None


def test_extract_evidence_ignores_non_string_and_malformed_values() -> None:
    ev = extract_evidence(
        _defect(
            grounded_in_clause=123,
            minimal_trigger=["not", "a", "string"],
            grounding_route="not_a_registered_route",
            runtime_probe="not an object",
        )
    )

    assert ev.grounded_in_clause is None
    assert ev.minimal_trigger is None
    assert ev.grounding_route is None
    assert ev.runtime_probe is None


# --------------------------------------------------------------------------
# declared-interface adjudication (edge_case-02-clean, suppression target 1)
# --------------------------------------------------------------------------


def test_trigger_outside_declared_parameter_annotation_is_contradicted() -> None:
    defect = _defect(minimal_trigger="user=None")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.trigger_in_contract.status == CONTRADICTED
    assert adj.trigger_in_contract.rule == "declared-interface"


def test_trigger_inside_declared_parameter_annotation_is_verified() -> None:
    defect = _defect(minimal_trigger="user={}")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.trigger_in_contract.status == VERIFIED


def test_trigger_for_unknown_parameter_name_is_unresolved() -> None:
    defect = _defect(minimal_trigger="nosuchparam=None")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.trigger_in_contract.status == UNRESOLVED


def test_trigger_against_complex_annotation_is_unresolved() -> None:
    code = "def f(items: list[dict[str, int]]) -> None:\n    return None\n"
    defect = _defect(minimal_trigger="items=None")

    adj = adjudicate(defect, extract_evidence(defect), "task", code)

    assert adj.trigger_in_contract.status == UNRESOLVED


def test_unparseable_minimal_trigger_is_unresolved() -> None:
    defect = _defect(minimal_trigger="whatever the model felt like writing")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.trigger_in_contract.status == UNRESOLVED


def test_absent_minimal_trigger_is_unresolved() -> None:
    defect = _defect()

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.trigger_in_contract.status == UNRESOLVED


# --------------------------------------------------------------------------
# return-type contradiction (edge_case-02-clean, suppression target 2)
# --------------------------------------------------------------------------


def test_claimed_bad_return_permitted_by_declared_union_is_contradicted() -> None:
    defect = _defect(minimal_trigger="return=None")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.violation_present_in_submitted_code.status == CONTRADICTED
    assert adj.violation_present_in_submitted_code.rule == "declared-return-type"


def test_claimed_bad_return_outside_declared_union_is_unresolved() -> None:
    defect = _defect(minimal_trigger="return=42")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.violation_present_in_submitted_code.status == UNRESOLVED


# --------------------------------------------------------------------------
# explicit-guarantee adjudication (security-04-clean, suppression target 3)
# --------------------------------------------------------------------------


def test_guarantee_quoted_verbatim_from_task_is_verified() -> None:
    defect = _defect(
        excluded_by_clause="The caller connects to the address you return and does not look "
        "the host up again"
    )

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.premise_excluded_by_guarantee.status == VERIFIED
    assert adj.premise_excluded_by_guarantee.rule == "explicit-guarantee"


def test_guarantee_paraphrased_rather_than_quoted_is_unsupported() -> None:
    defect = _defect(excluded_by_clause="the caller promises not to re-resolve the hostname")

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.premise_excluded_by_guarantee.status != VERIFIED


def test_guarantee_match_tolerates_whitespace_differences_only() -> None:
    defect = _defect(
        excluded_by_clause="The caller connects to the address you return\n  and does not "
        "look the host up again"
    )

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.premise_excluded_by_guarantee.status == VERIFIED


def test_absent_guarantee_clause_is_unresolved() -> None:
    defect = _defect()

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.premise_excluded_by_guarantee.status == UNRESOLVED


# --------------------------------------------------------------------------
# probes (suppression target 4)
# --------------------------------------------------------------------------


def test_probe_registry_contains_only_pure_stdlib_address_predicates() -> None:
    assert PROBE_REGISTRY
    for key in PROBE_REGISTRY:
        assert key.startswith("ipaddress.")


def test_probe_evaluates_registered_predicate_and_records_interpreter_version() -> None:
    result = run_probe("ipaddress.is_loopback", "::ffff:127.0.0.1")

    assert result.ok is True
    assert result.value is True
    assert result.interpreter_version
    assert result.predicate == "ipaddress.is_loopback"
    assert result.argument == "::ffff:127.0.0.1"


def test_probe_on_unknown_predicate_fails_without_raising() -> None:
    result = run_probe("os.system", "rm -rf /")

    assert result.ok is False
    assert result.value is None
    assert "unknown predicate" in result.error


def test_probe_on_unparseable_argument_fails_without_raising() -> None:
    result = run_probe("ipaddress.is_loopback", "not-an-address")

    assert result.ok is False
    assert result.value is None


def test_probe_refuting_the_judges_claim_contradicts_the_premise() -> None:
    # The judge claims ::ffff:127.0.0.1 is NOT caught by the loopback check.
    defect = _defect(
        runtime_probe={
            "predicate": "ipaddress.is_loopback",
            "argument": "::ffff:127.0.0.1",
            "claim": False,
        }
    )

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.violation_present_in_submitted_code.status == CONTRADICTED
    assert adj.violation_present_in_submitted_code.rule == "runtime-probe"
    assert adj.probe is not None
    assert adj.probe.value is True


def test_probe_confirming_the_judges_claim_never_verifies_a_violation() -> None:
    # A probe may only ever REMOVE blocking authority, never create it.
    defect = _defect(
        runtime_probe={
            "predicate": "ipaddress.is_private",
            "argument": "100.64.0.0",
            "claim": False,
        }
    )

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.violation_present_in_submitted_code.status != VERIFIED
    assert adj.violation_present_in_submitted_code.status == UNRESOLVED


def test_unknown_probe_predicate_leaves_premise_unresolved() -> None:
    defect = _defect(
        runtime_probe={"predicate": "subprocess.run", "argument": "ls", "claim": False}
    )

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.violation_present_in_submitted_code.status == UNRESOLVED


def test_failing_probe_leaves_premise_unresolved() -> None:
    defect = _defect(
        runtime_probe={
            "predicate": "ipaddress.is_loopback",
            "argument": "definitely not an address",
            "claim": False,
        }
    )

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.violation_present_in_submitted_code.status == UNRESOLVED


def test_probe_without_a_claim_field_is_unresolved() -> None:
    defect = _defect(
        runtime_probe={"predicate": "ipaddress.is_loopback", "argument": "::ffff:127.0.0.1"}
    )

    adj = adjudicate(defect, extract_evidence(defect), SEC_04_TASK, SEC_04_CLEAN)

    assert adj.violation_present_in_submitted_code.status == UNRESOLVED


# --------------------------------------------------------------------------
# retraction
# --------------------------------------------------------------------------


def test_load_bearing_retraction_marker_is_detected() -> None:
    defect = _defect(fix="No fix needed; retracted concern")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.self_contradiction.status == VERIFIED


def test_ordinary_fix_prose_is_not_treated_as_a_retraction() -> None:
    defect = _defect(fix="Validate the filename before invoking the converter")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert adj.self_contradiction.status != VERIFIED


# --------------------------------------------------------------------------
# the adjudicator never raises and never mutates the defect
# --------------------------------------------------------------------------


def test_adjudicate_never_mutates_the_defect_it_is_given() -> None:
    defect = _defect(minimal_trigger="user=None")
    before = dict(defect)

    adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, EDGE_02_CLEAN)

    assert defect == before


def test_adjudicate_survives_unparseable_code_snapshot() -> None:
    defect = _defect(minimal_trigger="user=None")

    adj = adjudicate(defect, extract_evidence(defect), EDGE_02_TASK, "def broken(:\n")

    assert adj.trigger_in_contract.status == UNRESOLVED
