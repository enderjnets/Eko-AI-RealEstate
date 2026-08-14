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
from app.models import Conversation, Lead, Message


class TestEveryBoundedColumnIsCovered:
    @pytest.mark.parametrize("model", [Lead, Message, Conversation])
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

    def test_a_long_email_thread_id_is_trimmed(self) -> None:
        # On email this holds the provider's thread key, built from the
        # `References` header chain — which grows with every forward and runs
        # past 255 on a long one. Written in the same transaction as the
        # message it belongs to.
        conversation = Conversation(external_thread_id="t" * 900)
        assert len(conversation.external_thread_id) == 255

    def test_none_and_non_strings_pass_through(self) -> None:
        lead = Lead(phone="+13035550003", name=None)
        assert lead.name is None


class TestIdentifiersAreNotProse:
    """`leads.phone` is the key everything looks a person up by, and it is
    UNIQUE per organisation. Trimming it at the model — the right move for a
    free-text column — makes the write and the lookup disagree, which is worse
    than the failure it replaced: the first message stores a 254-character row,
    the second searches for the original value, finds nothing, tries to insert
    and hits the unique index. "The first message is lost" becomes "every
    message after the first is lost", and that one is harder to notice.

    So the identifier is normalised where it enters instead, and everything
    downstream agrees by construction.
    """

    def test_an_over_long_identifier_is_clipped_on_arrival(self) -> None:
        from app.services._common import ParsedMessage

        raw = "a" * 240 + "@a-very-long-domain-name-example.invalid"
        assert len(raw) > 254
        parsed = ParsedMessage(
            channel="email",
            external_id="m1",
            from_identifier=raw,
            from_name="Someone",
            content="hello",
        )
        assert len(parsed.from_identifier) == 254

    def test_the_same_sender_normalises_to_the_same_identifier(self) -> None:
        # The point of doing it here: two messages from one person must resolve
        # to one lead, which is only true if lookup and write see one string.
        from app.services._common import ParsedMessage

        raw = "b" * 300
        first = ParsedMessage(
            channel="email", external_id="m1", from_identifier=raw,
            from_name="Someone", content="hello",
        )
        second = ParsedMessage(
            channel="email", external_id="m2", from_identifier=raw,
            from_name="Someone", content="again",
        )
        assert first.from_identifier == second.from_identifier

    def test_an_ordinary_identifier_is_untouched(self) -> None:
        from app.services._common import ParsedMessage

        parsed = ParsedMessage(
            channel="sms", external_id="m1", from_identifier="+13035550100",
            from_name="Someone", content="hello",
        )
        assert parsed.from_identifier == "+13035550100"
