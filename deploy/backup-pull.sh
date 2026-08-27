#!/usr/bin/env bash
# Pull the production backups off the VPS and keep a copy on the ROG.
#
# Runs ON THE ROG, over the tailnet. Install:
#   crontab -e →  45 4 * * *  /home/enderj/eko-backup-pull.sh >> /home/enderj/.eko-backup-pull.log 2>&1
#   (ANY new cron on the ROG goes ABOVE the `# ===== BitTrader YouTube Pipeline`
#    marker: that block is restored append-only and eats whatever follows it.)
#
# WHY THE ROG PULLS INSTEAD OF THE VPS PUSHING — this is the whole point:
# a push needs credentials on the VPS that can write to the backup store, so
# anything that owns the VPS owns its backups too and can wipe them on the way
# out. A pull needs nothing on the VPS at all. It also happens to be the only
# direction that works: the VPS cannot reach the ROG over SSH (measured
# 27-ago-2026, connection times out), while the ROG reaches the VPS fine.
#
# The copy this makes is the ONLY one that survives losing the droplet. The
# dumps that `backup-db.sh` writes live on the same disk as the database they
# came from, which covers a bad migration or a `docker compose down -v` — not a
# machine that is gone.
set -euo pipefail

REMOTE="${EKO_BACKUP_REMOTE:-enderj@100.116.187.14}"   # VPS over the tailnet
REMOTE_DIR="${EKO_BACKUP_REMOTE_DIR:-eko-realtors-backups}"
OUT_DIR="${EKO_BACKUP_PULL_DIR:-$HOME/eko-realtors-backups-vps}"
KEEP="${EKO_BACKUP_PULL_KEEP:-30}"
MIN_BYTES="${EKO_BACKUP_MIN_BYTES:-20000}"
# postgres:16-alpine is already on this machine (the stopped production db used
# it). Used instead of `docker exec` because there is no database container
# running here — and there must not be one: see the migration notes.
PG_IMAGE="${EKO_PG_IMAGE:-postgres:16-alpine}"

mkdir -p "$OUT_DIR"

# `--ignore-existing` rather than a full sync: these files are immutable once
# written, so re-transferring them is waste, and it means a truncated local file
# is never silently "repaired" into looking complete. Deliberately NOT
# `--delete`: retention here is ours to decide, and mirroring the remote's
# deletions would mean a single bad night on the VPS could empty the only
# off-machine copy we have.
# Both halves of the set, and the roles half is not optional: the data dump
# carries the tenant-isolation policies but not the role they name, so a copy
# without `eko-roles-*.sql` restores every row with no row-level security at
# all. Pulling one and not the other would build an off-machine backup that
# looks complete and comes back insecure.
rsync -az --ignore-existing --timeout=120 \
  -e 'ssh -o BatchMode=yes -o ConnectTimeout=15' \
  "$REMOTE:$REMOTE_DIR/eko-realtors-*.dump" "$REMOTE:$REMOTE_DIR/eko-roles-*.sql" "$OUT_DIR/" 2>/dev/null \
  || { echo "$(date -Is) FATAL: pull from $REMOTE failed — local copies left untouched" >&2; exit 1; }

# Verify what actually landed here, rather than trusting that the far side
# verified it. Same two questions `backup-db.sh` asks, asked again on this
# machine, because a transfer can truncate a file that was perfectly good when
# it left. A backup nobody has ever read back is a belief, not a backup.
newest="$(ls -1t "$OUT_DIR"/eko-realtors-*.dump 2>/dev/null | head -1 || true)"
if [ -z "$newest" ]; then
  echo "$(date -Is) FATAL: no dumps present after pull — nothing rotated" >&2
  exit 1
fi

size="$(wc -c < "$newest")"
if [ "$size" -lt "$MIN_BYTES" ]; then
  echo "$(date -Is) FATAL: newest local dump $newest is $size bytes — not rotating" >&2
  exit 1
fi

entries="$(docker run --rm -i "$PG_IMAGE" pg_restore -l < "$newest" 2>/dev/null | grep -c '^[0-9]' || true)"
if [ "${entries:-0}" -lt 10 ]; then
  echo "$(date -Is) FATAL: $newest lists only ${entries:-0} entries — not rotating" >&2
  exit 1
fi

# The roles half. Checked by content, not by presence: an empty or truncated
# file passes `-f` and fails at 3am.
roles="$(ls -1t "$OUT_DIR"/eko-roles-*.sql 2>/dev/null | head -1 || true)"
if [ -z "$roles" ] || ! grep -q 'CREATE ROLE eko_app' "$roles"; then
  echo "$(date -Is) FATAL: no usable roles dump alongside $newest — a restore from this set would come back with no row-level security. Not rotating." >&2
  exit 1
fi

age_days=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 86400 ))
echo "$(date -Is) ok: $(basename "$newest") · $size bytes · $entries entries · roles $(basename "$roles") · newest is ${age_days}d old"

# A stale newest file means the VPS side stopped producing dumps and nobody
# noticed — the failure mode where the pull keeps "succeeding" forever against
# a frozen source. Loud on stderr so cron mails it / the log shows it.
if [ "$age_days" -gt 3 ]; then
  echo "$(date -Is) WARNING: newest backup is ${age_days} days old — the VPS side has stopped producing dumps" >&2
fi

ls -1t "$OUT_DIR"/eko-realtors-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$(date -Is) retention: kept newest $KEEP in $OUT_DIR"
