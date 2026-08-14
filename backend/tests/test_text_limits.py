"""Nothing a machine writes can be too long for its column.

Nine rounds of audit found this one field at a time — `urgency`, then `zone`,
then the display name on a constructor two lines below one that had just been
guarded, then an email subject. Every fix was right and every one covered the
field somebody was looking at.

Postgres does not truncate an over-long VARCHAR, it refuses the statement, and
on these paths the same transaction is storing what the customer said. So the
rule lives on the model, and these tests walk the tables rather than a list
anyone has to remember to update.
"""
import pytest

from app.db.text_limits import bounded_string_columns
from app.models import Lead, Message


class TestEveryBoundedColumnIsCovered:
    @pytest.mark.parametrize("model", [Lead, Message])
    def test_no_bounded_column_is_left_unregistered(self, model: type) -> None:
        """A new `String(n)` column added without registering it is a hole of
        exactly the kind this exists to close, so the check is derived from the
        table, not from a list."""
        registered = set(model.__mapper__.validators.keys())
        missing = sorted(set(bounded_string_columns(model)) - registered)
        assert not missing, (
            f"{model.__name__} has bounded columns nothing trims: {missing}. "
            "An over-long value there does not lose the field, it loses the "
            "message the same transaction was storing."
        )


class TestTrimming:
    def test_a_long_name_is_trimmed_not_refused(self) -> None:
        # An email `From:` display name has no length limit in the RFC, and a
        # forwarded broker signature routinely runs past 160 characters.
        lead = Lead(phone="+13035550000", name="N" * 400)
        assert len(lead.name) == 160

    def test_a_long_zone_is_trimmed(self) -> None:
        # The classifier answering "which neighbourhoods?" with a list.
        lead = Lead(phone="+13035550001", zone="Highland, Berkeley, Sunnyside, " * 12)
        assert len(lead.zone) == 160

    def test_a_long_subject_is_trimmed(self) -> None:
        # Subject headers fold and grow through a forwarded chain; the column
        # is 500. An email destroyed by its own subject line is a real loss.
        message = Message(subject="S" * 900)
        assert len(message.subject) == 500

    def test_a_value_that_fits_is_untouched(self) -> None:
        lead = Lead(phone="+13035550002", name="Marisol Vega", zone="Brickell")
        assert lead.name == "Marisol Vega"
        assert lead.zone == "Brickell"

    def test_none_and_non_strings_pass_through(self) -> None:
        lead = Lead(phone="+13035550003", name=None)
        assert lead.name is None
