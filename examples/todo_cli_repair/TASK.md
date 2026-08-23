# Demo task: todo_cli_repair (repair required)

Task text:

    parse_due_date('') and parse_due_date('   ') both fail with an unhelpful
    error. Make them raise ValueError('due date must not be empty'), and add a
    regression test. Do not change the existing behaviour for valid dates.

Why this needs a repair round: the obvious guard is a length check
(`if len(raw) != 10: raise ValueError(...)`), which rejects
`"  2026-08-21  "` and breaks the existing
`test_tolerates_surrounding_whitespace`. The agent must run the tests, observe
the real failure, and replace the guard with `if not raw.strip():`.
