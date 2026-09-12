"""Offline, prompt-neutral evidence mining -- a research prototype.

Pins the design from the AgentGate forensic-analysis turn: a narrow,
case-blind text pattern that recovers a `minimal_trigger` for the *existing,
unmodified* declared-interface adjudication path (`adjudication.py`,
`admissibility.py`) without asking the judge for anything new. The judge
prompt, severity, and every existing defect field are untouched by this
module; it only ever adds an out-of-band `minimal_trigger` candidate that
downstream adjudication may use or ignore.

NOT wired into pipeline.py, verdict.py, or any authoritative path. These
tests exercise `mine_trigger_evidence` in isolation.
"""

from engine.verification.evidence_mining import (
    mine_return_value_evidence,
    mine_trigger_evidence,
)

# --- edge_case-02 fixtures (dict-shaped fixtures deliberately mirror the
# historical task/code, but the module under test never sees a case id) ----

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
EDGE_02_OPTIONAL_CLEAN = (
    "def get_user_email(user: dict | None) -> str | None:\n"
    "    if user is None:\n"
    "        return None\n"
    '    profile = user.get("profile")\n'
    "    if not isinstance(profile, dict):\n"
    "        return None\n"
    '    email = profile.get("email")\n'
    "    return email if isinstance(email, str) else None\n"
)

# --- security-04 fixtures ---------------------------------------------------

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

# --- security-03 fixture ----------------------------------------------------

SEC_03_TASK = (
    "Implement generate_reset_token() -> str returning a random 32-character hex "
    "token for password-reset links."
)
SEC_03_BROKEN = (
    "import random\n\n\n"
    "def generate_reset_token() -> str:\n"
    '    return "".join(random.choice("0123456789abcdef") for _ in range(32))\n'
)

# --- quality-04 fixture ------------------------------------------------------

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
    "        return \"standard\"\n"
    '    return "rejected"\n'
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


# ==========================================================================
# 1. The historical edge_case-02-clean claim: a real hit
# ==========================================================================


def test_1_declared_dict_parameter_with_none_literal_is_mined() -> None:
    defect = _defect(
        location="solution.py: user.get(\"profile\")",
        fix=(
            "Guard against user not being a dict (e.g., None or other type) by checking "
            "isinstance(user, dict) before calling .get, to avoid AttributeError."
        ),
    )

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {"minimal_trigger": "user=None"}


# ==========================================================================
# 2. Unrelated prose / no exact parameter name -> {}
# ==========================================================================


def test_2_literal_present_but_no_declared_parameter_named_nearby() -> None:
    defect = _defect(
        location="solution.py: email = profile.get(\"email\")",
        fix=(
            "Return the value found at user['profile']['email'] regardless of its type; "
            "only return None when the key/path itself is missing."
        ),
    )

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {}


def test_2b_literal_with_no_parenthetical_hint_at_all() -> None:
    defect = _defect(
        fix="If user is not a dict, user.get will raise AttributeError; guard against None.",
    )

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {}


# ==========================================================================
# 3. Optional/union parameter -> {} (already admits None, not a contradiction)
# ==========================================================================


def test_3_optional_parameter_is_never_mined() -> None:
    defect = _defect(
        fix="Guard against user not being a dict (e.g., None or other type) before calling .get",
    )

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_OPTIONAL_CLEAN)

    assert evidence == {}


# ==========================================================================
# 4. Ambiguous multi-trigger text -> {}
# ==========================================================================


def test_4_two_competing_candidate_triggers_stays_unmined() -> None:
    code = (
        "def merge(user: dict, profile: dict) -> dict | None:\n"
        "    return {**user, **profile}\n"
    )
    defect = _defect(
        fix=(
            "Guard against user not being a dict (e.g., None) and also guard against "
            "profile being empty (e.g., {}) before merging."
        ),
    )

    evidence = mine_trigger_evidence(defect, "irrelevant task text", code)

    assert evidence == {}


# ==========================================================================
# 5. quality-04-broken: permanent regression guard
# ==========================================================================


def test_5_quality_04_broken_named_constant_finding_is_never_mined() -> None:
    defect = _defect(
        category="CODE-QUALITY",
        location="solution.py: total > 100 (used twice)",
        fix=(
            "Define a module-level constant, e.g. HIGH_VALUE_THRESHOLD = 100, and replace "
            "both literal 100 comparisons with it, per the explicit task requirement."
        ),
    )

    evidence = mine_trigger_evidence(defect, QUALITY_04_TASK, QUALITY_04_BROKEN)

    assert evidence == {}


