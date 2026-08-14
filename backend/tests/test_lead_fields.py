"""What a machine understood, made safe for the table.

Everything here protects one thing: both writers of these columns run inside
the transaction that stores what the customer actually said — the WhatsApp
message, or the call transcript. A value the database refuses does not lose a
field, it loses the conversation, and the provider replays the same payload so
every retry fails the same way.
"""
from decimal import Decimal

import pytest

from app.services.lead_fields import (
    merge_budget,
    parse_budget,
    storable_budget,
    storable_text,
)


class TestParsingWhatTheModelSaid:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Suffixes. Dropping them is the dangerous reading: 450k as 450 is
            # wrong by a thousand and passes every check downstream, so the
            # lead gets matched against houses they never asked about.
            ("450k", 450_000),
            ("1.2M", 1_200_000),
            ("$1.2m", 1_200_000),
            ("2.5 million", 2_500_000),
            ("under 300k", 300_000),
            ("450 mil", 450_000),
            # Grouping, both conventions. This is a Colorado brokerage, and
            # "450,000" used to come out as 450.
            ("450,000", 450_000),
            ("1,200,000", 1_200_000),
            ("1.200.000", 1_200_000),
            ("1.200.000,50", 1_200_000.5),
            ("1,200,000.50", 1_200_000.5),
            ("450 000", 450_000),
            ("$450,000", 450_000),
            # Plain decimals are left alone.
            ("450.5", 450.5),
            ("450,5", 450.5),
            (900_000, 900_000),
            (Decimal("750000"), 750_000),
        ],
    )
    def test_it_reads_what_a_person_would_read(self, raw: object, expected: float) -> None:
        assert parse_budget(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            # Two numbers is a range, and welding them into a third invents an
            # answer: "between 300k and 500k" once produced 300500.
            "between 300k and 500k",
            "300k-500k",
            "1,20,000",   # grouping this code does not claim to read
            "1e6",        # exponent notation, read wrong more easily than right
            "abc", "", None, "n/a", "null", "-", ".", ",", "$",
            True,         # a bool is not a budget, and bool is an int in Python
            [1, 2], {"a": 1},
        ],
    )
    def test_it_says_nothing_rather_than_guessing(self, raw: object) -> None:
        assert parse_budget(raw) is None

    def test_the_minus_sign_is_part_of_the_number(self) -> None:
        # Losing it turned "-1" into 1: a negative silently becoming a positive
        # is worse than not reading it, because nothing downstream can tell.
        assert parse_budget("-1") == -1
        assert parse_budget("-50000") == -50_000

    def test_it_never_raises(self) -> None:
        for hostile in ("--5", "١٢٣", "１２３", "9" * 400, Decimal("1E+400"), float("nan")):
            parse_budget(hostile)  # the assertion is that this line returns


class TestWhatTheTableWillAccept:
    def test_values_the_database_refuses_are_dropped(self) -> None:
        assert storable_budget(-50_000) is None
        assert storable_budget("-1") is None
        assert storable_budget(1e14) is None

    def test_nan_and_infinity_are_dropped(self) -> None:
        # NaN survives every comparison-based check — `nan < 0` is False and so
        # is `nan > ceiling` — and Postgres stores it in a NUMERIC quite
        # happily. The lead then matches no listing ever again, and any later
        # comparison against it raises inside the transaction.
        assert storable_budget(float("nan")) is None
        assert storable_budget(float("inf")) is None
        assert storable_budget(float("-inf")) is None

    def test_zero_is_a_real_answer(self) -> None:
        assert storable_budget(0) == 0

    def test_text_is_trimmed_to_the_column(self) -> None:
        # `urgency` is 40 characters; a voice agent says "as soon as possible,
        # ideally within the next thirty days" — 52. Postgres does not truncate,
        # it refuses, and the refusal costs the call.
        long = "as soon as possible, ideally within the next thirty days"
        assert len(storable_text(long, "urgency")) <= 40
        assert storable_text("  Brickell  ", "zone") == "Brickell"
        assert storable_text("", "zone") is None
        assert storable_text(None, "zone") is None
        assert storable_text(123, "zone") is None


class TestReconcilingWithWhatWeAlreadyKnew:
    def test_a_complete_range_overrides_a_stale_guess(self) -> None:
        # They say "between 100 and 300"; an earlier guess left 500 as the
        # minimum. Keeping the old one shows them what they just ruled out,
        # however many times they repeat themselves.
        assert merge_budget((500_000, None), (100_000, 300_000)) == (100_000, 300_000)

    def test_a_single_value_only_fills_a_gap(self) -> None:
        assert merge_budget((None, 300_000), (100_000, None)) == (100_000, 300_000)
        assert merge_budget((100_000, 300_000), (None, 900_000)) == (100_000, 300_000)

    def test_it_never_produces_a_pair_the_table_would_refuse(self) -> None:
        assert merge_budget((None, 300_000), (900_000, None)) == (None, 300_000)
        assert merge_budget((900_000, None), (None, 300_000)) == (900_000, None)
        assert merge_budget((None, None), (900_000, 100_000)) == (None, None)

    def test_a_single_exact_price_is_a_valid_range(self) -> None:
        # "exactly 400k". A strict `<` here would drop it, and no test caught
        # that until one was written for it.
        assert merge_budget((None, None), (400_000, 400_000)) == (400_000, 400_000)
        assert merge_budget((None, 400_000), (400_000, None)) == (400_000, 400_000)

    def test_a_decimal_already_in_the_row_compares_cleanly(self) -> None:
        # `lead.budget_max` is a Decimal once loaded and the extraction is a
        # float. Mixing them is fine; mixing a Decimal with NaN is not.
        assert merge_budget((None, Decimal("300000.00")), (100_000.0, None)) == (
            100_000.0,
            Decimal("300000.00"),
        )
        assert merge_budget((None, Decimal("300000.00")), (900_000.0, None)) == (
            None,
            Decimal("300000.00"),
        )

    def test_a_nan_on_either_side_is_treated_as_absent(self) -> None:
        # This is the one that took the message down: `Decimal('300000.00') >=
        # nan` raises InvalidOperation, inside the transaction.
        nan = float("nan")
        assert merge_budget((None, Decimal("300000.00")), (nan, None)) == (
            None,
            Decimal("300000.00"),
        )
        assert merge_budget((Decimal("NaN"), None), (100_000.0, None)) == (100_000.0, None)
        assert merge_budget((None, None), (nan, nan)) == (None, None)


class TestTheFeedCannotPoisonItself:
    """A recorded reason in the inventory was wrong, and this is what it should
    have said. RESO allows 255 characters for a ListingKey against a column
    that holds 120. The page is written in one statement and its cursor is
    committed with it, so an over-long key does not fail one listing — it fails
    the page, the cursor never moves, and every later run refetches exactly the
    same page. One record stops the whole MLS feed until somebody notices."""

    def test_an_over_long_listing_key_is_skipped_not_fatal(self) -> None:
        from app.services.listings import _map_reso_record

        record = {
            "ListingKey": "K" * 200,
            "UnparsedAddress": "1200 S Downing St",
            "City": "Denver",
            "ListPrice": 640000,
        }
        assert _map_reso_record(record) is None

    def test_an_ordinary_listing_still_comes_through(self) -> None:
        from app.services.listings import _map_reso_record

        record = {
            "ListingKey": "REC1234567",
            "UnparsedAddress": "1200 S Downing St",
            "City": "Denver",
            "ListPrice": 640000,
        }
        assert _map_reso_record(record) is not None
