# Denver Home Story Video Quality v2

## Goal

Produce daily English vertical videos that earn attention and send qualified
viewers to DenverHomeStory.com, while keeping every financial claim reproducible
against the site calculator and every publishable frame attributable to Denver
Home Story and Engel & Völkers.

## Measured problem

Piece 83 is 44.08 seconds long. Its four Eko scene prompts are cycled by the
BitTrader renderer, the calculator never appears, the opening overlay is broken
English with an inverted Spanish question mark, and the final frame contains no
deterministic URL or brokerage line. One generated door also carries the readable
number `19239`. BitTrader reported thumbnail, watermark, karaoke, and pacing as
passing because its pacing check only tests a broad duration range.

## Chosen architecture

Eko remains the editorial authority. It computes figures, writes the narration,
chooses seven to nine distinct scene prompts, supplies the opening statement and
the destination, and validates the delivered file. The ROG and BitTrader remain
the visual engine and continue using local generation. After BitTrader returns an
MP4, the Eko worker applies a deterministic DHS finishing pass and performs the
final quality checks before delivery to the approval queue.

BitTrader keeps its shared producer. Its DHS profile disables the producer's
generic hook and adopts a restrained channel-specific subtitle style. Defaults
for the other channels remain byte-for-byte compatible.

## Editorial contract

- English scripts target 45-65 model-written words. The deterministic spoken CTA
  may bring the narration to at most 75 words.
- Generated pieces carry seven to nine distinct scene prompts. Calculated pieces
  use eight hand-written prompts and eight hand-written screen lines.
- The result appears in the first five seconds.
- A calculated piece has one destination:
  `denverhomestory.com/calculator`, seeded with the same rent and savings used by
  the server calculation.
- The spoken CTA appears once. The finishing pass displays the destination once
  on the final card.
- The final card lasts three seconds and carries the DHS mark, destination, and
  brokerage line. A live calculator screenshot is used when Chromium can capture
  it; a branded navy card is the fail-safe.

## Render contract

The internal render-job response adds a `finish` object with:

- `opening_text`: deterministic short text from the first planned scene.
- `cta_label`: `RUN YOUR NUMBERS` for calculated pieces and a neutral DHS label
  otherwise.
- `cta_display`: a display-safe domain/path without query parameters.
- `calculator_url`: the full seeded HTTPS URL, or null.

The worker writes all text to temporary files and passes those files to ffmpeg.
No user or model text is interpolated into a filter string. BitTrader's result is
never edited in place; the finishing pass writes a new file and replaces the
worker result only after ffmpeg exits successfully and the output probes cleanly.

## Visual design

- 1080x1920 H.264/AAC, unchanged from the current publishing contract.
- Opening overlay: two lines maximum, DHS navy translucent field, white text,
  visible for 2.8 seconds.
- Captions: white base, DHS gold active word, smaller scale change and smaller
  type than the current yellow 140% karaoke treatment.
- Final card: dimmed calculator screen where available, navy veil, gold eyebrow,
  white destination, white brokerage line, and DHS mark.
- No generic subscribe button and no second CTA.

## Quality gates

The worker refuses delivery when any of these is true:

- duration is outside 20-35 seconds;
- fewer than seven scene prompts were provided or prompts repeat after
  normalization;
- the full narration exceeds 75 words;
- a calculated piece has no seeded calculator URL;
- final-card text files are missing or empty;
- ffmpeg cannot produce a valid 1080x1920 file with audio;
- OCR over the central picture area detects an unapproved sequence of three or
  more digits before the final card.

OCR is a defense in depth check, not a claim that arbitrary generated writing can
always be understood. Human approval remains mandatory.

## Existing queue

Pieces 83 and 85 were produced or queued under the old contract. They must not be
approved or rebuilt unchanged. After deployment, reject them with a precise
quality reason and regenerate the calculated topic through the corrected writer.
No scheduled or published Buffer item is modified.

## Verification and deployment

Tests cover editorial word/scene limits, deterministic render metadata, pure
ffmpeg command construction, real ffmpeg output, OCR refusal, BitTrader profile
isolation, and subtitle styling. A production candidate must also render one
complete QA piece on the ROG, pass automatic checks, and be inspected at opening,
result, calculator, and final-card frames before Eko and BitTrader are pushed and
their live services updated.
