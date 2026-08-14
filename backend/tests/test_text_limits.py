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
    # Every model, not a hand-picked three. The gate covering only the models
    # somebody remembered is how a whole table of unguarded columns — the one
    # the MLS feed writes — stayed invisible through five rounds of this.
    @pytest.mark.parametrize(
        "model",
        [Lead, Message, Conversation],
        ids=lambda m: m.__name__,
    )
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
        ("channel_routes", "channel"): "literal, set by the adapter that received it",
        ("conversations", "channel"): "trimmed on the model — it is in the clip list",
        ("follow_ups", "kind"): "enum value",
        ("properties", "source"): "literal: reso | idx | mls | manual",
        ("sync_state", "source"): "literal, one per feed",
        # Admin configuration through an authenticated form. Failing loudly is
        # right here: silently storing a different email than the one typed
        # would lock somebody out of an account they think they created.
        ("organizations", "slug"): "admin-entered config",
        ("accounts", "email"): "self-registration; stripped and lowercased at the schema, bounded there",
        ("allowed_users", "email"): "admin-entered, must not be silently altered",
        ("channel_routes", "destination"): "admin-entered provider address",
        ("user_activity", "email"): "our own string — a JWT claim, or a synthesised impersonation label",
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


class TestEveryTableWithBoundedTextHasBeenThoughtAbout:
    """The gate that would have found the last three rounds' defects.

    Trimming on the model only helps where writes go through ORM attributes.
    `properties` is written by one Core `INSERT … ON CONFLICT` per page, so no
    validator can fire — and a value that does not fit does not fail its own
    row, it fails the page, whose cursor is committed with it, so every later
    run refetches the same page and fails identically. One listing stalls the
    whole feed.

    So each table records how its bounded text is kept inside its columns.
    Adding a table, or a bounded column on one, fails here until somebody says.
    """

    HANDLED = {
        # Trimmed on the model — every writer goes through ORM attributes.
        "leads": "@validates on the model; identity key gets the digest",
        "messages": "@validates on the model; idempotency key gets the digest",
        "conversations": "@validates on the model",
        # Written by a Core INSERT, so validators cannot fire: the feed values
        # are fitted in `_map_reso_record` before they get here, with codes
        # translated rather than truncated.
        "properties": "fitted in listings._map_reso_record before the Core insert",
        # Operator configuration through an authenticated form. Failing loudly
        # is right: silently storing something other than what an admin typed
        # is worse than refusing it.
        "channel_routes": "admin config; loud failure is correct",
        "organizations": "admin config; loud failure is correct",
        "accounts": "self-registration, normalised and bounded at the schema",
        "allowed_users": "admin config; loud failure is correct",
        "agent_settings": "admin config; loud failure is correct",
        "sync_state": "written from our own literals",
        # Written from our own values, or after the customer's words are safe.
        "visits": "our own values plus a Cal.com id, written after the commit",
        "call_logs": "advisor input through a bounded schema",
        "user_activity": "our own strings; see the notes in platform.py",
    }

    def test_every_table_is_accounted_for(self) -> None:
        from sqlalchemy import Enum as SAEnum
        from sqlalchemy import String

        import app.models  # noqa: F401 — registers the models on the metadata
        from app.db.base import Base

        with_text = {
            table.name
            for table in Base.metadata.tables.values()
            if any(
                isinstance(column.type, String)
                and not isinstance(column.type, SAEnum)
                and getattr(column.type, "length", None)
                for column in table.columns
            )
        }
        undecided = sorted(with_text - set(self.HANDLED))
        assert not undecided, (
            f"tables with bounded text and no recorded decision: {undecided}. "
            "Say how values are kept inside their columns — and check whether "
            "the writer is a Core insert, where model validators never fire."
        )

    def test_the_gate_is_looking_at_something(self) -> None:
        # Derived from the schema, not from a number I typed: the previous
        # version of this idea asserted a count that happened to match, so it
        # was satisfied by the very gap it existed to find.
        from sqlalchemy import Enum as SAEnum
        from sqlalchemy import String

        import app.models  # noqa: F401
        from app.db.base import Base

        tables = [
            t
            for t in Base.metadata.tables.values()
            if any(
                isinstance(c.type, String)
                and not isinstance(c.type, SAEnum)
                and getattr(c.type, "length", None)
                for c in t.columns
            )
        ]
        assert len(tables) == len(self.HANDLED)


class TestEveryWriterOfTheIdentityKeyAgrees:
    """The claim that broke twice: "every writer normalises the same way".

    It was written once when only the message boundary did, and again when the
    model did but three services did not. Each time the merge stayed reachable
    through a route nobody had listed. So this walks the writers instead of
    trusting the sentence.
    """

    def test_discovery_does_not_merge_two_businesses(self) -> None:
        # Long tracking URLs share prefixes easily, and the import route takes
        # its website and email from a language model with no length bound. A
        # slice made the second business "already imported" — counted as
        # skipped, never created, with nothing to show why.
        from app.services.discovery import BusinessDTO, lead_identifier

        shared = "https://" + "x" * 250
        first = BusinessDTO("First Co", "fsbo", website=shared + "/a")
        second = BusinessDTO("Second Co", "fsbo", website=shared + "/b")
        assert lead_identifier(first) != lead_identifier(second)
        assert len(lead_identifier(first)) <= 254

    def test_discovery_agrees_with_the_model(self) -> None:
        from app.models import Lead
        from app.services.discovery import BusinessDTO, lead_identifier

        raw = "https://" + "y" * 300
        business = BusinessDTO("A Co", "fsbo", website=raw)
        assert lead_identifier(business) == Lead(phone=raw).phone

    def test_the_synthetic_key_is_normalised_too(self) -> None:
        from app.services.discovery import BusinessDTO, lead_identifier

        # No website, no email, no phone: the key is built from the name, and
        # two long similar names must still be two businesses.
        first = BusinessDTO("A" * 300, "fsbo", city="Denver")
        second = BusinessDTO("A" * 299 + "B", "fsbo", city="Denver")
        assert lead_identifier(first) != lead_identifier(second)
        assert len(lead_identifier(first)) <= 254

    def test_the_voice_helper_normalises_before_it_looks_up(self) -> None:
        # This one has no savepoint, so a lookup that misses the row it just
        # wrote takes the whole call's transaction down with it.
        import inspect

        from app.services import voice

        source = inspect.getsource(voice._resolve_or_create_lead)
        assert "clip_identifier(identifier)" in source, (
            "the voice tool-call path looks a lead up by a value the write "
            "would rewrite"
        )
