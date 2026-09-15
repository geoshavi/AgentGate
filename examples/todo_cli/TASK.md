# Demo task: todo_cli (straightforward success)

`parse_due_date("")` currently fails with an unhelpful
`ValueError: invalid literal for int() with base 10: ''`, because `"".split("-")`
is `[""]` and `int("")` raises before any index error can occur.

Task text for the demo run:

    parse_due_date('') fails with an unhelpful error. Make it raise
    ValueError('due date must not be empty') for empty input, and add a
    regression test.

The fix is a single guard and leaves the existing ISO-date test passing, so
this fixture is expected to reach verification without a repair round.

Run against a COPY of this directory -- `engine code` edits the workspace in
place. In Windows PowerShell:

    Copy-Item -Recurse examples\todo_cli "$env:TEMP\todo_cli"
    engine code "<task text above>" --workspace "$env:TEMP\todo_cli"
