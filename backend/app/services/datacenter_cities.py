"""Cities where the visitor is a machine, not a neighbour.

A visit to a Denver real-estate page reporting a city in the middle of Iowa or
Oregon, that scrolls nothing at all, is a crawler or a link-preview fetcher
running in somebody's cloud region. The geo header is honest about where the
request came from; what does not hold is the inference that a person lives
there and is shopping for a house in Denver.

── Two tiers, and the difference is deliberate ──────────────────────────────
`OBSERVED` are cities that have actually appeared in our own
`landing_sessions` behaving like machines, each with what was measured on
16-sep-2026. `KNOWN_SITES` are other hyperscale locations from the same
operators that we have **not** seen behaving that way — listed so the next
crawl from a different region is caught the first time rather than after
somebody notices.

Keeping them apart matters: the first tier is evidence, the second is
expectation, and a list that blurs the two invites somebody to "tidy it up" by
adding a city that is mostly a city.

── What is deliberately NOT here, and why ───────────────────────────────────
Dublin, San Jose, Chicago, New York, Mountain View, Dallas, Phoenix. All host
large amounts of cloud capacity; all are places where many people live, some
of whom move to Denver. **The asymmetry decides it.** This operation has zero
leads, so a false `automated` throws away the only kind of row that matters,
while a false `unknown` costs a slightly noisier denominator. When in doubt,
leave it `unknown`.

Ashburn is the judgement call that stayed. About fifty thousand people live
there and it is also the densest concentration of internet infrastructure on
earth — but all three of its visits here were one event with zero scroll, and
the rule below requires exactly that.
"""

# Measured in our own `landing_sessions`. Each note is what was seen, not a
# general claim about the city.
OBSERVED: dict[str, str] = {
    # The Facebook infrastructure that arrived on 11-sep and was counted as
    # "started the form": 38-41 events each, zero scroll, seven rows in all.
    "forest city": "Meta, North Carolina — 1 session, 39 events, 0% scroll, form_start",
    "clonee": "Meta, Ireland — 3 sessions, 77 events, 0% scroll, 2 form_starts",
    "prineville": "Meta, Oregon — 2 sessions, 0% scroll, 1 form_start",
    "boardman": "AWS, Oregon — 3 sessions, 43 events, 0% scroll, 1 form_start",
    "springfield": "Meta, Nebraska — 1 session, 38 events, 0% scroll, form_start",
    # Found on 16-sep while profiling the one-event, zero-scroll bucket. Both
    # arrived as `direct`, which is what a machine with no referrer looks like.
    "council bluffs": "Google, Iowa — 9 sessions, one event each, 0% scroll",
    "ashburn": "AWS, Virginia — 3 sessions, one event each, 0% scroll",
}

# The same operators' other sites, not seen behaving this way in our data.
KNOWN_SITES: dict[str, str] = {
    "the dalles": "Google, Oregon",
    "altoona": "Meta, Iowa",
    "papillion": "Meta, Nebraska",
    "quincy": "Microsoft, Washington",
    "new albany": "Meta, Ohio",
    "eemshaven": "Google, Netherlands",
    "hamina": "Google, Finland",
    "odense": "Meta, Denmark",
}

# Seen, and deliberately left OUT of both tiers.
#
# Boydton (Microsoft, Virginia) has 4 sessions here with 23 events between them
# and a maximum scroll of **100%**. Whatever it is, it does not match the
# signature this module is about, and the rule below would never fire on it.
# Adding it would be listing a city we have no evidence against, which is the
# habit this file exists to resist.
NOT_LISTED_DESPITE_BEING_A_DATACENTER: dict[str, str] = {
    "boydton": "Microsoft, Virginia — 4 sessions, 23 events, scrolled to 100%",
}

# Luleå is stored in our own database as the mojibake `LuleÃ¥` — measured, the
# bytes are `4c756c65c383c2a5`, which is `å` decoded as Latin-1 and re-encoded
# as UTF-8. That is a real defect in how the Cloudflare city header is read,
# and it affects every city whose name is not ASCII.
#
# Both spellings are matched here on purpose. Writing only the correct one
# would produce a list that looks right and matches nothing, and writing only
# the broken one would silently stop working the day the header bug is fixed.
_ENCODING_VARIANTS: dict[str, str] = {
    "lulea": "Meta, Sweden — 1 session, 38 events, 0% scroll, form_start",
    "luleå": "Meta, Sweden — correct spelling",
    "luleã¥": "Meta, Sweden — as actually stored today, double-encoded",
}

DATACENTER_CITIES: frozenset[str] = (
    frozenset(OBSERVED) | frozenset(KNOWN_SITES) | frozenset(_ENCODING_VARIANTS)
)


def is_datacenter_city(city: str | None) -> bool:
    """Whether a city name is one of the machine rooms above.

    Lowercased and stripped, because the geo header's capitalisation is not
    ours to rely on.
    """
    if not city:
        return False
    return city.strip().lower() in DATACENTER_CITIES
