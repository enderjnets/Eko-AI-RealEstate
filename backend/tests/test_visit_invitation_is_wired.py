"""Booking a visit must actually send the invitation.

The `.ics` builder has its own unit tests, and they would all stay green with
the invitation never sent: a generator nobody calls is the exact shape of the
bug this project keeps paying for — `render_error` written and never displayed,
`publications` painted from a table nothing wrote, a Fair Housing filter whose
only callers were in the video lane.

Checked by AST rather than by booking a visit end to end, deliberately. The two
call sites are in different layers (an HTTP handler and a voice tool handler)
and both sit behind a real calendar booking; an integration test for each would
be mostly scaffolding, and would still not answer the question this one does —
"is the call there at all".
"""
from __future__ import annotations

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# Every place that creates a Visit row, and therefore every place that owes the
# lead and the agent an invitation.
BOOKING_SITES = [
    ("app/api/v1/visits.py", "book_slot"),
    ("app/services/voice.py", "handle_tool_call"),
]


def _function(path: str, name: str) -> ast.AST:
    tree = ast.parse((BACKEND / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path}::{name} not found — did it get renamed?")


def _calls(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            if isinstance(func, ast.Name):
                found.add(func.id)
            elif isinstance(func, ast.Attribute):
                found.add(func.attr)
    return found


def test_both_booking_paths_send_the_invitation() -> None:
    for path, name in BOOKING_SITES:
        assert "send_visit_invitation" in _calls(_function(path, name)), (
            f"{path}::{name} creates a Visit without sending the calendar "
            "invitation. The appointment would exist only in our own table — "
            "which is the state this feature was written to end."
        )


def test_both_paths_still_create_a_visit() -> None:
    """Guard on the guard.

    If a booking path stops creating a Visit — renamed, moved, refactored away —
    the test above keeps passing over a function that no longer books anything,
    and the real booking site goes unchecked. This is the same failure the
    content-gate sweep had: a set of names that could quietly empty out.
    """
    for path, name in BOOKING_SITES:
        assert "Visit" in _calls(_function(path, name)), (
            f"{path}::{name} no longer constructs a Visit; the booking site has "
            "moved and BOOKING_SITES is now checking the wrong function."
        )
