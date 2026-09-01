"""Budget enforcement for LLM calls: token and spend limits are checked
BEFORE every call, not only recorded afterward. Cost is always derived from
PRICE_TABLE -- callers never supply a dollar amount directly.

All amounts are Decimal. Never construct a Decimal from a float -- price
table entries and any literal amounts must be string literals
(``Decimal("0.000003")``, never ``Decimal(0.000003)``) or built from
integers, which are exact. Running totals accumulate at full precision;
rounding (ROUND_HALF_UP) happens only in ``round_for_display``, never during
accumulation or storage.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# USD per token. Sourced from https://platform.claude.com/docs/en/about-claude/pricing
# on 2026-08-04, reverified 2026-09-01. "cache_creation" uses the 5-minute
# cache-write rate (the recommended default per that page); the 1-hour
# write rate ($4/MTok for Sonnet 5, $2/MTok for Haiku 4.5) isn't
# represented separately since nothing in this codebase sets cache_control
# yet -- both cache columns are always 0 in practice today. If 1-hour
# caching gets adopted, this table needs a second cache-write column and
# Gateway/GenerationResult need to start distinguishing which duration was
# used.
#
# Claude Sonnet 5 was launched with time-boxed introductory pricing ($2/$10
# per MTok input/output) that was scheduled to rise to $3/$15 on
# 2026-09-01. Per the pricing page's "claude-sonnet-5-introductory-pricing"
# note as of the 2026-09-01 reverification, that increase will not occur --
# $2/$10 is now the standard, permanent rate. The values below are
# unchanged from the 2026-08-04 sourcing.
PRICE_TABLE: dict[str, dict[str, Decimal]] = {
    "claude-sonnet-5": {
        "input": Decimal("0.000002"),
        "output": Decimal("0.00001"),
        "cache_read": Decimal("0.0000002"),
        "cache_creation": Decimal("0.0000025"),
    },
    "claude-haiku-4-5-20251001": {
        "input": Decimal("0.000001"),
        "output": Decimal("0.000005"),
        "cache_read": Decimal("0.0000001"),
        "cache_creation": Decimal("0.00000125"),
    },
}

DISPLAY_QUANTUM = Decimal("0.000001")


class BudgetExceededError(Exception):
    pass


class UnknownModelPricingError(Exception):
    pass


def estimate_cost(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> Decimal:
    try:
        prices = PRICE_TABLE[model]
    except KeyError:
        raise UnknownModelPricingError(
            f"no price table entry for model {model!r}; add one to PRICE_TABLE before using it"
        ) from None
    return (
        Decimal(input_tokens) * prices["input"]
        + Decimal(output_tokens) * prices["output"]
        + Decimal(cache_read_tokens) * prices["cache_read"]
        + Decimal(cache_creation_tokens) * prices["cache_creation"]
    )


def round_for_display(amount: Decimal) -> Decimal:
    return amount.quantize(DISPLAY_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass
class BudgetController:
    """Tracks cumulative usage for one run and enforces limits before each
    call. Not thread-safe -- fine while execution is sequential; revisit if
    a future parallel-execution phase shares one controller across
    concurrently running calls.
    """

    max_tokens: int
    planned_budget: Decimal
    spent_tokens: int = field(default=0, init=False)
    spent_amount: Decimal = field(default=Decimal(0), init=False)

    def check_before_call(self, model: str, max_tokens: int) -> None:
        if self.spent_tokens + max_tokens > self.max_tokens:
            raise BudgetExceededError(
                f"token budget would be exceeded: {self.spent_tokens} spent + "
                f"{max_tokens} requested > {self.max_tokens} max"
            )
        # Worst-case estimate: only the requested output cap is known ahead
        # of the call, so input/cache costs aren't part of the pre-flight
        # check -- they're smaller in practice and unknowable without
        # tokenizing the prompt.
        worst_case = estimate_cost(model, output_tokens=max_tokens)
        if self.spent_amount + worst_case > self.planned_budget:
            raise BudgetExceededError(
                f"spend budget would be exceeded: {self.spent_amount} spent + "
                f"{worst_case} worst-case > {self.planned_budget} planned"
            )

    def record_usage(
        self,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> Decimal:
        self.spent_tokens += input_tokens + output_tokens
        spend = estimate_cost(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
        self.spent_amount += spend
        return spend
