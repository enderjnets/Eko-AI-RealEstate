# Platform Link Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve each approved Denver Home Story destination while publishing a complete, platform-tagged HTTPS link for every content piece.

**Architecture:** `buffer_publisher.with_platform_utm` remains the single mutation point before the payload reaches Buffer. Small private helpers identify the configured hostname, parse the first matching caption URL, preserve path/query/fragment, and replace only the four managed UTM values.

**Tech Stack:** Python 3.11+, `urllib.parse`, regular expressions, pytest, SQLAlchemy integration tests.

**Spec:** `docs/superpowers/specs/2026-09-13-platform-link-attribution.md`

## Global Constraints

- Only the first URL whose hostname exactly matches the configured CTA hostname may change.
- A root destination becomes `/start`; explicit paths and fragments remain intact.
- Output uses the configured scheme and authority and sets source, medium, campaign, and `piece-<id>`.
- Captions with no matching link remain byte-for-byte unchanged.
- No database migration or content state-machine change belongs in this plan.
- Run each new test once in red before writing production code.

---

### Task 1: Normalize and tag the approved site link

**Files:**
- Modify: `backend/app/services/buffer_publisher.py`
- Test: `backend/tests/test_buffer_publisher.py`

**Interfaces:**
- Consumes: `text`, configured `cta_url`, `PublicationPlatform`, `piece_id`, and campaign.
- Produces: unchanged public signature `with_platform_utm(text, cta_url, platform, piece_id, campaign) -> str`.

- [ ] **Step 1: Replace the old boundary test with failing destination tests**

Add cases equivalent to:

```python
def test_explicit_path_is_preserved_and_tagged() -> None:
    text = "Run it: denverhomestory.com/calculator?mode=rent#result."
    out = with_platform_utm(text, CTA, PublicationPlatform.YOUTUBE, 21, "video")
    assert "https://www.denverhomestory.com/calculator?mode=rent&" in out
    assert "utm_source=youtube" in out
    assert "utm_content=piece-21" in out
    assert "#result." in out

def test_root_routes_to_social_hub() -> None:
    out = with_platform_utm(f"Start: {CTA}", CTA, PublicationPlatform.TIKTOK, 4, "video")
    assert out.startswith("Start: https://www.denverhomestory.com/start?")

def test_lookalike_host_is_untouched() -> None:
    text = "https://denverhomestory.com.example.org/calculator"
    assert with_platform_utm(text, CTA, PublicationPlatform.INSTAGRAM, 2, "video") == text
```

Also test `http://`, `www.`, bare domain, existing UTM replacement, retained
non-UTM query values, `/#consult`, comma/period/closing-parenthesis punctuation,
two mentions where only the first changes, no configured CTA, and no matching
site link.

- [ ] **Step 2: Run focused tests and confirm red**

Run:

```bash
cd backend
python -m pytest tests/test_buffer_publisher.py -k "source or link or utm or path or root or lookalike" -q
```

Expected: at least the explicit-path, bare-domain, and root-to-start tests fail.

- [ ] **Step 3: Implement hostname-safe normalization**

Use `urlsplit`, `urlunsplit`, `parse_qsl`, and `urlencode`. Derive the accepted
host from `cta_url`, allowing the same host with or without a leading `www.`.
Build a boundary-safe regex and strip only terminal prose punctuation from the
matched candidate. Parse a schemeless candidate by temporarily prepending
`https://`. Refuse when the normalized candidate hostname differs from the
configured hostname. Set `/start` only when the candidate path is empty or `/`.
Remove existing managed UTM pairs, append the four current values, reconstruct
the URL with the configured scheme and authority, then splice that one result
back into the original caption.

The central construction is:

```python
managed = {"utm_source", "utm_medium", "utm_campaign", "utm_content"}
pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in managed]
pairs.extend([
    ("utm_source", platform.value),
    ("utm_medium", "social"),
    ("utm_campaign", campaign),
    ("utm_content", f"piece-{piece_id}"),
])
path = parts.path
if path in ("", "/") and not parts.fragment:
    path = "/start"
tagged = urlunsplit((configured.scheme, configured.netloc, path, urlencode(pairs), parts.fragment))
```

- [ ] **Step 4: Run unit and publisher integration tests**

Run: `cd backend && python -m pytest tests/test_buffer_publisher.py -q`

Expected: PASS, including the existing three-platform payload and fair-housing tests.

- [ ] **Step 5: Commit the normalization**

```bash
git add backend/app/services/buffer_publisher.py backend/tests/test_buffer_publisher.py
git commit -m "fix(content): preserve destinations in tracked social links" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
