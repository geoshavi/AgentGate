"""The evaluation benchmark dataset: 20 tasks, each with a broken and a
clean version, spanning 4 benchmark categories (correctness, security,
quality, edge_case) -- 40 total cases.

The benchmark's own category taxonomy (correctness/security/quality/
edge_case) is intentionally separate from ``expected_defect_category``,
which must be one of the three dimensions the judge schema actually
validates against (verification/rubric.py's DIMENSIONS: CORRECTNESS,
SECURITY, CODE-QUALITY). edge_case tasks are all correctness-flavored bugs
at input/data boundaries -- there is no fourth judge dimension for "edge
case", so every edge_case task's expected_defect_category is CORRECTNESS.

Every snippet (broken and clean) is written to be ruff- and mypy-clean on
its own merits: broken versions carry a genuine semantic/security/
structural defect invisible to static linting, never a lint or type error.
If a snippet tripped ruff or mypy, verdict.gate() would return UNVERIFIED
for reasons unrelated to the judge, contaminating what this benchmark
measures. None of the snippets include test_*.py files, so the pytest gate
auto-passes ("no test files present") for every case -- automated_results
should always pass, and the only source of UNVERIFIED for "broken" cases
should be genuine judge-detected defects.

Deliberately mixes obvious anchor cases (SQL injection, mutable default
argument) with subtler ones the judge lens prompts don't name explicitly
(weak randomness for tokens, SSRF, timing-attack comparison, Unicode
truncation, non-atomic increment) so the benchmark tests generalization,
not prompt-keyword matching.
"""

from dataclasses import dataclass, replace

BENCHMARK_NAME = "engine-review-benchmark"
BENCHMARK_VERSION = "v2"
DATASET_VERSION = "v6"

# Benchmark v1 remains constructible from this module -- see TASKS_V1 / CASES_V1 at the
# bottom, which hold the pre-v2 form of every task v2 changed. Runs recorded under
# benchmark_version v1 / dataset_version v3 are not comparable with v2 runs: v2 restates
# six task specifications, repairs three fixtures, and corrects one expected category.
BENCHMARK_V1_VERSION = "v1"
BENCHMARK_V1_DATASET_VERSION = "v3"

CATEGORIES = ("correctness", "security", "quality", "edge_case")
# The only three dimensions the judge schema (verification/rubric.py) accepts.
JUDGE_DIMENSIONS = ("CORRECTNESS", "SECURITY", "CODE-QUALITY")


@dataclass(frozen=True)
class EvalCase:
    eval_case_id: str
    category: str
    task_text: str
    files: dict[str, str]
    expected_verdict: str  # "OK" | "UNVERIFIED"
    expected_defect_category: str | None  # one of JUDGE_DIMENSIONS, or None for clean cases


@dataclass(frozen=True)
class EvalTask:
    task_id: str
    category: str
    task_text: str
    expected_defect_category: str
    broken_files: dict[str, str]
    clean_files: dict[str, str]


