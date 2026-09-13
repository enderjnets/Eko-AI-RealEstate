# Platform Link Attribution Design

## Purpose

The publisher currently tags only an exact configured root URL. A caption that
already points to `/calculator`, or writes the domain without a scheme, leaves
Buffer without per-platform attribution and may leave YouTube text that is not
clickable. Publishing must preserve the intended destination while producing a
complete HTTPS URL tagged with platform, campaign, and content piece.

## Options considered

1. Add a `cta_path` database column and editor to every content piece. This is
   explicit but adds a migration and another approval control before the link
   normalizer itself is reliable.
2. Normalize the first Denver Home Story URL already present in the approved
   caption. This is selected because authors retain destination control and
   old approved pieces become measurable without a data migration.
3. Create a short-link table and redirect endpoint per publication. This gives
   richer click logs, but adds another public service and persistence layer
   before the current UTM path has been made dependable.

## Link rules

`with_platform_utm(text, cta_url, platform, piece_id, campaign)` finds the first
URL in the caption whose hostname exactly matches the configured CTA hostname.
It accepts `https://`, `http://`, `www.`, and bare-domain forms. It must not
match a lookalike hostname such as `denverhomestory.com.example.org`.

The output URL always uses the scheme and authority from the configured
`cta_url`, which is HTTPS in production. It preserves an explicit path,
non-UTM query parameters, and fragment from the caption. A generic root target
is changed to `/start`; an explicit destination such as `/calculator` or
`/#consult` remains that destination.

The function sets, replacing any old values rather than duplicating them:

- `utm_source=<platform value>`
- `utm_medium=social`
- `utm_campaign=<configured campaign>`
- `utm_content=piece-<piece id>`

Only the first matching Denver Home Story URL is rewritten. Captions without a
configured CTA or without a matching site URL remain byte-for-byte unchanged.
Surrounding punctuation is not captured as part of the URL.

The final caption continues through the existing fair-housing validation and
Buffer publishing path. No link is added to a caption whose approved text has
no site URL.

## Acceptance criteria

- Root URLs route to `/start` and carry the four current UTM fields.
- `/calculator`, `/#consult`, existing query parameters, and fragments survive.
- Bare and `www.` domains become complete HTTPS links.
- Existing UTM values are replaced once, not duplicated.
- Foreign and lookalike domains are untouched.
- A caption without a Denver Home Story link is untouched.
- Each of the three Buffer platform payloads carries its own source and the
  exact `piece-<id>` tag.
- Fair-housing output before and after URL normalization is unchanged.