# ==========================================================================
# 6. security-03-broken: weak randomness, no parameters at all
# ==========================================================================


def test_6_security_03_broken_weak_randomness_finding_is_never_mined() -> None:
    defect = _defect(
        category="SECURITY",
        location="solution.py: random.choice",
        fix=(
            "Use secrets.token_hex instead of the random module, which is not "
            "cryptographically secure for password-reset tokens."
        ),
    )

    evidence = mine_trigger_evidence(defect, SEC_03_TASK, SEC_03_BROKEN)

    assert evidence == {}


# ==========================================================================
# 7. edge_case-02-broken: genuine missing-path finding
# ==========================================================================


def test_7_edge_case_02_broken_missing_path_finding_is_never_mined() -> None:
    defect = _defect(
        location="solution.py: user[\"profile\"][\"email\"]",
        fix=(
            "Missing handling for an absent 'profile' or 'email' key: this raises "
            "KeyError instead of returning None, violating the 'without raising' "
            "requirement."
        ),
    )

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_BROKEN)

    assert evidence == {}


# ==========================================================================
# 8. security-04-broken: genuine no-validation finding
# ==========================================================================


def test_8_security_04_broken_no_validation_finding_is_never_mined() -> None:
    defect = _defect(
        category="SECURITY",
        location="solution.py: resolve_safe_fetch_target",
        fix=(
            "No validation of the resolved address at all; internal/private addresses "
            "are never rejected, allowing SSRF against internal services."
        ),
    )

    evidence = mine_trigger_evidence(defect, SEC_04_TASK, SEC_04_BROKEN)

    assert evidence == {}


# ==========================================================================
# 9. security-04-clean: explicitly out of scope for this prototype
# ==========================================================================


