from typing import Any

from engine.verification.rubric import BLOCKING, CRITIC_KEYS, DEFECT_KEYS, DIMENSIONS, SEVERITIES


def enforce_critic_schema(critic: Any) -> list[str]:
    errs: list[str] = []

    if not isinstance(critic, dict):
        return [f"critic must be a JSON object, got {type(critic).__name__}"]

    defects = critic.get("defects")
    if not isinstance(defects, list):
        errs.append("defects: must be a list")
        defects = []
    for i, d in enumerate(defects):
        if not isinstance(d, dict):
            errs.append(f"defects[{i}]: must be an object")
            continue
        missing = DEFECT_KEYS - d.keys()
        if missing:
            errs.append(f"defects[{i}]: missing keys {sorted(missing)}")
        if d.get("severity") not in SEVERITIES:
            errs.append(f"defects[{i}].severity: must be one of {sorted(SEVERITIES)}")
        if d.get("category") not in DIMENSIONS:
            # Deliberate fail-closed, decided 2026-08-06 -- not an oversight.
            # A lens can honestly find an off-topic defect (observed:
            # security lens labeling a sort-order bug "LOGIC" instead of
            # "SECURITY", 8/8 runs on correctness-04-broken). Rejected two
            # alternatives: coercing the category to the lens's own fixed
            # value would silently overwrite what the model actually said;
            # widening DIMENSIONS would change eval/dataset.py's
            # category_accuracy scoring right after it was stabilized.
            # Every observed occurrence so far was redundantly caught by a
            # different lens at blocking severity, so this has cost
            # visibility, not accuracy. Revisit ONLY if a future run shows
            # an out-of-enum category as the ONLY lens catching a real
            # defect -- query eval_case_schema_failures for error_detail
            # LIKE '%.category:%' to check.
            errs.append(f"defects[{i}].category: must be one of {list(DIMENSIONS)}")

    verdict = critic.get("verdict")
    if verdict not in ("OK", "FAIL"):
        errs.append("verdict: must be 'OK' or 'FAIL'")
    else:
        has_blocking = any(
            isinstance(d, dict) and d.get("severity") in BLOCKING for d in defects
        )
        expected = "FAIL" if has_blocking else "OK"
        if verdict != expected:
            errs.append(f"verdict: is {verdict!r} but expected {expected!r} given the defects")

    stray = set(critic.keys()) - CRITIC_KEYS
    if stray:
        errs.append(f"unexpected top-level keys: {sorted(stray)}")

    return errs