TASKS: list[EvalTask] = [
    # ---------------------------------------------------------------- correctness
    EvalTask(
        task_id="correctness-01",
        category="correctness",
        task_text=(
            "Implement paginate(items, page, page_size) using 1-indexed pages "
            "(page=1 is the first page) that returns the correct slice of items for that page."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def paginate(items: list[int], page: int, page_size: int) -> list[int]:\n"
                "    if page < 1 or page_size < 1:\n"
                "        raise ValueError(\"page and page_size must be positive\")\n"
                "    start = page * page_size\n"
                "    end = start + page_size\n"
                "    return items[start:end]\n"
            )
        },
        clean_files={
            "solution.py": (
                "def paginate(items: list[int], page: int, page_size: int) -> list[int]:\n"
                "    if page < 1 or page_size < 1:\n"
                "        raise ValueError(\"page and page_size must be positive\")\n"
                "    start = (page - 1) * page_size\n"
                "    end = start + page_size\n"
                "    return items[start:end]\n"
            )
        },
    ),
    EvalTask(
        task_id="correctness-02",
        category="correctness",
        task_text=(
            "Implement is_close_enough(a, b) -> bool for comparing currency amounts: "
            "return True when the two values differ by less than 0.01, and False "
            "otherwise. A difference of exactly 0.01 is not close enough."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def is_close_enough(a: float, b: float) -> bool:\n"
                "    return a == b\n"
            )
        },
        clean_files={
            "solution.py": (
                "from decimal import Decimal\n\n\n"
                "def is_close_enough(a: float, b: float) -> bool:\n"
                "    diff = abs(Decimal(str(a)) - Decimal(str(b)))\n"
                "    return diff < Decimal(\"0.01\")\n"
            )
        },
    ),
    EvalTask(
        task_id="correctness-03",
        category="correctness",
        task_text=(
            "Implement can_edit(is_admin, is_owner, is_archived) -> bool: a user can edit "
            "if (they are an admin OR the owner) AND the resource is not archived."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def can_edit(is_admin: bool, is_owner: bool, is_archived: bool) -> bool:\n"
                "    return is_admin or is_owner and not is_archived\n"
            )
        },
        clean_files={
            "solution.py": (
                "def can_edit(is_admin: bool, is_owner: bool, is_archived: bool) -> bool:\n"
                "    return (is_admin or is_owner) and not is_archived\n"
            )
        },
    ),
    EvalTask(
        task_id="correctness-04",
        category="correctness",
        task_text=(
            "Implement top_n_by_score(items, n) -> list returning the n items with the "
            "HIGHEST score, ordered from highest to lowest. items is a list of (name, score) pairs."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def top_n_by_score(items: list[tuple[str, int]], n: int) -> list[tuple[str, int]]:\n"
                "    return sorted(items, key=lambda x: x[1])[:n]\n"
            )
        },
        clean_files={
            "solution.py": (
                "def top_n_by_score(items: list[tuple[str, int]], n: int) -> list[tuple[str, int]]:\n"
                "    return sorted(items, key=lambda x: x[1], reverse=True)[:n]\n"
            )
        },
    ),
    EvalTask(
        task_id="correctness-05",
        category="correctness",
        task_text=(
            "Implement running_average(nums) -> list[float] returning the cumulative "
            "running average at each index i (the average of nums[0..i])."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def running_average(nums: list[float]) -> list[float]:\n"
                "    result = []\n"
                "    for i, n in enumerate(nums, start=1):\n"
                "        total = n\n"
                "        result.append(total / i)\n"
                "    return result\n"
            )
        },
        clean_files={
            "solution.py": (
                "def running_average(nums: list[float]) -> list[float]:\n"
                "    result = []\n"
                "    total = 0.0\n"
                "    for i, n in enumerate(nums, start=1):\n"
                "        total += n\n"
                "        result.append(total / i)\n"
                "    return result\n"
            )
        },
    ),
    # ------------------------------------------------------------------- security
    EvalTask(
        task_id="security-01",
        category="security",
        task_text=(
            "Implement get_user_by_email(conn, email) that queries the users table for a "
            "matching email and returns the row."
        ),
        expected_defect_category="SECURITY",
        broken_files={
            "solution.py": (
                "import sqlite3\n\n\n"
                "def get_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:\n"
                "    cursor = conn.execute(f\"SELECT * FROM users WHERE email = '{email}'\")\n"
                "    return cursor.fetchone()\n"
            )
        },
        clean_files={
            "solution.py": (
                "import sqlite3\n\n\n"
                "def get_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:\n"
                "    cursor = conn.execute(\"SELECT * FROM users WHERE email = ?\", (email,))\n"
                "    return cursor.fetchone()\n"
            )
        },
    ),
    EvalTask(
        task_id="security-02",
        category="security",
        task_text=(
            "Implement convert_to_png(filename) that converts an existing image in a fixed "
            "application-owned working directory to filename + '.png' in that directory, "
            "using a trusted external image converter. filename is untrusted: accept only "
            "ASCII basenames matching [A-Za-z0-9][A-Za-z0-9_.-]* with no '..' substring, and "
            "reject anything else with ValueError before invoking any process -- no directory "
            "paths, leading options, whitespace, shell metacharacters, or other special "
            "syntax. Invoke the converter through a fixed absolute executable path with the "
            "input and output as separate literal filename arguments and no shell evaluation; "
            "report a conversion failure to the caller without retrying through a shell."
        ),
        expected_defect_category="SECURITY",
        broken_files={
            "solution.py": (
                "import subprocess\n\n\n"
                "def convert_to_png(filename: str) -> None:\n"
                "    subprocess.run(f\"convert {filename} {filename}.png\", shell=True, check=True)\n"
            )
        },
        clean_files={
            "solution.py": (
                "import re\n"
                "import subprocess\n\n"
                "_CONVERTER_PATH = \"/usr/bin/convert\"\n"
                "_WORKING_DIR = \"/srv/app/images\"\n"
                "_SAFE_FILENAME = re.compile(r\"[A-Za-z0-9][A-Za-z0-9_.-]*\")\n\n\n"
                "def convert_to_png(filename: str) -> None:\n"
                "    if \"..\" in filename or _SAFE_FILENAME.fullmatch(filename) is None:\n"
                "        raise ValueError(f\"invalid filename: {filename!r}\")\n"
                "    try:\n"
                "        subprocess.run(\n"
                "            [_CONVERTER_PATH, filename, f\"{filename}.png\"],\n"
                "            cwd=_WORKING_DIR,\n"
                "            check=True,\n"
                "        )\n"
                "    except subprocess.CalledProcessError as exc:\n"
                "        raise RuntimeError(f\"image conversion failed for {filename!r}\") from exc\n"
            )
        },
    ),
    EvalTask(
        task_id="security-03",
        category="security",
        task_text=(
            "Implement generate_reset_token() -> str returning a random 32-character hex "
            "token for password-reset links."
        ),
        expected_defect_category="SECURITY",
        broken_files={
            "solution.py": (
                "import random\n\n\n"
                "def generate_reset_token() -> str:\n"
                "    return \"\".join(random.choice(\"0123456789abcdef\") for _ in range(32))\n"
            )
        },
        clean_files={
            "solution.py": (
                "import secrets\n\n\n"
                "def generate_reset_token() -> str:\n"
                "    return secrets.token_hex(16)\n"
            )
        },
    ),
    EvalTask(
        task_id="security-04",
        category="security",
        task_text=(
            "Implement resolve_safe_fetch_target(host) -> str | None used to guard a "
            "URL-preview feature against fetching internal/private network addresses (SSRF). "
            "Return the network address the fetch must connect to, or None when the host has "
            "no safe address. The caller connects to the address you return and does not look "
            "the host up again, so the address you return must be one you checked."
        ),
        expected_defect_category="SECURITY",
        broken_files={
            "solution.py": (
                "import socket\n\n\n"
                "def resolve_safe_fetch_target(host: str) -> str | None:\n"
                "    return socket.gethostbyname(host)\n"
            )
        },
        clean_files={
            "solution.py": (
                "import ipaddress\n"
                "import socket\n\n\n"
                "def _is_public(addr: str) -> bool:\n"
                "    ip = ipaddress.ip_address(addr)\n"
                "    return not (\n"
                "        ip.is_private\n"
                "        or ip.is_loopback\n"
                "        or ip.is_link_local\n"
                "        or ip.is_reserved\n"
                "        or ip.is_multicast\n"
                "        or ip.is_unspecified\n"
                "    )\n\n\n"
                "def resolve_safe_fetch_target(host: str) -> str | None:\n"
                "    try:\n"
                "        infos = socket.getaddrinfo(host, None)\n"
                "    except (OSError, ValueError):\n"
                "        return None\n"
                "    addresses = [str(info[4][0]) for info in infos]\n"
                "    if not addresses:\n"
                "        return None\n"
                "    try:\n"
                "        if not all(_is_public(addr) for addr in addresses):\n"
                "            return None\n"
                "    except ValueError:\n"
                "        return None\n"
                "    return addresses[0]\n"
            )
        },
    ),
    EvalTask(
        task_id="security-05",
        category="security",
        task_text=(
            "Implement verify_signature(expected, provided) -> bool that securely "
            "compares two pre-computed signature strings for equality, guarding "
            "against timing attacks."
        ),
        expected_defect_category="SECURITY",
        broken_files={
            "solution.py": (
                "def verify_signature(expected: str, provided: str) -> bool:\n"
                "    return expected == provided\n"
            )
        },
        clean_files={
            "solution.py": (
                "import hmac\n\n\n"
                "def verify_signature(expected: str, provided: str) -> bool:\n"
                "    return hmac.compare_digest(expected, provided)\n"
            )
        },
    ),
    # -------------------------------------------------------------------- quality
    EvalTask(
        task_id="quality-01",
        category="quality",
        task_text=(
            "Implement build_leaderboard(matches) where matches is a list of (player, points) "
            "tuples: total each player's points and return one row per player as "
            "{'rank': int, 'player': str, 'points': int}, ordered by total points descending "
            "with ties broken by player name ascending, ranks starting at 1. Express that "
            "ordering rule in exactly one place: it must not be restated anywhere else in the "
            "module."
        ),
        expected_defect_category="CODE-QUALITY",
        broken_files={
            "solution.py": (
                "def build_leaderboard(matches: list[tuple[str, int]]) -> list[dict[str, object]]:\n"
                "    totals: dict[str, int] = {}\n"
                "    for player, points in matches:\n"
                "        totals[player] = totals.get(player, 0) + points\n"
                "    ordered = sorted(totals, key=lambda name: (-totals[name], name))\n"
                "    ranks = {player: rank for rank, player in enumerate(ordered, start=1)}\n"
                "    rows: list[dict[str, object]] = []\n"
                "    for player in sorted(totals, key=lambda name: (-totals[name], name)):\n"
                "        rows.append({\"rank\": ranks[player], \"player\": player, \"points\": totals[player]})\n"
                "    return rows\n"
            )
        },
        clean_files={
            "solution.py": (
                "def _tally_by_player(matches: list[tuple[str, int]]) -> dict[str, int]:\n"
                "    totals: dict[str, int] = {}\n"
                "    for player, points in matches:\n"
                "        totals[player] = totals.get(player, 0) + points\n"
                "    return totals\n\n\n"
                "def _rank_order(totals: dict[str, int]) -> list[str]:\n"
                "    return sorted(totals, key=lambda name: (-totals[name], name))\n\n\n"
                "def build_leaderboard(matches: list[tuple[str, int]]) -> list[dict[str, object]]:\n"
                "    totals = _tally_by_player(matches)\n"
                "    return [\n"
                "        {\"rank\": rank, \"player\": player, \"points\": totals[player]}\n"
                "        for rank, player in enumerate(_rank_order(totals), start=1)\n"
                "    ]\n"
            )
        },
    ),
    EvalTask(
        task_id="quality-02",
        category="quality",
        task_text=(
            "Implement validate_signup(email, age) and validate_profile_update(email, age). "
            "Both apply the same rule: the email must have a non-empty part before '@', and "
            "after '@' a domain containing a '.' with non-empty text on both sides of it; the "
            "age must be between 13 and 120 inclusive. Define that rule once, in a single "
            "shared implementation both functions call, so the two entry points cannot drift "
            "apart."
        ),
        expected_defect_category="CODE-QUALITY",
        broken_files={
            "solution.py": (
                "def validate_signup(email: str, age: int) -> bool:\n"
                "    local, sep, domain = email.partition(\"@\")\n"
                "    if not sep or not local:\n"
                "        return False\n"
                "    domain_prefix, dot, tld = domain.rpartition(\".\")\n"
                "    if not dot or not domain_prefix or not tld:\n"
                "        return False\n"
                "    return 13 <= age <= 120\n\n\n"
                "def validate_profile_update(email: str, age: int) -> bool:\n"
                "    local, sep, domain = email.partition(\"@\")\n"
                "    if not sep or not local:\n"
                "        return False\n"
                "    domain_prefix, dot, tld = domain.rpartition(\".\")\n"
                "    if not dot or not domain_prefix or not tld:\n"
                "        return False\n"
                "    return 13 <= age <= 120\n"
            )
        },
        clean_files={
            "solution.py": (
                "MIN_AGE = 13\n"
                "MAX_AGE = 120\n\n\n"
                "def _is_valid_email_and_age(email: str, age: int) -> bool:\n"
                "    local, sep, domain = email.partition(\"@\")\n"
                "    if not sep or not local:\n"
                "        return False\n"
                "    domain_prefix, dot, tld = domain.rpartition(\".\")\n"
                "    if not dot or not domain_prefix or not tld:\n"
                "        return False\n"
                "    return MIN_AGE <= age <= MAX_AGE\n\n\n"
                "def validate_signup(email: str, age: int) -> bool:\n"
                "    return _is_valid_email_and_age(email, age)\n\n\n"
                "def validate_profile_update(email: str, age: int) -> bool:\n"
                "    return _is_valid_email_and_age(email, age)\n"
            )
        },
    ),
    EvalTask(
        task_id="quality-03",
        category="quality",
        task_text=(
            "Implement get_or_create_user(users, user_id), using exactly that name: return "
            "the existing user dict from the users-by-id dict if present, otherwise create a "
            "new default user record, store it under user_id, and return it. Expose the "
            "operation under that one name, and build the default record in exactly one "
            "place, so there is a single definition of what a new user starts out as."
        ),
        expected_defect_category="CODE-QUALITY",
        broken_files={
            "solution.py": (
                "DEFAULT_USER_NAME = \"New User\"\n\n\n"
                "def create_user(users: dict[int, dict[str, str]], user_id: int) -> dict[str, str]:\n"
                "    new_user = {\"name\": DEFAULT_USER_NAME}\n"
                "    users[user_id] = new_user\n"
                "    return new_user\n\n\n"
                "def get_user(users: dict[int, dict[str, str]], user_id: int) -> dict[str, str]:\n"
                "    if user_id in users:\n"
                "        return users[user_id]\n"
                "    new_user = {\"name\": DEFAULT_USER_NAME}\n"
                "    users[user_id] = new_user\n"
                "    return new_user\n"
            )
        },
        clean_files={
            "solution.py": (
                "DEFAULT_USER_NAME = \"New User\"\n\n\n"
                "def get_or_create_user(users: dict[int, dict[str, str]], user_id: int) -> dict[str, str]:\n"
                "    if user_id in users:\n"
                "        return users[user_id]\n"
                "    new_user = {\"name\": DEFAULT_USER_NAME}\n"
                "    users[user_id] = new_user\n"
                "    return new_user\n"
            )
        },
    ),
    EvalTask(
        task_id="quality-04",
        category="quality",
        task_text=(
            "Implement classify_order(total, is_member, has_coupon, in_stock) -> str. Return "
            "'rejected' when not in_stock. Otherwise an order is high-value when total is "
            "strictly greater than 100, and the tier is: members with a coupon get "
            "'vip_discount' when high-value and 'member_coupon_discount' otherwise; members "
            "without a coupon get 'member_discount' when high-value and 'member_standard' "
            "otherwise; non-members get 'coupon_discount' with a coupon and 'standard' "
            "without. Define the high-value threshold once as a single named constant."
        ),
        expected_defect_category="CODE-QUALITY",
        broken_files={
            "solution.py": (
                "def classify_order(total: float, is_member: bool, has_coupon: bool, in_stock: bool) -> str:\n"
                "    if in_stock:\n"
                "        if is_member:\n"
                "            if has_coupon:\n"
                "                if total > 100:\n"
                "                    return \"vip_discount\"\n"
                "                else:\n"
                "                    return \"member_coupon_discount\"\n"
                "            else:\n"
                "                if total > 100:\n"
                "                    return \"member_discount\"\n"
                "                else:\n"
                "                    return \"member_standard\"\n"
                "        else:\n"
                "            if has_coupon:\n"
                "                return \"coupon_discount\"\n"
                "            else:\n"
                "                return \"standard\"\n"
                "    else:\n"
                "        return \"rejected\"\n"
            )
        },
        clean_files={
            "solution.py": (
                "HIGH_VALUE_THRESHOLD = 100\n\n\n"
                "def classify_order(total: float, is_member: bool, has_coupon: bool, in_stock: bool) -> str:\n"
                "    if not in_stock:\n"
                "        return \"rejected\"\n"
                "    if is_member and has_coupon and total > HIGH_VALUE_THRESHOLD:\n"
                "        return \"vip_discount\"\n"
                "    if is_member and has_coupon:\n"
                "        return \"member_coupon_discount\"\n"
                "    if is_member and total > HIGH_VALUE_THRESHOLD:\n"
                "        return \"member_discount\"\n"
                "    if is_member:\n"
                "        return \"member_standard\"\n"
                "    if has_coupon:\n"
                "        return \"coupon_discount\"\n"
                "    return \"standard\"\n"
            )
        },
    ),
    EvalTask(
        task_id="quality-05",
        category="quality",
        task_text=(
            "Implement compute_ticket_price(age, base_price) -> float: children under 18 "
            "get a 15% discount off the base price, no other adjustments. Raise ValueError "
            "if age or base_price is negative."
        ),
        # v2: was CODE-QUALITY. The broken variant omits an explicitly required ValueError,
        # which is a missing stated requirement -- a CORRECTNESS defect, not a style one.
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def compute_ticket_price(age: int, base_price: float) -> float:\n"
                "    if age < 18:\n"
                "        return base_price * 0.85\n"
                "    return base_price\n"
            )
        },
        clean_files={
            "solution.py": (
                "CHILD_AGE_CUTOFF = 18\n"
                "CHILD_DISCOUNT_RATE = 0.15\n\n\n"
                "def compute_ticket_price(age: int, base_price: float) -> float:\n"
                "    if age < 0 or base_price < 0:\n"
                "        raise ValueError(\"age and base_price must be non-negative\")\n"
                "    if age < CHILD_AGE_CUTOFF:\n"
                "        return base_price * (1 - CHILD_DISCOUNT_RATE)\n"
                "    return base_price\n"
            )
        },
    ),
    # ------------------------------------------------------------------ edge_case
    EvalTask(
        task_id="edge_case-01",
        category="edge_case",
        task_text=(
            "Implement average(nums) -> float returning the arithmetic mean, or 0.0 for an "
            "empty list."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def average(nums: list[float]) -> float:\n"
                "    return sum(nums) / len(nums)\n"
            )
        },
        clean_files={
            "solution.py": (
                "def average(nums: list[float]) -> float:\n"
                "    if not nums:\n"
                "        return 0.0\n"
                "    return sum(nums) / len(nums)\n"
            )
        },
    ),
    EvalTask(
        task_id="edge_case-02",
        category="edge_case",
        task_text=(
            "Implement get_user_email(user) -> str | None that safely reads "
            "user['profile']['email'], returning None if any part of that path is missing, "
            "without raising."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def get_user_email(user: dict) -> str | None:\n"
                "    return user[\"profile\"][\"email\"]\n"
            )
        },
        clean_files={
            "solution.py": (
                "def get_user_email(user: dict) -> str | None:\n"
                "    profile = user.get(\"profile\")\n"
                "    if not isinstance(profile, dict):\n"
                "        return None\n"
                "    email = profile.get(\"email\")\n"
                "    return email if isinstance(email, str) else None\n"
            )
        },
    ),
    EvalTask(
        task_id="edge_case-03",
        category="edge_case",
        task_text=(
            "Implement truncate(text, max_chars) -> str that shortens text to at most "
            "max_chars characters, without corrupting multi-byte Unicode characters."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def truncate(text: str, max_chars: int) -> str:\n"
                "    return text.encode(\"utf-8\")[:max_chars].decode(\"utf-8\")\n"
            )
        },
        clean_files={
            "solution.py": (
                "def truncate(text: str, max_chars: int) -> str:\n"
                "    return text[:max_chars]\n"
            )
        },
    ),
    EvalTask(
        task_id="edge_case-04",
        category="edge_case",
        task_text=(
            "Implement is_business_hours(hour) -> bool returning True for hours in [9, 17) "
            "using 24-hour time -- 9:00 is open, 17:00 is already closed. Raise ValueError "
            "if hour is outside [0, 23]."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "def is_business_hours(hour: int) -> bool:\n"
                "    return 9 <= hour <= 17\n"
            )
        },
        clean_files={
            "solution.py": (
                "def is_business_hours(hour: int) -> bool:\n"
                "    if not isinstance(hour, int) or hour < 0 or hour > 23:\n"
                "        raise ValueError(\"hour must be an integer in [0, 23]\")\n"
                "    return 9 <= hour < 17\n"
            )
        },
    ),
    EvalTask(
        task_id="edge_case-05",
        category="edge_case",
        task_text=(
            "Implement a Counter class with increment() and a value property, safe to call "
            "from multiple threads concurrently."
        ),
        expected_defect_category="CORRECTNESS",
        broken_files={
            "solution.py": (
                "class Counter:\n"
                "    def __init__(self) -> None:\n"
                "        self._value = 0\n\n"
                "    def increment(self) -> None:\n"
                "        current = self._value\n"
                "        self._value = current + 1\n\n"
                "    @property\n"
                "    def value(self) -> int:\n"
                "        return self._value\n"
            )
        },
        clean_files={
            "solution.py": (
                "import threading\n\n\n"
                "class Counter:\n"
                "    def __init__(self) -> None:\n"
                "        self._value = 0\n"
                "        self._lock = threading.Lock()\n\n"
                "    def increment(self) -> None:\n"
                "        with self._lock:\n"
                "            self._value += 1\n\n"
                "    @property\n"
                "    def value(self) -> int:\n"
                "        with self._lock:\n"
                "            return self._value\n"
            )
        },
    ),
]


