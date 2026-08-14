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


# Both spellings. Fourteen of the thirty migrations here declare
# `revision: str = "..."` — and so does `migrations/script.py.mako`, this
# project's own template, which means every migration Alembic generates from
# now on takes the form the first version of this regex could not see. A guard
# blind to all future instances of what it guards is worse than none, because
# it reads as coverage.
_REVISION = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"'](.+?)[\"']", re.M)


def _revisions() -> list[tuple[str, str]]:
    found = []
    for path in sorted(VERSIONS.glob("*.py")):
        match = _REVISION.search(path.read_text())
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


def test_the_check_sees_every_migration() -> None:
    """Counted against the files on disk, not against a number I wrote down.

    The first version of this asserted `>= 16`, which was exactly the number the
    regex happened to match — so the guard against silently checking nothing was
    satisfied by the very miss it existed to catch.
    """
    on_disk = [p for p in VERSIONS.glob("*.py") if not p.name.startswith("__")]
    checked = _revisions()
    assert len(checked) == len(on_disk), (
        f"{len(on_disk) - len(checked)} migrations have a revision id this check "
        f"cannot see: {sorted({p.name for p in on_disk} - {n for n, _ in checked})}"
    )
