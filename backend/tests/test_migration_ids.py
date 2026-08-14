"""Revision identifiers have to fit the table Alembic keeps them in.

`alembic_version.version_num` is `varchar(32)` and Alembic owns it, so it is
invisible to the schema inventory in `test_text_limits.py` — which walks our own
metadata. These ids are also the one string in this project written entirely by
hand, in a naming style (`NNN_what_it_does`) that grows with how descriptive the
name is.

The failure is at deploy time and confusing when it comes: the migration's DDL
runs and then recording it fails, so the operator sees an error from a step that
looks unrelated to the change they wrote. Catching it here costs nothing.
"""
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"

# The column is 32. Stopping at 30 leaves room to rename a revision slightly
# without a deploy being the thing that tells you it was too long.
COMFORTABLE = 30


def _revisions() -> list[tuple[str, str]]:
    found = []
    for path in sorted(VERSIONS.glob("*.py")):
        match = re.search(r"^revision = [\"'](.+?)[\"']", path.read_text(), re.M)
        if match:
            found.append((path.name, match.group(1)))
    return found


def test_every_revision_id_fits_with_room_to_spare() -> None:
    too_long = [
        (name, rev, len(rev)) for name, rev in _revisions() if len(rev) > COMFORTABLE
    ]
    assert not too_long, (
        f"revision ids too long for alembic_version.version_num (32): {too_long}"
    )


def test_there_are_revisions_to_check() -> None:
    # A guard that silently checks nothing is worse than no guard: if the glob
    # or the regex ever stops matching, this says so instead of passing.
    assert len(_revisions()) >= 16
