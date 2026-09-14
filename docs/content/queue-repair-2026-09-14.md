# Content queue selection repair

The production query selected fully scheduled pieces before applying the daily
limit. Their deliveries were correctly skipped, but they occupied every slot
in the query and prevented approved pieces from being considered.

The selection now requires a configured platform with no publication row, a
pending row, or a failed row on a piece explicitly approved again. Scheduled,
published and ambiguous publishing rows remain owned by their original delivery
and are never retried by this change. Reconciliation still runs first.

Validation: regression observed failing (zero deliveries for the fresh piece),
then passing; six additional cases cover pending, missing, reapproved failures,
non-reapproved failures, publishing and published rows. Publisher, approval gate
and tenant isolation suites: 181 passed against a dedicated local Postgres.

## Deployment control

Before recreating the Eko backend, set CONTENT_PUBLISH_MAX_PER_DAY=0 in the
production environment. Leave CONTENT_PUBLISH_ENABLED=true: reconciliation still
runs before the daily-cap return. Buffer schedules remain active independently.
Do not restore the previous value (8) until the approved backlog has been
reviewed for duplicates, season windows and calculator consistency. This is an
operator hold, not a code default.

No schema migration. Roll back to v0.102.1 if backend health or reconciliation
fails; retain the hold during rollback. Do not change existing publication IDs,
media, dates or statuses as part of deploying this fix.

The fix retains the existing daily cap semantics: resumption competes for the
remaining per-tick selection budget. It does not change editorial dates or add
a bulk retry feature.
