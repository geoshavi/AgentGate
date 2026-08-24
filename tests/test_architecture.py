"""Architecture protection: the Gateway must stay the only path to a live
provider. Three separate rules, each failing with the offending file and
which rule it broke, so a regression is diagnosable from the assertion
alone:

  Rule A: only runtime/ and providers/ may import a provider SDK directly.
  Rule B: only runtime/gateway.py may import anything under providers/, with
          NO exceptions -- nothing outside providers/ itself names that
          package at all.

          This rule previously carried two standing allowlist exceptions,
          both of which were symptoms of things living in the wrong place
          rather than genuine needs. Recording them because the reasoning
          that removed them is the reason the rule can now be absolute:

            (1) `any name from providers.base` was allowed because Message
                and GenerationResult are the argument/return types of
                gateway.generate(), so every caller needed them -- the
                Gateway's own public API forced callers across the very
                boundary this rule exists to protect. Fixed by moving those
                two types to engine/llm_types.py, a neutral leaf owned by
                neither side (Rule F keeps it a leaf). The Provider protocol
                stayed in providers/base.py; nothing outside providers/ and
                the Gateway needs it.
            (2) `providers.registry.DEFAULT_MODELS` was allowed because it
                is a plain dict of model-name strings that cannot call out.
                True, but it is configuration, not provider machinery, and
                its placement made api.py, cli.py, and orchestrator/engine.py
                import the provider package purely to read config. Fixed by
                moving it to engine/config.py.

          An allowlist was the right shape while exceptions existed: a
          blocklist (naming AnthropicProvider, build_provider, etc.) was
          tried first and missed `import engine.providers` reaching the same
          classes via attribute access. With zero exceptions the distinction
          is moot -- every import form is judged by module path alone, which
          subsumes both failure modes.
          Residual gap, acknowledged rather than silently ignored: a fully
          dynamic `importlib.import_module("engine.providers...")` has no
          import statement for AST to see at all. No static import scanner
          can close that; it would need a runtime import hook instead.
  Rule C: providers/ must not import runtime/ -- the dependency runs one
          way only (gateway -> provider). A cycle here would defeat the
          reason runtime/ lives outside orchestrator/ in the first place
          (so verification/ can import it without reaching into
          orchestrator/).
  Rule D: eval/ may only depend on verification/, runtime/, and state/
          (plus engine.config, needed everywhere, and stdlib/third-party).
          Everything else -- orchestrator/ (including agents/), providers/,
          api.py, cli.py, reporting/ -- is forbidden. This is
          stricter than "don't import providers/ or an SDK" (which Rule
          A/B already give eval/ for free by placement under src/engine/):
          it caught a real violation during development, where eval/runner.py
          imported write_files from orchestrator/agents/common.py. Fixed by
          giving eval/ its own minimal file-writer instead -- dataset file
          paths are hand-authored, not LLM output, so they don't need
          write_files()'s path-traversal guard in the first place.
  Rule E: verification/, runtime/, and state/ must never import eval/ --
          the dependency runs one way only (eval -> verification/runtime/
          state). Eval is a *client* of the review flow, not a dependency
          of it; those three packages must stay usable without eval/ ever
          being on the import path.
  Rule G: nothing under eval/, verification/, runtime/, state/ or
          orchestrator/ may import engine.codeagent or engine.debugagent, and
          neither agent package may reach providers/ or a provider SDK
          directly. Both agents are leaf *clients* of the verification system:
          they call run_verification and read the verdict, and nothing in the
          verified-by path may depend on them. If the thing being verified ever
          lands on the verifier's import path, the benchmark stops measuring
          what it claims to. Rule D already forbids both packages inside eval/
          for free (its allowlist names only eval/verification/runtime/state
          plus engine.config), so this rule's eval/ clause is redundant by
          construction and stated anyway -- the redundancy is what keeps the
          guarantee if that allowlist is ever widened.

          The rule also fixes the direction of the seam between the two agents:
          debugagent/ imports codeagent/ (the workspace, the policy, the tool
          registry, the session loop, the verification seam) and codeagent/
          must never import debugagent/. One-way, because the Coding Agent
          shipped first and every existing test of it must keep passing without
          knowing the Debug Agent exists.
  Rule F: engine/llm_types.py must import nothing from engine.* -- it holds
          the gateway <-> provider data contract precisely because both
          sides may import it, which also makes it the one module in the
          tree that every layer can reach. A single engine.* import there
          would turn it into a back-channel joining layers that Rules B-E
          otherwise keep apart (e.g. an import of engine.state would hand
          providers/ a path to the database). Keeping it a stdlib-only leaf
          is what makes it safe for everyone to depend on.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).parent.parent / "src" / "engine"

# Extend as real SDKs are added (openai, google.generativeai, ollama, ...).
PROVIDER_SDK_MODULES = {"anthropic"}

GATEWAY_FILE = SRC_ROOT / "runtime" / "gateway.py"
LLM_TYPES_FILE = SRC_ROOT / "llm_types.py"

# The leaf agent packages, and the packages that must never depend on them --
# see the Rule G docstring above.
AGENT_PACKAGES = ("codeagent", "debugagent")
VERIFIED_BY_PACKAGES = ("eval", "verification", "runtime", "state", "orchestrator")

# eval/'s allowed engine.* dependency surface -- see Rule D docstring above.
EVAL_ALLOWED_ENGINE_PACKAGES = {"engine.eval", "engine.verification", "engine.runtime", "engine.state"}
EVAL_ALLOWED_EXACT_MODULES = {"engine.config"}


def _iter_source_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def _relative(path: Path) -> str:
    return str(path.relative_to(SRC_ROOT.parent.parent))


def _imported_module_names(path: Path) -> list[str]:
    """Module names from `import x` / `from x import y`, found anywhere in
    the file (not just top-level statements), so an import hidden inside a
    function or method doesn't slip past this check.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _is_in_package(path: Path, package_dir: str) -> bool:
    return (SRC_ROOT / package_dir) in path.parents


