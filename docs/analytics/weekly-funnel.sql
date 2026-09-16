-- The weekly funnel: how many people, and how many of them did anything.
--
-- This is the number the 30-sep-2026 re-evaluation reads. It exists as a saved
-- query rather than a dashboard because a dashboard invites daily glancing at
-- a figure that only means something over weeks, and because the definition
-- below is the part worth arguing about, not the rendering.
--
-- HOW TO RUN IT
--   ssh ender-vps "docker exec eko-realestate-db psql -U eko -d eko_realestate \
--     -X -A -F'|' -f -" < docs/analytics/weekly-funnel.sql
-- or paste the body after `SET app.current_org_id='1';` in an interactive psql.
-- The SET is not optional: every table here is under row-level security and a
-- session without an organization bound sees nothing at all, which looks
-- exactly like a week with no visitors.
--
-- ── What counts as a person ──────────────────────────────────────────────
-- `traffic_class NOT IN ('automated','test')` AND scrolled at least halfway.
--
-- The scroll is doing most of the work, and deliberately so. It excludes every
-- machine the classifier has not caught yet: of the eight sessions that ever
-- started the contact form, seven were data centres and all seven scrolled
-- zero. So this figure was already honest before the classifier learned to
-- name them, and it stays honest against the next crawler from a region
-- nobody has listed.
--
-- ── What this figure CANNOT tell you, and must not be read as ────────────
-- Anything before roughly 12-sep-2026 includes our own testing. There was no
-- `?eko_qa=1` marker then, and 104 of the first 193 sessions came from the
-- Denver area, which is also where we are. Treat early September as an upper
-- bound on strangers, never as a baseline to beat.
--
-- ── The baseline, measured 16-sep-2026 ───────────────────────────────────
-- Sessions per day have held between 6 and 44. Sessions that scrolled at
-- least halfway have not:
--
--     09-06  44 sessions  13 scrolled        09-13   9 sessions   3 scrolled
--     09-07  14            7                 09-14   9            2
--     09-10  34           15                 09-15  20            2
--     09-11  12            4                 09-16   6            0
--
-- Leads, ever: 0. Forms submitted, ever: 0. Forms STARTED by a real visitor,
-- ever: 0.
--
-- Eight rows carry `form_started_at`. Seven are data centres. The eighth is
-- session 208 — The Pinery, Colorado, 15-sep — which is **our own Playwright**
-- and says so in `traffic_class = 'test'`. It read the page to 75%, answered
-- the calculator at $374,000 and began the form forty-eight seconds after
-- landing, which is what a real prospect would look like, and is why it fools
-- anyone who queries `form_started_at` without also reading `traffic_class`.
-- That mistake was made here on 16-sep and reported as a finding before being
-- caught.
--
-- So: every filter in the queries below excludes `test` for a reason, and the
-- honest summary of where this stands is that nobody outside this team has
-- ever touched the form.

SET app.current_org_id = '1';

SELECT
  to_char(
    date_trunc('week', first_seen_at AT TIME ZONE 'America/Denver'), 'YYYY-MM-DD'
  )                                                           AS week_of,
  source,
  count(*)                                                    AS people,
  count(*) FILTER (WHERE cta_clicks > 0)                      AS tapped_cta,
  count(*) FILTER (WHERE tel_clicks > 0)                      AS tapped_phone,
  count(*) FILTER (WHERE form_started_at IS NOT NULL)         AS started_form,
  count(*) FILTER (WHERE form_submitted_at IS NOT NULL)       AS sent_form,
  count(*) FILTER (WHERE lead_id IS NOT NULL)                 AS became_lead
FROM landing_sessions
WHERE coalesce(traffic_class, '') NOT IN ('automated', 'test')
  AND coalesce(max_scroll_pct, 0) >= 50
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;

-- The same thing by day, for the fortnight. Use this one to tell a real change
-- from the ordinary noise of a site with single-digit daily traffic: one
-- Facebook share moved a Sunday by thirty sessions, and a week that averages
-- two a day cannot be read from any single day.
SELECT
  (first_seen_at AT TIME ZONE 'America/Denver')::date          AS day,
  count(*)                                                     AS all_sessions,
  count(*) FILTER (
    WHERE coalesce(traffic_class, '') NOT IN ('automated', 'test')
      AND coalesce(max_scroll_pct, 0) >= 50
  )                                                            AS people,
  count(*) FILTER (WHERE coalesce(max_scroll_pct, 0) = 0)      AS never_scrolled
FROM landing_sessions
WHERE first_seen_at > now() - interval '14 days'
GROUP BY 1
ORDER BY 1;

-- Who the classifier thinks they are. `unknown` falling is the point of the
-- work; `unknown` at zero would mean the classifier had started guessing.
SELECT
  coalesce(traffic_class, 'null')  AS class,
  coalesce(traffic_class_reason, '-') AS reason,
  count(*)                         AS sessions
FROM landing_sessions
GROUP BY 1, 2
ORDER BY 3 DESC;
