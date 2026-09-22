# Denver content lines implementation plan

1. Add failing unit tests for the weekly calendar, disabled Ask alternation, editorial-date reservation, fresh/stale DMAR parsing, per-series word/scene rules, deterministic CTAs, render bounds and link-free publishing.
2. Add the content-series enum, contract module and database migration. Default existing rows to conversion without changing their dates or statuses.
3. Add the official DMAR source reader with strict host, report type and freshness validation.
4. Make the writer reserve the next date after the existing queue, choose the series, build the corresponding brief, apply only that series' deterministic CTA, and persist the series/source/date.
5. Carry the series contract into render jobs and make the ROG finishing pass validate per-series duration, scene and narration bounds.
6. Make Buffer's link gate conditional: required for conversion, forbidden as a deterministic CTA for growth and authority. Keep slot discovery and existing publication rows unchanged.
7. Expose series, editorial date and source through the API and show them on the approval card with English and Spanish interface labels.
8. Run focused tests, backend suite, worker suite, frontend tests/typecheck/lint/build, migration upgrade/downgrade check and Docker builds.
9. Re-read the original requirements, inspect the diff and the first changelog lines, check remote main/version, rebase if needed, bump both versions, commit and push.
10. Merge through the repository workflow, deploy only Eko AI Realtors services that changed, run migrations, verify health/version/content API in production, and confirm existing Buffer publication rows were not changed.