def test_rule_a_only_runtime_and_providers_import_the_sdk_directly() -> None:
    violations = []
    for path in _iter_source_files():
        if _is_in_package(path, "runtime") or _is_in_package(path, "providers"):
            continue
        for name in _imported_module_names(path):
            if name in PROVIDER_SDK_MODULES or any(
                name.startswith(f"{sdk}.") for sdk in PROVIDER_SDK_MODULES
            ):
                violations.append(f"{_relative(path)}: imports {name!r} (Rule A)")
    assert not violations, "Provider SDK imported outside runtime/ and providers/:\n" + "\n".join(
        violations
    )


def test_rule_b_only_gateway_imports_a_provider_implementation() -> None:
    violations = []
    for path in _iter_source_files():
        if _is_in_package(path, "providers") or path == GATEWAY_FILE:
            continue

        # No exceptions: judged by module path alone, which covers both
        # `import engine.providers[.X]` (attribute access to everything
        # inside) and `from engine.providers.X import Y` (any name). See the
        # Rule B docstring for the two exceptions this used to carry and
        # what replaced them.
        for name in _imported_module_names(path):
            if name == "engine.providers" or name.startswith("engine.providers."):
                violations.append(f"{_relative(path)}: imports {name!r} (Rule B)")

    assert not violations, (
        "Only runtime/gateway.py may import anything under providers/ -- everything else "
        "must go through the Gateway (Message/GenerationResult live in engine.llm_types, "
        "DEFAULT_MODELS in engine.config):\n" + "\n".join(violations)
    )


def test_rule_c_providers_does_not_import_runtime() -> None:
    violations = []
    for path in _iter_source_files():
        if not _is_in_package(path, "providers"):
            continue
        for name in _imported_module_names(path):
            if name == "engine.runtime" or name.startswith("engine.runtime."):
                violations.append(f"{_relative(path)}: imports {name!r} (Rule C)")
    assert not violations, (
        "providers/ must not import runtime/ -- the dependency runs one way only "
        "(gateway -> provider):\n" + "\n".join(violations)
    )


def test_rule_d_eval_only_depends_on_verification_runtime_state() -> None:
    violations = []
    for path in _iter_source_files():
        if not _is_in_package(path, "eval"):
            continue
        for name in _imported_module_names(path):
            if not name.startswith("engine."):
                continue
            if name in EVAL_ALLOWED_EXACT_MODULES:
                continue
            if any(name == pkg or name.startswith(f"{pkg}.") for pkg in EVAL_ALLOWED_ENGINE_PACKAGES):
                continue
            violations.append(f"{_relative(path)}: imports {name!r} (Rule D)")
    assert not violations, (
        "eval/ may only depend on verification/, runtime/, and state/ (plus engine.config) -- "
        "orchestrator/, providers/, api.py, cli.py, reporting/, routing/ are all forbidden:\n"
        + "\n".join(violations)
    )