def test_9_security_04_clean_toctou_finding_is_never_mined() -> None:
    """The dominant historical complaint on this case ('validates all addresses but
    returns addresses[0]') is a factual/data-flow claim, not a declared-parameter-type
    contradiction, and this miner does not attempt it. `addresses[0]` also must never
    be mistaken for the numeric-zero vocabulary token -- it is a subscript, not a
    parenthesized example, and `addresses` is a local variable, not a declared
    parameter."""
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

    evidence = mine_trigger_evidence(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert evidence == {}


def test_9b_security_04_clean_paraphrased_guarantee_is_never_mined() -> None:
    """A paraphrase of the task's caller guarantee carries no declared-parameter literal
    at all, so it was never a candidate for this miner in the first place -- the
    excluded_by_clause route is out of scope for this prototype entirely."""
    defect = _defect(
        category="SECURITY",
        fix="This is actually handled correctly since the task states this is the contract.",
    )

    evidence = mine_trigger_evidence(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert evidence == {}


# ==========================================================================
# Additional narrow-miner safety pins
# ==========================================================================


def test_defect_with_no_free_text_fields_is_never_mined() -> None:
    defect = {"id": "C1", "category": "CORRECTNESS", "severity": "HIGH"}

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {}


def test_unparseable_code_snapshot_is_never_mined() -> None:
    defect = _defect(fix="Guard against user not being a dict (e.g., None)")

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, "def broken(:\n")

    assert evidence == {}


def test_lowercase_none_is_not_mistaken_for_the_python_literal() -> None:
    """Vocabulary matching is exact-token, not case-insensitive: 'none' in prose is not
    the Python literal None, and treating it as one would be a silent broadening of the
    closed vocabulary."""
    defect = _defect(fix="Guard against user having none of the expected keys.")

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {}


# ==========================================================================
# mine_return_value_evidence -- a second, independent miner
#
# Targets the OTHER edge_case-02-clean claim family (runs 55, 59, 62): the
# judge objects to `email if isinstance(email, str) else None`, asking for
# the raw value "regardless of type" instead -- which would violate the
# function's own `-> str | None` return annotation whenever email is present
# but not a string. This is a declared-RETURN-type contradiction
# (adjudication._adjudicate_return / rule "factual-premise"), a completely
# separate adjudication Fact from the parameter-type miner above. Wholly
# independent function; does not touch mine_trigger_evidence's rules at all.
# ==========================================================================

# Functions whose return-type ternary shape does NOT qualify, for the
# negative-control tests (F/G/H/I).
EDGE_02_RETURN_NOT_OPTIONAL = (
    "def get_user_email(user: dict) -> str:\n"
    '    profile = user.get("profile")\n'
    "    if not isinstance(profile, dict):\n"
    '        return ""\n'
    '    email = profile.get("email")\n'
    "    return email if isinstance(email, str) else None\n"
)
EDGE_02_RETURN_NO_IFEXP = (
    "def get_user_email(user: dict) -> str | None:\n"
    '    profile = user.get("profile")\n'
    "    if not isinstance(profile, dict):\n"
    "        return None\n"
    '    email = profile.get("email")\n'
    "    if isinstance(email, str):\n"
    "        return email\n"
    "    return None\n"
)
EDGE_02_RETURN_MISMATCHED_NAME = (
    "def get_user_email(user: dict) -> str | None:\n"
    '    profile = user.get("profile")\n'
    "    if not isinstance(profile, dict):\n"
    "        return None\n"
    '    email = profile.get("email")\n'
    '    other = profile.get("other")\n'
    "    return other if isinstance(email, str) else None\n"
)
EDGE_02_RETURN_ELSE_NOT_NONE = (
    "def get_user_email(user: dict) -> str:\n"
    '    profile = user.get("profile")\n'
    "    if not isinstance(profile, dict):\n"
    '        return ""\n'
    '    email = profile.get("email")\n'
    '    return email if isinstance(email, str) else ""\n'
)


def _return_defect(**overrides: object) -> dict:
    base: dict = {
        "id": "C1",
        "category": "CORRECTNESS",
        "severity": "HIGH",
        "location": "solution.py: email = profile.get(\"email\")",
        "fix": "change something",
    }
    base.update(overrides)
    return base


def test_r1_run_55_style_text_is_mined() -> None:
    defect = _return_defect(
        fix=(
            "Return the value of profile['email'] as-is when present, only returning "
            "None if the key or path is missing; do not filter based on the value's "
            "type (e.g., {'profile': {'email': 123}} should return 123, not None)."
        ),
    )

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {"minimal_trigger": "return=None"}


def test_r2_run_59_style_text_is_mined() -> None:
    defect = _return_defect(
        fix=(
            "Remove the isinstance(email, str) check and simply return "
            "profile.get('email') (or use .get() chaining) so that the actual value "
            "is returned whenever profile['email'] key exists, regardless of its "
            "type; only return None when profile or email key is truly absent, per "
            "the task requirement of returning None only if part of the path is "
            "missing."
        ),
    )

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {"minimal_trigger": "return=None"}


def test_r3_run_62_style_text_is_mined() -> None:
    defect = _return_defect(
        fix=(
            "Return the value found at user['profile']['email'] regardless of its "
            "type; only return None when the key/path itself is missing (e.g., use "
            "`return profile.get('email')` after confirming profile is a dict, "
            "without filtering on type)."
        ),
    )

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {"minimal_trigger": "return=None"}


def test_r4_emitted_evidence_shape_is_exact() -> None:
    """No stray keys, no extra fields -- exactly one key, exactly this value."""
    defect = _return_defect(fix="Return it regardless of its type.")

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {"minimal_trigger": "return=None"}
    assert list(evidence.keys()) == ["minimal_trigger"]


def test_r5_historical_texts_resolve_through_real_admissibility() -> None:
    """The existing, unmodified admissibility.decide() must independently confirm
    what this miner's evidence resolves to -- proving the miner's output is not
    merely shaped correctly but actually usable by the frozen adjudication path."""
    from engine.verification import admissibility

    historical_fixes = [
        (
            "Return the value of profile['email'] as-is when present, only returning "
            "None if the key or path is missing; do not filter based on the value's "
            "type (e.g., {'profile': {'email': 123}} should return 123, not None)."
        ),
        (
            "Remove the isinstance(email, str) check and simply return "
            "profile.get('email') so that the actual value is returned regardless of "
            "its type; only return None when profile or email key is truly absent."
        ),
        (
            "Return the value found at user['profile']['email'] regardless of its "
            "type; only return None when the key/path itself is missing, without "
            "filtering on type."
        ),
    ]
    for fix in historical_fixes:
        defect = _return_defect(fix=fix)
        evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)
        assert evidence == {"minimal_trigger": "return=None"}

        augmented = {**defect, **evidence}
        decision = admissibility.decide(augmented, EDGE_02_TASK, EDGE_02_CLEAN)
        assert decision.admissible is False
        assert decision.rule == "factual-premise"


def test_r6_return_type_not_optional_is_never_mined() -> None:
    """F: the declared return type doesn't admit None at all -- returning None would
    be a genuine violation, not an admitted one, so nothing may be mined."""
    defect = _return_defect(fix="Return it regardless of its type, without filtering.")

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_RETURN_NOT_OPTIONAL)

    assert evidence == {}


