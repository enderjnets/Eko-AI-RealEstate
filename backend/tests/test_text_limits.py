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

    def test_two_senders_sharing_a_prefix_stay_two_people(self) -> None:
        """The failure that plain truncation creates, and the reason this is a
        digest rather than a slice.

        Two addresses identical for their first 254 characters clipped to the
        same string, so they resolved to one lead — one person's messages in
        another person's thread, with the agent replying to both. That is worse
        than losing a message, and it can be arranged on purpose.
        """
        from app.services._common import clip_identifier

        alice = "c" * 254 + "-alice@example.invalid"
        bob = "c" * 254 + "-bob@example.invalid"
        assert clip_identifier(alice) != clip_identifier(bob)
        assert len(clip_identifier(alice)) == 254
        assert clip_identifier(alice) == clip_identifier(alice)

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


class TestTheIdempotencyKey:
    """`messages.external_id` is UNIQUE per organisation and it is the key that
    answers "have we already handled this?". Both ways of getting it wrong are
    silent, and one of them looks like success."""

    def test_two_different_provider_ids_stay_two_messages(self) -> None:
        # Truncated, a message whose id shares a prefix with another is filed
        # as already-seen: the customer wrote, we answered nothing, and there
        # is no error anywhere to notice.
        from app.models import Message

        first = Message(external_id="q" * 254 + "-one")
        second = Message(external_id="q" * 254 + "-two")
        assert first.external_id != second.external_id
        assert len(first.external_id) == 254

    def test_the_lookup_and_the_stored_value_agree(self) -> None:
        # The "seen this already?" query runs before the row exists, so it uses
        # the parsed value while the row keeps the model's. If those disagree,
        # every redelivery looks new and the customer gets answered twice.
        from app.models import Message
        from app.services._common import ParsedMessage

        raw = "w" * 300
        parsed = ParsedMessage(
            channel="whatsapp", external_id=raw, from_identifier="+13035550001",
            from_name="Someone", content="hello",
        )
        assert parsed.external_id == Message(external_id=raw).external_id

    def test_an_ordinary_provider_id_is_untouched(self) -> None:
        from app.models import Message

        assert Message(external_id="wamid.HBgLMTM=").external_id == "wamid.HBgLMTM="


class TestEveryUniqueStringKeyHasBeenThoughtAbout:
    """The inventory, so the next one cannot arrive unnoticed.

    A bounded string column with a UNIQUE constraint has three failure modes,
    and which one applies depends entirely on where the value comes from:

    - Stored whole, an over-long value fails the write. If that write shares a
      transaction with something the customer sent, the message is lost.
    - Truncated, two distinct values collide. On an identity key that merges
      two people; on an idempotency key it silently drops a message.
    - Rewritten at all, a value that has to travel back to an external system
      stops matching there.

    Twelve rounds of audit found these one at a time. This test lists every one
    in the schema with the reason it is safe, so adding a new unique string
    column fails here until somebody writes that reason down.
    """

    # column -> why it cannot bite
    DECIDED = {
        # Normalised with a digest: identity and idempotency keys, fed by
        # providers, looked up by equality. See `clip_identifier`.
        ("leads", "phone"): "digest — identity key from providers",
        ("messages", "external_id"): "digest — idempotency key from providers",
        # Written from fixed literals in our own code, never from input.
        ("channel_routes", "channel"): "literal: whatsapp | sms | email | voice",
        ("conversations", "channel"): "literal, same set",
        ("follow_ups", "kind"): "enum value",
        ("properties", "source"): "literal: mls | manual",
        ("sync_state", "source"): "literal, one per feed",
        # Admin configuration through an authenticated form. Failing loudly is
        # right here: silently storing a different email than the one typed
        # would lock somebody out of an account they think they created.
        ("organizations", "slug"): "admin-entered config",
        ("accounts", "email"): "admin-entered, must not be silently altered",
        ("allowed_users", "email"): "admin-entered, must not be silently altered",
        ("channel_routes", "destination"): "admin-entered provider address",
        ("user_activity", "email"): "copied from accounts.email",
        # Round-trips to an external system, so it must be stored faithfully or
        # not at all: a truncated id cannot cancel the booking it names, and a
        # digest could not either. Cal.com uids are ~20 characters against 120.
        ("visits", "external_booking_id"): "must round-trip to Cal.com; never rewrite",
        # From the MLS feed. The reason recorded here was WRONG when it was
        # written: an over-long key does not fail its own listing. The page is
        # written in one INSERT … ON CONFLICT and the cursor is committed with
        # it, so the page fails, the cursor never advances, and the next run
        # refetches the same page and fails the same way — one record stalling
        # the entire feed until a human intervenes. The record is skipped at
        # the parser now, with a loud log line.
        ("properties", "external_id"): "feed id; over-long records skipped at the parser",
    }

    def test_the_inventory_is_complete(self) -> None:
        from sqlalchemy import String

        import app.models  # noqa: F401 — registers every model on the metadata
        from app.db.base import Base

        # Walked from the metadata rather than from `dir(app.models)`: a model
        # that someone forgets to export would be invisible to the second, and
        # a safety net with a hole that only opens later is the shape of every
        # defect this file exists to stop.
        found = set()
        for table in Base.metadata.tables.values():
            unique: set[str] = set()
            for constraint in table.constraints:
                if type(constraint).__name__ == "UniqueConstraint":
                    unique |= {c.name for c in constraint.columns}
            for index in table.indexes:
                if index.unique:
                    unique |= {c.name for c in index.columns}
            for column in table.columns:
                if (
                    column.name in unique
                    and isinstance(column.type, String)
                    and column.type.length
                ):
                    found.add((table.name, column.name))

        undecided = sorted(found - set(self.DECIDED))
        assert not undecided, (
            f"new unique string columns with no decision recorded: {undecided}. "
            "Say where the value comes from and which of the three failure "
            "modes applies — see this class's docstring."
        )


class TestTheIdentityKeyOnEveryRoute:
    """v0.46.6 said it had stopped two senders becoming one lead. It had — on
    the inbound path only. `POST /api/v1/leads` writes the same column through
    the model, which was still slicing, so the merge stayed reachable through
    the route a realtor uses and the two normalisations of one key disagreed
    with each other."""

    def test_the_model_and_the_boundary_agree(self) -> None:
        from app.models import Lead
        from app.services._common import clip_identifier

        raw = "q" * 254 + "-someone@example.invalid"
        assert Lead(phone=raw).phone == clip_identifier(raw)

    def test_two_senders_stay_two_leads_through_the_model(self) -> None:
        from app.models import Lead

        alice = "q" * 254 + "-alice@example.invalid"
        bob = "q" * 254 + "-bob@example.invalid"
        assert Lead(phone=alice).phone != Lead(phone=bob).phone

    def test_the_create_route_normalises_before_it_looks_anything_up(self) -> None:
        # The route searches by this value and then writes it. If the schema
        # left it raw, the search would miss the row the model had normalised
        # and the second attempt would hit the unique index — a 500 that
        # repeats for ever.
        from app.api.v1.leads import LeadCreate
        from app.models import Lead

        raw = "r" * 300
        assert LeadCreate(phone=raw).phone == Lead(phone=raw).phone

    def test_an_ordinary_number_is_untouched_everywhere(self) -> None:
        from app.api.v1.leads import LeadCreate
        from app.models import Lead

        assert Lead(phone="+13035550001").phone == "+13035550001"
        assert LeadCreate(phone="+13035550001").phone == "+13035550001"
