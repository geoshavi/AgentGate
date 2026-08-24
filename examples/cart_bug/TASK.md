# Debug Agent demo fixture: cart_bug

## Reported bug

    Adding nothing to the cart and asking for a total crashes instead of
    returning the shipping charge. Customers hitting the empty basket page see
    a 500. Totals for non-empty carts look correct.

That is the whole report — a symptom, as a user would describe it. It names no
file, no function and no patch, because a fixture that hands over the fix does
not exercise D2's diagnosis at all.

## Commands

Reproduction (frozen — this is what "the bug" means):

    python -m pytest -q tests/test_cart.py::test_empty_cart_is_shipping_only

Plain `pytest -q` — no special flags. The evidence layer reads pytest's own
failure-location lines (`cart.py:24: ValueError`, `cart.py:33: in cart_total`)
as well as CPython's `File "...", line N, in fn` form, so the command a person
would actually type is the command the Debug Agent freezes.

Regression suite:

    python -m pytest -q

## Why this fixture

The failure is a `ValueError` from `min()` on an empty sequence, and the
traceback points at the line that raised. That line is **not** where the fix
belongs, which is the point: the guard has to go where the empty case is first
reachable, not where it happens to blow up.

There are three passing tests besides the targeted one, and they are what make
the full-suite gate mean something. A change that simply makes the discount
disappear turns the reported bug green and breaks
`test_bulk_discount_applies_to_the_cheapest_item` — a targeted-only gate would
report that as a fix. Verified:

| Change | Targeted repro | Full suite | Proof |
| --- | --- | --- | --- |
| Guard the empty case before the discount is computed | passes | passes | **PROVEN** |
| Make the discount unconditionally zero | passes | **fails** | UNPROVEN |
| No change | fails | fails | UNPROVEN |

## Running it

In Windows PowerShell, against a COPY — the Debug Agent edits in place:

```powershell
Copy-Item -Recurse examples\cart_bug "$env:TEMP\cart_bug"

engine debug "Adding nothing to the cart and asking for a total crashes instead of returning the shipping charge." `
  --workspace "$env:TEMP\cart_bug" `
  --repro=python --repro=-m --repro=pytest --repro=-q `
  '--repro=tests/test_cart.py::test_empty_cart_is_shipping_only' `
  --budget 0.25
```

`--repro` is one argv token per flag — there is no shell in this path, so
nothing is word-split or interpreted. The `--flag=value` spelling is required
for `-m` and `-q`, which argparse would otherwise read as options; using it for
every token means one rule rather than two. The token carrying `::` is
single-quoted so PowerShell passes it through untouched.

The regression suite defaults to `python -m pytest -q`, so `--suite` is only
needed to override it. Expected result: **PASSED**, exit 0. See
[`docs/debug-agent.md`](../../docs/debug-agent.md).

The fixture is committed in its **broken** state. `python -m pytest -q` inside
it reports `1 failed, 3 passed`; if it does not, the fixture has been edited and
no longer proves anything.
