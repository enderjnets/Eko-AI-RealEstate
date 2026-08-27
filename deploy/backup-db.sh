#!/usr/bin/env bash
# Nightly Postgres backup for Eko AI Realtors (custom-format dump), with retention.
#
# Runs ON THE VPS, where production lives since the 27-ago-2026 cutover. Install:
#   crontab -e →  15 4 * * *  /home/enderj/Eko-AI-RealEstate/deploy/backup-db.sh >> /home/enderj/eko-realtors-backup.log 2>&1
#
# Why this exists at all: until 27-ago-2026 this product had NO backup of any
# kind. Not on the ROG (timeshift excludes `/var/lib/docker/*` as a built-in
# rule that `timeshift.json` cannot override — measured in the snapshot's own
# exclude.list), and not on the VPS. 38 leads and 72 messages belonging to real
# clients of a licensed broker sat on a single volume with no second copy.
#
# Modelled on `~/Black-Volt-Mobility/deploy/backup-db.sh`, which has run nightly
# on this same machine since June, with one addition explained at `_usable`.
#
# ── HOW TO RESTORE (the order matters, and step 2 is the one that gets missed) ─
#   1. Bring up an empty postgres:16-alpine and create the database.
#   2. Apply the ROLES file FIRST, then give eko_app a password:
#        psql -U eko -d postgres -f eko-roles-<stamp>.sql
#        psql -U eko -d postgres -c "ALTER ROLE eko_app WITH PASSWORD '<nueva>'"
#      Skipping this restores every row and NONE of the row-level security, and
#      nothing warns you: pg_restore prints the errors and exits 0.
#   3. pg_restore -U eko -d eko_realestate --no-owner eko-realtors-<stamp>.dump
#   4. Put that same password in DATABASE_URL_APP in `.env`.
#   5. Verify with row counts AND with a tenant check — that a session bound to
#      one org cannot see another's leads — not just that the app starts.
set -euo pipefail

CONTAINER="${EKO_DB_CONTAINER:-eko-realestate-db}"
DB_USER="${POSTGRES_USER:-eko}"
DB_NAME="${POSTGRES_DB:-eko_realestate}"
OUT_DIR="${EKO_BACKUP_DIR:-$HOME/eko-realtors-backups}"
KEEP="${EKO_BACKUP_KEEP:-14}"

# A dump smaller than this is not a small database, it is a broken dump. The
# real one is ~112 KB; an empty-but-valid schema-only dump is around 30 KB.
# Deliberately well under the real size so that a genuinely shrinking database
# (a purge, a client leaving) does not trip it — this floor is here to catch
# "the container came up on an empty volume", not to police size.
MIN_BYTES="${EKO_BACKUP_MIN_BYTES:-20000}"

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_DIR/eko-realtors-$STAMP.dump"

# Custom format: compressed, and restorable selectively with pg_restore.
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$OUT"

# ── Is this dump usable? Asked BEFORE anything old is deleted. ───────────────
#
# `set -e` already aborts on a pg_dump that exits non-zero, so the case this
# guards is the other one: a dump that succeeds and is worthless. If the db
# container ever comes up on a fresh/empty volume, pg_dump returns 0 and writes
# a valid file containing nothing — and the retention step below would then
# delete fourteen good backups to make room for it. That is how a backup system
# eats itself, and it does it silently, on the one night you needed it.
#
# Two cheap questions, neither of which restores anything:
#   - is there enough bytes for it to be real?
#   - does pg_restore agree it is a dump, and does it list actual tables?
_usable() {
  local f="$1" size entries
  size="$(wc -c < "$f")"
  if [ "$size" -lt "$MIN_BYTES" ]; then
    echo "$(date -Is) FATAL: dump is $size bytes, under the $MIN_BYTES floor — keeping older backups untouched" >&2
    return 1
  fi
  # `pg_restore -l` reads the table of contents without touching any database.
  # A real dump of this schema lists dozens of entries; a corrupt file makes
  # pg_restore exit non-zero, and `|| true` keeps `set -e` from hiding which of
  # the two checks actually failed.
  entries="$(docker exec -i "$CONTAINER" pg_restore -l < "$f" 2>/dev/null | grep -c '^[0-9]' || true)"
  if [ "${entries:-0}" -lt 10 ]; then
    echo "$(date -Is) FATAL: pg_restore lists only ${entries:-0} entries — dump is not usable, keeping older backups untouched" >&2
    return 1
  fi
  echo "$(date -Is) verified $entries table-of-contents entries"
  return 0
}

if ! _usable "$OUT"; then
  # The bad dump is kept, not deleted: it is the evidence of what went wrong,
  # and it is named with a timestamp so it cannot be mistaken for a good one by
  # the pull side, which checks the same two things.
  mv "$OUT" "$OUT.rejected"
  echo "$(date -Is) rejected dump parked at $OUT.rejected — NO retention ran" >&2
  exit 1
fi

echo "$(date -Is) wrote $OUT ($(du -h "$OUT" | cut -f1))"

# ── The roles, which the data dump does NOT contain ──────────────────────────
#
# Measured, not assumed: restoring this dump into a clean cluster produces
# exactly 36 errors, and all 36 are `role "eko_app" does not exist`. The dump
# carries 49 POLICY/ACL entries — every tenant-isolation policy is in there —
# but a policy that names a role Postgres has never heard of cannot be applied.
# `pg_dump` of one database is database-scoped; roles are cluster-scoped and
# live in `pg_dumpall`. Without this file, a 3am recovery restores the rows and
# silently loses the isolation between agencies, which is the one thing this
# schema must never lose.
#
# `--no-role-passwords` on purpose: this writes role names, attributes and
# memberships, and NOT the password hashes. Recovery creates `eko_app` with a
# fresh password and puts the same one in DATABASE_URL_APP — a backup file is
# the wrong place to keep credentials that are already in `.env`.
ROLES="$OUT_DIR/eko-roles-$STAMP.sql"
docker exec "$CONTAINER" pg_dumpall -U "$DB_USER" --roles-only --no-role-passwords > "$ROLES"
if ! grep -q 'CREATE ROLE eko_app' "$ROLES"; then
  echo "$(date -Is) FATAL: roles dump does not define eko_app — a restore from this set would come back without RLS" >&2
  mv "$ROLES" "$ROLES.rejected"
  exit 1
fi
echo "$(date -Is) wrote $ROLES ($(wc -l < "$ROLES") lines)"

# Retention: keep the newest $KEEP good dumps. Rejected ones are not matched by
# these globs (`*.rejected`), so a run of failures cannot rotate away the last
# known-good backup — it just accumulates evidence until someone looks.
ls -1t "$OUT_DIR"/eko-realtors-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "$OUT_DIR"/eko-roles-*.sql 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$(date -Is) retention: kept newest $KEEP in $OUT_DIR"