def _build_cases(tasks: list[EvalTask]) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for task in tasks:
        cases.append(
            EvalCase(
                eval_case_id=f"{task.task_id}-broken",
                category=task.category,
                task_text=task.task_text,
                files=task.broken_files,
                expected_verdict="UNVERIFIED",
                expected_defect_category=task.expected_defect_category,
            )
        )
        cases.append(
            EvalCase(
                eval_case_id=f"{task.task_id}-clean",
                category=task.category,
                task_text=task.task_text,
                files=task.clean_files,
                expected_verdict="OK",
                expected_defect_category=None,
            )
        )
    return cases


CASES: list[EvalCase] = _build_cases(TASKS)


# ------------------------------------------------------------- benchmark v1 archive
#
# Benchmark v1 stays constructible so historical runs remain interpretable and so a
# v1-vs-v2 inventory diff can be computed without git archaeology. Only the six tasks v2
# changed are stored; everything else is shared with TASKS by reference, so this archive
# cannot drift from v1 for the unchanged 14 tasks -- they are the same objects.

_TASKS_BY_ID: dict[str, EvalTask] = {t.task_id: t for t in TASKS}

_V1_TASKS_CHANGED: dict[str, EvalTask] = {
    # CLARIFY_TASK: "within 0.01" did not fix the inclusive/exclusive boundary.
    "correctness-02": replace(
        _TASKS_BY_ID["correctness-02"],
        task_text=(
            "Implement is_close_enough(a, b) -> bool that returns True if two floats are "
            "close enough to be considered equal for currency comparison (within 0.01)."
        ),
    ),
    # A-3 CLARIFY_TASK + REPAIR_FIXTURE: v1 exposed a bool-only contract whose caller had to
    # resolve the host a second time, and a clean variant that checked one IPv4 address.
    "security-04": replace(
        _TASKS_BY_ID["security-04"],
        task_text=(
            "Implement is_safe_fetch_target(host) -> bool used to guard a URL-preview "
            "feature against fetching internal/private network addresses (SSRF)."
        ),
        broken_files={
            "solution.py": (
                "def is_safe_fetch_target(host: str) -> bool:\n"
                "    return True\n"
            )
        },
        clean_files={
            "solution.py": (
                "import ipaddress\n"
                "import socket\n\n\n"
                "def is_safe_fetch_target(host: str) -> bool:\n"
                "    try:\n"
                "        addr = socket.gethostbyname(host)\n"
                "        ip = ipaddress.ip_address(addr)\n"
                "    except (OSError, ValueError):\n"
                "        return False\n"
                "    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)\n"
            )
        },
    ),
    # CLARIFY_TASK: no single-source requirement, and a loose email rule.
    "quality-02": replace(
        _TASKS_BY_ID["quality-02"],
        task_text=(
            "Implement validate_signup(email, age) and validate_profile_update(email, age), "
            "each returning True if email contains '@' with a '.' after it, and age is 13-120."
        ),
    ),
    # A-1 CLARIFY_TASK + REPAIR_FIXTURE: v1 stated no ordering-rule requirement, and the
    # broken variant differed from the clean one only by inlining and verbosity.
    "quality-01": replace(
        _TASKS_BY_ID["quality-01"],
        task_text=(
            "Implement build_leaderboard(matches) where matches is a list of (player, points) "
            "tuples: total each player's points and return one row per player as "
            "{'rank': int, 'player': str, 'points': int}, ordered by total points descending "
            "with ties broken by player name ascending, ranks starting at 1."
        ),
        broken_files={
            "solution.py": (
                "def build_leaderboard(matches: list[tuple[str, int]]) -> list[dict[str, object]]:\n"
                "    totals: dict[str, int] = {}\n"
                "    for player, points in matches:\n"
                "        if player in totals:\n"
                "            totals[player] = totals[player] + points\n"
                "        else:\n"
                "            totals[player] = points\n"
                "    ordered = sorted(totals, key=lambda name: (-totals[name], name))\n"
                "    rows: list[dict[str, object]] = []\n"
                "    for rank, player in enumerate(ordered, start=1):\n"
                "        rows.append({\"rank\": rank, \"player\": player, \"points\": totals[player]})\n"
                "    return rows\n"
            )
        },
    ),
    # A-2 CLARIFY_TASK + REPAIR_FIXTURE: v1 prescribed no function name and no single-
    # definition requirement, so the pair differed only by one identifier.
    "quality-03": replace(
        _TASKS_BY_ID["quality-03"],
        task_text=(
            "Implement a function that returns an existing user dict from a users-by-id "
            "dict if present, otherwise creates and stores a new default user record."
        ),
        broken_files={
            "solution.py": (
                "DEFAULT_USER_NAME = \"New User\"\n\n\n"
                "def get_user(users: dict[int, dict[str, str]], user_id: int) -> dict[str, str]:\n"
                "    if user_id in users:\n"
                "        return users[user_id]\n"
                "    new_user = {\"name\": DEFAULT_USER_NAME}\n"
                "    users[user_id] = new_user\n"
                "    return new_user\n"
            )
        },
    ),
    # CLARIFY_TASK: no tier table and no named-constant requirement.
    "quality-04": replace(
        _TASKS_BY_ID["quality-04"],
        task_text=(
            "Implement classify_order(total, is_member, has_coupon, in_stock) -> str "
            "returning 'rejected' if not in_stock, else a discount tier based on the other flags."
        ),
    ),
    # FIX_EXPECTED_CATEGORY: v1 filed a missing required ValueError as CODE-QUALITY.
    "quality-05": replace(_TASKS_BY_ID["quality-05"], expected_defect_category="CODE-QUALITY"),
}