def test_r7_return_shape_without_ifexp_is_never_mined() -> None:
    """G: the same logic expressed as an if/else statement instead of a ternary
    IfExp -- the miner requires the exact expression shape, not the behavior."""
    defect = _return_defect(fix="Return it regardless of its type, without filtering.")

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_RETURN_NO_IFEXP)

    assert evidence == {}


def test_r8_mismatched_isinstance_name_is_never_mined() -> None:
    """H: the ternary's test checks one name but returns a different one -- exact
    name identity must hold, not "some isinstance check exists somewhere"."""
    defect = _return_defect(fix="Return it regardless of its type, without filtering.")

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_RETURN_MISMATCHED_NAME)

    assert evidence == {}


def test_r9_ifexp_else_branch_not_none_is_never_mined() -> None:
    """I: the else branch is some other fallback, not the literal None -- the whole
    point is that returning None is what the code does and what the annotation
    admits, so a non-None else branch is a different shape entirely."""
    defect = _return_defect(fix="Return it regardless of its type, without filtering.")

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_RETURN_ELSE_NOT_NONE)

    assert evidence == {}


def test_r10_generic_type_complaint_without_bounded_phrase_is_never_mined() -> None:
    """J: bare mentions of "type"/"isinstance"/"validation"/"defensive" must never
    match on their own -- only the specific, bounded objection phrases do."""
    for fix in (
        "There is a type issue here that should be fixed.",
        "This isinstance check looks defensive.",
        "Consider revisiting the validation logic for this field.",
        "The type of this value is not well documented.",
    ):
        defect = _return_defect(fix=fix)
        evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)
        assert evidence == {}, f"unexpectedly mined for: {fix!r}"


def test_r11_defect_with_no_free_text_is_never_mined() -> None:
    defect = {"id": "C1", "category": "CORRECTNESS", "severity": "HIGH"}

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {}


def test_r12_unparseable_code_snapshot_is_never_mined() -> None:
    defect = _return_defect(fix="Return it regardless of its type.")

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, "def broken(:\n")

    assert evidence == {}


# --- safety regressions: the four broken controls plus security-04-clean ---


def test_r_quality_04_broken_is_never_mined() -> None:
    defect = _return_defect(
        fix=(
            "Define a module-level constant, e.g. HIGH_VALUE_THRESHOLD = 100, and "
            "replace both literal 100 comparisons with it, per the explicit task "
            "requirement."
        ),
    )

    evidence = mine_return_value_evidence(defect, QUALITY_04_TASK, QUALITY_04_BROKEN)

    assert evidence == {}


def test_r_security_03_broken_is_never_mined() -> None:
    defect = _return_defect(
        fix="Use secrets.token_hex instead of the random module, which is not "
        "cryptographically secure for password-reset tokens.",
    )

    evidence = mine_return_value_evidence(defect, SEC_03_TASK, SEC_03_BROKEN)

    assert evidence == {}


def test_r_edge_case_02_broken_is_never_mined() -> None:
    defect = _return_defect(
        fix=(
            "Missing handling for an absent 'profile' or 'email' key: this raises "
            "KeyError instead of returning None."
        ),
    )

    evidence = mine_return_value_evidence(defect, EDGE_02_TASK, EDGE_02_BROKEN)

    assert evidence == {}


def test_r_security_04_broken_is_never_mined() -> None:
    defect = _return_defect(
        fix=(
            "No validation of the resolved address at all; internal/private "
            "addresses are never rejected, allowing SSRF against internal services."
        ),
    )

    evidence = mine_return_value_evidence(defect, SEC_04_TASK, SEC_04_BROKEN)

    assert evidence == {}


def test_r_security_04_clean_is_never_mined() -> None:
    defect = _return_defect(
        fix=(
            "The function validates ALL resolved addresses are public but then "
            "returns addresses[0], the first address from getaddrinfo, not "
            "necessarily the one that was validated in a TOCTOU/DNS-rebinding sense."
        ),
    )

    evidence = mine_return_value_evidence(defect, SEC_04_TASK, SEC_04_CLEAN)

    assert evidence == {}


def test_r_existing_parameter_miner_rules_are_unmodified() -> None:
    """The new miner must not weaken or broaden mine_trigger_evidence -- pin that
    its behavior on the canonical hit is byte-for-byte the same as before."""
    defect = _defect(
        location="solution.py: user.get(\"profile\")",
        fix=(
            "Guard against user not being a dict (e.g., None or other type) by "
            "checking isinstance(user, dict) before calling .get, to avoid "
            "AttributeError."
        ),
    )

    evidence = mine_trigger_evidence(defect, EDGE_02_TASK, EDGE_02_CLEAN)

    assert evidence == {"minimal_trigger": "user=None"}