def test_rule_e_eval_is_never_imported_by_verification_runtime_state() -> None:
    violations = []
    for path in _iter_source_files():
        if _is_in_package(path, "eval"):
            continue
        if not (
            _is_in_package(path, "verification")
            or _is_in_package(path, "runtime")
            or _is_in_package(path, "state")
        ):
            continue
        for name in _imported_module_names(path):
            if name == "engine.eval" or name.startswith("engine.eval."):
                violations.append(f"{_relative(path)}: imports {name!r} (Rule E)")
    assert not violations, (
        "verification/, runtime/, and state/ must never import eval/ -- the dependency runs "
        "one way only (eval -> verification/runtime/state):\n" + "\n".join(violations)
    )


def test_rule_f_llm_types_stays_a_leaf() -> None:
    # Asserted rather than skipped-if-missing: if this file is renamed or
    # removed, the rule must fail loudly rather than silently pass by
    # scanning nothing.
    assert LLM_TYPES_FILE.is_file(), (
        f"{_relative(LLM_TYPES_FILE)} is missing -- it holds the gateway <-> provider data "
        "contract that lets Rule B stay exception-free. If it moved, update LLM_TYPES_FILE."
    )
    violations = [
        f"{_relative(LLM_TYPES_FILE)}: imports {name!r} (Rule F)"
        for name in _imported_module_names(LLM_TYPES_FILE)
        if name == "engine" or name.startswith("engine.")
    ]
    assert not violations, (
        "engine/llm_types.py must import nothing from engine.* -- every layer is allowed to "
        "import it, so an engine.* import there becomes a back-channel between layers that "
        "Rules B-E keep apart:\n" + "\n".join(violations)
    )


def test_rule_g_the_agents_are_leaf_clients() -> None:
    violations = []
    for path in _iter_source_files():
        if any(_is_in_package(path, agent) for agent in AGENT_PACKAGES):
            continue
        if not any(_is_in_package(path, pkg) for pkg in VERIFIED_BY_PACKAGES):
            continue
        for name in _imported_module_names(path):
            for agent in AGENT_PACKAGES:
                if name == f"engine.{agent}" or name.startswith(f"engine.{agent}."):
                    violations.append(f"{_relative(path)}: imports {name!r} (Rule G)")
    assert not violations, (
        "eval/, verification/, runtime/, state/ and orchestrator/ must never import "
        "codeagent/ or debugagent/ -- both agents are clients of the verification "
        "system, never dependencies of it. If the thing being verified is on the "
        "verifier's import path, the benchmark stops measuring what it claims to:\n"
        + "\n".join(violations)
    )


def test_rule_g_the_agent_seam_runs_one_way() -> None:
    """debugagent/ may import codeagent/; codeagent/ may never import debugagent/."""
    violations = [
        f"{_relative(path)}: imports {name!r} (Rule G)"
        for path in _iter_source_files()
        if _is_in_package(path, "codeagent")
        for name in _imported_module_names(path)
        if name == "engine.debugagent" or name.startswith("engine.debugagent.")
    ]
    assert not violations, (
        "codeagent/ must never import debugagent/ -- the seam runs one way, which is "
        "what lets every Coding Agent test keep passing without knowing the Debug "
        "Agent exists:\n" + "\n".join(violations)
    )


def test_rule_g_the_agents_do_not_reach_a_provider() -> None:
    # Rules A and B already cover this by placement; asserted separately so a
    # failure names the agent package directly instead of surfacing as a
    # generic Rule A/B violation, and so the guarantee survives any future
    # relaxation of those rules' scope.
    violations = []
    for path in _iter_source_files():
        if not any(_is_in_package(path, agent) for agent in AGENT_PACKAGES):
            continue
        for name in _imported_module_names(path):
            if name == "engine.providers" or name.startswith("engine.providers."):
                violations.append(f"{_relative(path)}: imports {name!r} (Rule G)")
            if name in PROVIDER_SDK_MODULES or any(
                name.startswith(f"{sdk}.") for sdk in PROVIDER_SDK_MODULES
            ):
                violations.append(f"{_relative(path)}: imports {name!r} (Rule G)")
    assert not violations, (
        "codeagent/ and debugagent/ must reach a model only through runtime/gateway.py, "
        "never through providers/ or a provider SDK directly:\n" + "\n".join(violations)
    )