TASKS_V1: list[EvalTask] = [_V1_TASKS_CHANGED.get(t.task_id, t) for t in TASKS]

CASES_V1: list[EvalCase] = _build_cases(TASKS_V1)


def validate_dataset(cases: list[EvalCase]) -> list[str]:
    """Structural validation only -- never judges whether a task is a good
    benchmark case, only whether it's well-formed enough to run. Mirrors
    execution_plan.py's validate_execution_plan: a pure function, no I/O,
    called by --dry-run before any LLM call is made.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()

    for i, case in enumerate(cases):
        if case.eval_case_id in seen_ids:
            errors.append(f"cases[{i}]: duplicate eval_case_id {case.eval_case_id!r}")
        seen_ids.add(case.eval_case_id)

        if case.category not in CATEGORIES:
            errors.append(f"cases[{i}]: unknown category {case.category!r}, expected one of {CATEGORIES}")

        if case.expected_verdict not in ("OK", "UNVERIFIED"):
            errors.append(
                f"cases[{i}]: expected_verdict must be 'OK' or 'UNVERIFIED', got {case.expected_verdict!r}"
            )

        if case.expected_defect_category is not None and case.expected_defect_category not in JUDGE_DIMENSIONS:
            errors.append(
                f"cases[{i}]: expected_defect_category must be one of {JUDGE_DIMENSIONS} or None, "
                f"got {case.expected_defect_category!r}"
            )

        if not case.files:
            errors.append(f"cases[{i}]: files must not be empty")

        if not case.task_text.strip():
            errors.append(f"cases[{i}]: task_text must not be empty")

    return errors
