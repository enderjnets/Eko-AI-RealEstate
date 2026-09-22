# Denver Home Story Video Quality v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every generated DHS video short, visually varied, calculator-grounded, branded, and mechanically reviewable before human approval.

**Architecture:** Eko owns the editorial and finishing contracts. BitTrader on the ROG supplies locally generated visual footage; the Eko worker adds deterministic overlays and rejects outputs that violate the approved contract.

**Tech Stack:** FastAPI, Pydantic, Python worker, ffmpeg/ffprobe, Chromium headless, Tesseract OCR, pytest, BitTrader channel profiles and ASS subtitles.

**Spec:** `docs/superpowers/specs/2026-09-21-video-quality-v2-design.md`

## Global Constraints

- English publication copy only.
- Model-written script: 45-65 words; finished narration: no more than 75 words.
- Seven to nine distinct prompts; calculated rail uses eight.
- Final duration: 20-35 seconds.
- Calculator figures and seeded URL must originate from `calculator.build_snapshot` inputs.
- Existing scheduled and published Buffer items stay unchanged.
- Eko and BitTrader deploy only after their full relevant suites and one real ROG render pass.

---

### Task 1: Enforce the editorial contract

**Files:**
- Modify: `backend/app/services/content_writer.py`
- Modify: `backend/app/services/content_calculated.py`
- Test: `backend/tests/test_content_writer.py`
- Test: `backend/tests/test_content_calculated.py`

**Interfaces:**
- Produces: generated `ContentPiece.scenes` with 7-9 distinct prompts and narration within the approved word budget.

- [ ] Add failing tests for script-length findings, seven-scene minimum, nine-scene maximum, and eight deterministic calculated scenes.
- [ ] Run the focused tests and confirm the new assertions fail for the current 60-120-word/four-scene contract.
- [ ] Change the English and Spanish system contracts to 45-65 words and 7-9 scenes; make word/scene counts stored violations so prompt drift cannot pass.
- [ ] Expand calculated scene prompts and screen text to eight distinct shots derived from the same `Plan` inputs.
- [ ] Run both focused suites green and commit.

### Task 2: Send deterministic finishing metadata to the worker

**Files:**
- Modify: `backend/app/api/v1/render_jobs.py`
- Test: `backend/tests/test_render_jobs.py`

**Interfaces:**
- Produces: `JobInput.finish: {opening_text, cta_label, cta_display, calculator_url}`.

- [ ] Add failing route tests for calculated and ordinary pieces, including exact seeded query values.
- [ ] Run the focused tests and confirm `finish` is absent.
- [ ] Build the metadata only from stored scenes, calculator inputs, and configured DHS base URL.
- [ ] Run the focused suite green and commit.

### Task 3: Add the DHS finishing pass and quality gates

**Files:**
- Create: `worker/finish.py`
- Modify: `worker/main.py`
- Modify: `worker/verify.py`
- Test: `worker/tests/test_finish.py`
- Test: `worker/tests/test_worker.py`

**Interfaces:**
- Consumes: BitTrader MP4 plus `JobInput.finish`, scene prompts, narration, brokerage line, and DHS mark.
- Produces: `finish.apply(source, destination, spec, mark) -> FinishReport` and terminal `verify.Rejected` failures.

- [ ] Add failing unit tests for duration/word/scene/prompt gates and safe textfile-based ffmpeg command construction.
- [ ] Add failing real-ffmpeg tests for a branded fallback end card and an authorized calculator screenshot card.
- [ ] Add a failing OCR test that detects a central three-digit address and ignores the caption/final-card regions.
- [ ] Implement headless Chromium capture with a branded-card fallback, deterministic overlays, and atomic output replacement.
- [ ] Integrate the finish pass after BitTrader and before delivery; verify the resulting MP4 again.
- [ ] Run worker suites green and commit.

### Task 4: Give DHS restrained subtitles and remove BitTrader's generic hook

**Files (BitTrader repository):**
- Modify: `agents/channel_profile.py`
- Modify: `agents/karaoke_subs.py`
- Modify: `agents/profiles/denver_home_story.json`
- Test: `agents/test_dhs_subtitle_style.py`
- Test: `agents/test_hook_overlay_v21424.py`

**Interfaces:**
- Produces: optional profile-specific subtitle colors, size, scale, and grouping while preserving existing defaults for every other channel.

- [ ] Add failing tests proving DHS uses white/gold restrained captions and no BitTrader hook, while the default channel keeps its current yellow style.
- [ ] Run focused tests and confirm the DHS assertions fail.
- [ ] Add optional profile fields with backward-compatible defaults and consume them when writing ASS.
- [ ] Set the DHS profile values and `hook_overlay_words` to zero.
- [ ] Run focused and full BitTrader test suites green and commit.

### Task 5: Release metadata and operator documentation

**Files:**
- Modify: `frontend/lib/version.ts`
- Modify: `backend/app/config.py`
- Modify: `CHANGELOG.md`
- Modify: `worker/README.md`

**Interfaces:**
- Produces: one shared release number and a deployment/recovery procedure that includes the ROG worker.

- [ ] Add the next unused release number after fetching `origin/main`.
- [ ] Document Chromium/Tesseract prerequisites, the finishing order, and the rollback path.
- [ ] Run version parity tests and inspect the first ten changelog lines manually.
- [ ] Commit.

### Task 6: End-to-end verification and production rollout

**Files:**
- Create outside git: `eko-content-review-2026-09-14/video-quality-v2/` QA artifacts.

**Interfaces:**
- Consumes: tested Eko and BitTrader commits.
- Produces: one inspected MP4, production deployment, and clean queue state.

- [ ] Run Eko backend, worker, frontend, typecheck, lint, and build suites.
- [ ] Run the full BitTrader suite under `~/.venvs/bittrader/bin/python` on the ROG-compatible checkout.
- [ ] Deploy the BitTrader commit to the ROG without touching its data directories; restart only `eko-render-worker.service` after Eko worker code is synchronized.
- [ ] Render a non-publishing QA job through the real ROG path and inspect opening, result, calculator, and final frames plus ffprobe/OCR reports.
- [ ] If and only if every gate is green, push both branches, merge through reviewed PRs, deploy Eko frontend/backend as required, and confirm production health/version.
- [ ] Reject pieces 83 and 85 as old-format artifacts, regenerate the calculator topic, and confirm no scheduled/published Buffer item changed.

